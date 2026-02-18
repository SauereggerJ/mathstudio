import pytest
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock
from services.bibliography import bibliography_service

def test_find_bib_pages_mocked(test_db):
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
    
    with (patch("core.config.DB_FILE", Path(test_db)),
          patch("core.config.LIBRARY_ROOT", Path("/tmp")),
          patch("fitz.open", return_value=mock_doc),
          patch("pathlib.Path.exists", return_value=True)):
        pages, error = bibliography_service.find_bib_pages(1)
        assert error is None
        assert 100 in pages

def test_parse_citations_mocked(test_db, mock_gemini):
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

    with (patch("core.config.DB_FILE", Path(test_db)),
          patch("core.config.LIBRARY_ROOT", Path("/tmp")),
          patch("fitz.open", return_value=mock_doc),
          patch("pathlib.Path.exists", return_value=True)):
        citations, error = bibliography_service.parse_citations(1, [100])
        assert error is None
        assert len(citations) == 1
        assert citations[0]["title"] == "Real Analysis"
