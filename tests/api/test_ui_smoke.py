import pytest
from unittest.mock import patch, MagicMock
import sqlite3

def test_ui_index_page(client):
    """Verifies that the home page renders correctly."""
    response = client.get('/')
    assert response.status_code == 200
    assert b"MathStudio" in response.data

def test_ui_admin_page(client):
    """Verifies that the admin dashboard renders correctly."""
    response = client.get('/admin')
    assert response.status_code == 200
    assert b"Dashboard" in response.data or b"Admin" in response.data

def test_ui_book_details_page(client, test_db):
    """Verifies that the book details page renders with data."""
    # Setup data
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO books (id, filename, title, author, path) VALUES (758, 'test.pdf', 'Test Book', 'Author', 'test.pdf')")
    conn.commit()
    conn.close()

    # We need to mock search_service calls that might be made in the view
    with (patch("services.search.search_service.get_similar_books", return_value=[]),
          patch("services.search.search_service.get_chapters", return_value=[])):
        response = client.get('/book/758')
        assert response.status_code == 200
        assert b"Test Book" in response.data
        assert b"Author" in response.data

def test_ui_notes_page(client):
    """Verifies that the notes list page renders."""
    response = client.get('/notes')
    assert response.status_code == 200
    assert b"Note" in response.data
