import pytest
import sqlite3
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

def test_delete_book_endpoint(client, test_db):
    # Setup dummy data
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO books (id, filename, title, author, path) VALUES (1, 'test.pdf', 'Delete Me', 'Author', 'test.pdf')")
    cursor.execute("INSERT INTO books_fts (rowid, title, author) VALUES (1, 'Delete Me', 'Author')")
    conn.commit()
    conn.close()

    # Mock filesystem and shutil
    # We patch Path.mkdir and Path.exists on the Path class itself
    with (patch("api_v1.DB_FILE", test_db),
          patch("api_v1.LIBRARY_ROOT", Path("/tmp")),
          patch("pathlib.Path.mkdir"),
          patch("pathlib.Path.exists", return_value=True),
          patch("shutil.move")):
        
        response = client.delete('/api/v1/books/1')
        data = response.get_json()
        if response.status_code != 200:
            print(f"ERROR: {data}")
        
        assert response.status_code == 200
        assert data['success'] is True

        # Verify DB entry is gone
        conn = sqlite3.connect(test_db)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM books WHERE id = 1")
        assert cursor.fetchone() is None
        conn.close()
