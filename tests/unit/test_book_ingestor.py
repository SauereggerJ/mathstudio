import pytest
import sqlite3
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
from book_ingestor import BookIngestor

@pytest.fixture
def ingestor(test_db):
    """Provides a BookIngestor instance pointing to the test database."""
    with patch("book_ingestor.DB_FILE", test_db):
        return BookIngestor(dry_run=True)

def test_calculate_hash(ingestor, tmp_path):
    """Verifies SHA256 calculation."""
    test_file = tmp_path / "test.txt"
    content = b"Hello MathStudio"
    test_file.write_bytes(content)
    
    expected_hash = hashlib.sha256(content).hexdigest()
    assert ingestor.calculate_hash(test_file) == expected_hash

def test_truncate_filename(ingestor):
    """Verifies filename truncation while preserving extension."""
    long_name = "A" * 300 + ".pdf"
    truncated = ingestor.truncate_filename(long_name, max_len=100)
    
    assert len(truncated) == 100
    assert truncated.endswith(".pdf")
    assert truncated.startswith("A" * 10)

def test_map_category_to_folder(ingestor):
    """Verifies MSC class mapping logic."""
    assert ingestor.map_category_to_folder("Linear Algebra") == "04_Algebra"
    assert ingestor.map_category_to_folder("Quantum Physics") == "01_Mathematical_Physics"
    assert ingestor.map_category_to_folder("Unknown Topic") == "99_General_and_Diverse"

def test_check_duplicate_hash(ingestor, test_db):
    """Verifies exact hash match detection."""
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    file_hash = "fake_hash_123"
    # Insert a book with this hash
    cursor.execute("INSERT INTO books (filename, path, file_hash) VALUES (?, ?, ?)", 
                   ("existing.pdf", "04_Algebra/existing.pdf", file_hash))
    conn.commit()
    
    # Mock filesystem check since the file doesn't actually exist
    with patch("pathlib.Path.exists", return_value=True):
        dup_type, match = ingestor.check_duplicate(file_hash, "Title", "Author")
        assert dup_type == "HASH"
        assert match[1] == "04_Algebra/existing.pdf"

def test_check_duplicate_semantic(ingestor, test_db):
    """Verifies semantic (Title/Author) match detection."""
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    # Insert a book
    cursor.execute("INSERT INTO books (filename, path, title, author) VALUES (?, ?, ?, ?)", 
                   ("existing.pdf", "04_Algebra/existing.pdf", "Algebraic Topology", "Allen Hatcher"))
    conn.commit()
    
    # Check for match (using first word logic of ingestor)
    dup_type, match = ingestor.check_duplicate("new_hash", "Algebraic", "Hatcher")
    assert dup_type == "SEMANTIC"
    assert "existing.pdf" in match[1]

def test_analyze_semantics_mock(ingestor, mock_gemini):
    """Verifies the AI analysis orchestration."""
    structure_data = {
        'toc': [['1', 'Chapter 1', 1]],
        'text_sample': 'This is a book about Algebra.',
        'page_count': 100
    }
    
    # Setup mock return value for Gemini
    mock_response = {
        "title": "Clean Title",
        "author": "Clean Author",
        "msc_class": "Algebra",
        "target_path": "04_Algebra",
        "audience": "Grad",
        "has_exercises": True,
        "has_solutions": False,
        "summary": "A great book."
    }
    mock_gemini.models.generate_content.return_value.text = json.dumps(mock_response)
    
    result = ingestor.analyze_semantics(structure_data, existing_folders=["04_Algebra"])
    assert result["title"] == "Clean Title"
    assert result["msc_class"] == "Algebra"
