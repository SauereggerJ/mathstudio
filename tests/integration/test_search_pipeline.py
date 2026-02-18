import pytest
import sqlite3
import numpy as np
from pathlib import Path
from unittest.mock import patch
from services.search import search_service

def test_full_search_flow(test_db, mock_gemini):
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO books (id, filename, title, author, path, directory, embedding, index_text)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (1, "topology.pdf", "Topology for Beginners", "John Doe", "topology.pdf", "03_Geometry", 
          np.array([0.1] * 768, dtype=np.float32).tobytes(),
          "Compactness 10, 20"))
    cursor.execute('''
        INSERT INTO books_fts (rowid, title, author, content, index_content)
        VALUES (?, ?, ?, ?, ?)
    ''', (1, "Topology for Beginners", "John Doe", "This is a book about topology.", "Compactness 10, 20"))
    conn.commit()
    conn.close()

    with patch("core.config.DB_FILE", Path(test_db)):
        results = search_service.search("topology", use_vector=True, use_fts=True)
        assert results['total_count'] > 0
        best_match = results['results'][0]
        assert "Topology" in best_match['title']

def test_search_index_boost(test_db, mock_gemini):
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO books (id, filename, title, author, path, index_text) VALUES (?, ?, ?, ?, ?, ?)",
                   (2, "analysis.pdf", "Real Analysis", "Jane Smith", "analysis.pdf", "Measure theory 100"))
    cursor.execute("INSERT INTO books_fts (rowid, title, author, content, index_content) VALUES (?, ?, ?, ?, ?)",
                   (2, "Real Analysis", "Jane Smith", "Analysis content", "Measure theory 100"))
    conn.commit()
    conn.close()

    with patch("core.config.DB_FILE", Path(test_db)):
        results = search_service.search("Measure theory")
        assert results['total_count'] > 0
        assert results['results'][0]['index_matches'] == "100"
