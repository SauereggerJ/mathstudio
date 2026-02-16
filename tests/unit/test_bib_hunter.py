import pytest
import json
import sqlite3
from unittest.mock import patch, MagicMock
from bib_hunter import BibHunter

@pytest.fixture
def hunter(test_db):
    return BibHunter(db_file=test_db)

def test_find_bib_pages_mocked(hunter, test_db):
    # Setup DB
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO books (id, filename, title, author, path) VALUES (1, 'test.pdf', 'Test Book', 'Author', 'test.pdf')")
    conn.commit()
    conn.close()

    mock_doc = MagicMock()
    mock_doc.__len__.return_value = 100
    
    def get_page(idx):
        page = MagicMock()
        if idx == 99: # Page 100
            page.get_text.return_value = """Bibliography
1. Book A"""
        else:
            page.get_text.return_value = """Normal text"""
        return page

    mock_doc.__getitem__.side_effect = get_page
    
    with (patch("fitz.open", return_value=mock_doc),
          patch("pathlib.Path.exists", return_value=True)):
        pages, error = hunter.find_bib_pages(1)
        assert error is None
        assert 100 in pages

def test_parse_bib_with_ai_mocked(hunter, test_db, mock_gemini):
    # Setup DB
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO books (id, filename, title, author, path) VALUES (1, 'test.pdf', 'Test Book', 'Author', 'test.pdf')")
    conn.commit()
    conn.close()

    mock_doc = MagicMock()
    mock_page = MagicMock()
    mock_page.get_text.return_value = """Cited: Real Analysis by Folland"""
    mock_doc.__getitem__.return_value = mock_page
    mock_doc.__len__.return_value = 100

    mock_dict = [{"title": "Real Analysis", "author": "Folland"}]
    mock_gemini.models.generate_content.return_value.text = json.dumps(mock_dict)

    with (patch("fitz.open", return_value=mock_doc),
          patch("pathlib.Path.exists", return_value=True)):
        citations, error = hunter.parse_bib_with_ai(1, [100])
        assert error is None
        assert len(citations) == 1
        assert citations[0]["title"] == "Real Analysis"

def test_cross_check_with_library(hunter, test_db):
    # Setup DB with an owned book
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO books (id, filename, title, author, path) VALUES (1, 'folland.pdf', 'Real Analysis', 'Folland', 'folland.pdf')")
    conn.commit()
    conn.close()

    bib_list = [
        {"title": "Real Analysis", "author": "Folland"},
        {"title": "Topology", "author": "Munkres"}
    ]

    with patch("fuzzy_book_matcher.FuzzyBookMatcher.batch_match") as mock_match:
        mock_match.return_value = [
            {"found": True, "match": {"id": 1, "title": "Real Analysis", "author": "Folland"}},
            {"found": False, "match": None}
        ]
        
        enriched, error = hunter.cross_check_with_library(bib_list)
        assert error is None
        assert enriched[0]["status"] == "owned"
        assert enriched[1]["status"] == "missing"
