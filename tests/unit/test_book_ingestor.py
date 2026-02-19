import pytest
import sqlite3
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
from services.ingestor import ingestor_service
from services.library import library_service

def test_calculate_hash(tmp_path):
    """Verifies SHA256 calculation."""
    test_file = tmp_path / "test.txt"
    content = b"Hello MathStudio"
    test_file.write_bytes(content)
    
    expected_hash = hashlib.sha256(content).hexdigest()
    assert library_service.calculate_hash(test_file) == expected_hash

def test_check_duplicate_hash(test_db):
    """Verifies exact hash match detection."""
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    file_hash = "fake_hash_123"
    cursor.execute("INSERT INTO books (filename, path, file_hash) VALUES (?, ?, ?)", 
                   ("existing.pdf", "04_Algebra/existing.pdf", file_hash))
    conn.commit()
    
    with patch("core.config.DB_FILE", Path(test_db)):
        dup_type, match = library_service.check_duplicate(file_hash, "Title", "Author")
        assert dup_type == "HASH"
        assert match['path'] == "04_Algebra/existing.pdf"

def test_check_duplicate_semantic(test_db):
    """Verifies semantic (Title/Author) match detection."""
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO books (filename, path, title, author) VALUES (?, ?, ?, ?)", 
                   ("existing.pdf", "04_Algebra/existing.pdf", "Algebraic Topology", "Allen Hatcher"))
    conn.commit()
    
    with patch("core.config.DB_FILE", Path(test_db)):
        dup_type, match = library_service.check_duplicate("new_hash", "Algebraic", "Hatcher")
        assert dup_type == "SEMANTIC"
        assert "existing.pdf" in match['path']

def test_analyze_content_mock(mock_gemini):
    """Verifies the AI analysis orchestration."""
    structure_data = {
        'toc': [['1', 'Chapter 1', 1]],
        'text_sample': 'This is a book about Algebra.',
        'page_count': 100
    }
    
    mock_response = {
        "title": "Clean Title",
        "author": "Clean Author",
        "msc_class": "Algebra",
        "target_path": "04_Algebra",
        "audience": "Grad",
        "has_exercises": True,
        "has_solutions": False,
        "summary": "A great book.",
        "description": "Longer blurb",
        "toc": [],
        "page_offset": 0
    }
    mock_gemini.models.generate_content.return_value.text = json.dumps(mock_response)
    
    result = ingestor_service.analyze_content(structure_data)
    assert result["title"] == "Clean Title"
    assert result["msc_class"] == "Algebra"
