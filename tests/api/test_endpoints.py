import pytest
import sqlite3
import json
from unittest.mock import patch

def test_search_endpoint(client, test_db, mock_gemini):
    # Setup dummy data
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO books (id, filename, title, author, path) VALUES (1, 'test.pdf', 'Test Book', 'Author', 'test.pdf')")
    cursor.execute("INSERT INTO books_fts (rowid, title, author) VALUES (1, 'Test Book', 'Author')")
    conn.commit()
    conn.close()

    with patch("services.search.search_service.search") as mock_search:
        mock_search.return_value = {
            'results': [{'id': 1, 'title': 'Test Book', 'author': 'Author', 'path': 'test.pdf'}],
            'total_count': 1,
            'expanded_query': None
        }
        response = client.get('/api/v1/search?q=Test')
        assert response.status_code == 200
        data = response.get_json()
        assert len(data['results']) > 0
        assert data['results'][0]['title'] == 'Test Book'

def test_book_details_endpoint(client, test_db):
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO books (id, filename, title, author, path, year) VALUES (10, 'path.pdf', 'Specific Book', 'Someone', 'path.pdf', 2020)")
    conn.commit()
    conn.close()

    response = client.get('/api/v1/books/10')
    assert response.status_code == 200
    data = response.get_json()
    assert data['title'] == 'Specific Book'
    assert data['year'] == 2020

def test_book_not_found(client, test_db):
    response = client.get('/api/v1/books/999')
    assert response.status_code == 404
