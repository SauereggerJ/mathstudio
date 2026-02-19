import pytest
import sqlite3
import os
from pathlib import Path
from unittest.mock import patch, MagicMock
from services.library import library_service

def test_check_sanity_existence(test_db):
    """Verifies that stale records are removed when fix=True."""
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO books (id, title, path, filename) VALUES (1, 'Missing Book', 'path/to/missing.pdf', 'missing.pdf')")
    cursor.execute("INSERT INTO books (id, title, path, filename) VALUES (2, 'Existing Book', 'path/to/exists.pdf', 'exists.pdf')")
    conn.commit()
    conn.close()

    def mock_exists(path_obj):
        return "exists.pdf" in str(path_obj)

    with (patch("core.config.DB_FILE", Path(test_db)),
          patch("core.config.LIBRARY_ROOT", Path("/tmp")),
          patch.object(Path, "exists", autospec=True) as mock_path_exists):
        
        mock_path_exists.side_effect = mock_exists
        library_service.check_sanity(fix=True)
        
        conn = sqlite3.connect(test_db)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM books")
        remaining_ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        assert 1 not in remaining_ids
        assert 2 in remaining_ids

def test_check_sanity_duplicates(test_db):
    """Verifies that content duplicates are resolved, keeping the better path."""
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    file_hash = "abc_hash"
    cursor.execute("INSERT INTO books (id, title, path, filename, file_hash) VALUES (1, 'Book', '99_General_and_Diverse/Unsorted/book.pdf', 'book.pdf', ?)", (file_hash,))
    cursor.execute("INSERT INTO books (id, title, path, filename, file_hash) VALUES (2, 'Book', '04_Algebra/book.pdf', 'book.pdf', ?)", (file_hash,))
    conn.commit()
    conn.close()

    with (patch("core.config.DB_FILE", Path(test_db)),
          patch("core.config.LIBRARY_ROOT", Path("/tmp")),
          patch.object(Path, "exists", return_value=True),
          patch("os.remove") as mock_remove):
        
        library_service.check_sanity(fix=True)
        
        conn = sqlite3.connect(test_db)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM books")
        remaining_ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        assert 1 not in remaining_ids
        assert 2 in remaining_ids
        assert mock_remove.called
