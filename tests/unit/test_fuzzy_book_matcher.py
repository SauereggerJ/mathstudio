import pytest
import sqlite3
from services.fuzzy_matcher import FuzzyBookMatcher

@pytest.fixture
def matcher(test_db):
    # Setup data in test_db
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO books (id, filename, title, author, path) VALUES (1, 'billingsley.pdf', 'Probability and Measure', 'P. Billingsley', 'path1.pdf')")
    cursor.execute("INSERT INTO books (id, filename, title, author, path) VALUES (2, 'folland.pdf', 'Real Analysis: Modern Techniques and Their Applications', 'Gerald B. Folland', 'path2.pdf')")
    cursor.execute("INSERT INTO books (id, filename, title, author, path) VALUES (3, 'hatcher.pdf', 'Algebraic Topology', 'Allen Hatcher', 'path3.pdf')")
    conn.commit()
    conn.close()
    
    return FuzzyBookMatcher(test_db, threshold=0.7)

def test_normalize_text(matcher):
    assert matcher.normalize_text("Real Analysis (2nd ed.)") == "real analysis"
    assert matcher.normalize_text("Algebraic-Topology") == "algebraic topology"

def test_match_exact(matcher):
    result = matcher.match_book("Probability and Measure", "P. Billingsley")
    assert result['found'] is True
    assert result['strategy'] == 'exact'
    assert result['match']['id'] == 1

def test_match_normalized(matcher):
    # Missing dot in P.
    result = matcher.match_book("Probability and Measure", "P Billingsley")
    assert result['found'] is True
    assert result['strategy'] == 'normalized'

def test_match_fuzzy(matcher):
    # Slight typo
    result = matcher.match_book("Algebrac Topology", "Allen Hatcher")
    assert result['found'] is True
    assert result['strategy'] == 'fuzzy'

def test_match_token_based(matcher):
    # Search for "Real Techniques" - should match Folland via tokens
    result = matcher.match_book("Real Techniques", "Folland")
    assert result['found'] is True
    assert result['strategy'] == 'token'

def test_batch_match(matcher):
    books = [
        {'title': 'Probability and Measure', 'author': 'Billingsley'},
        {'title': 'Non-existent Book', 'author': 'Nobody'}
    ]
    results = matcher.batch_match(books)
    assert len(results) == 2
    assert results[0]['found'] is True
    assert results[1]['found'] is False
