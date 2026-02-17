import unittest
from unittest.mock import MagicMock, patch
from services.search import SearchService
import numpy as np

class TestSearchService(unittest.TestCase):
    def setUp(self):
        self.search_service = SearchService()
        self.search_service.db = MagicMock()
        self.search_service.ai = MagicMock()

    def test_extract_index_pages(self):
        index_text = "Metric spaces, 12, 14, 15-18\nBanach-Fixed Point Theorem, 101"
        res = self.search_service.extract_index_pages(index_text, "Metric spaces")
        self.assertIn("12", res)
        self.assertIn("15-18", res)

    @patch('services.search.SearchService.get_embedding')
    def test_search_books_semantic(self, mock_emb):
        # Mock DB results
        mock_vec = np.array([0.1]*768, dtype=np.float32).tobytes()
        self.search_service.db.get_connection.return_value.__enter__.return_value.cursor.return_value.fetchall.side_effect = [
            [{'id': 1, 'embedding': mock_vec}, {'id': 2, 'embedding': mock_vec}], # First fetch
            [{'id': 1, 'title': 'Book 1', 'author': 'Author 1', 'path': 'p1', 'isbn': 'i1', 'publisher': 'pub1', 'year': 2020, 'summary': 's1', 'index_text': 'idx1'},
             {'id': 2, 'title': 'Book 2', 'author': 'Author 2', 'path': 'p2', 'isbn': 'i2', 'publisher': 'pub2', 'year': 2021, 'summary': 's2', 'index_text': 'idx2'}] # Second fetch
        ]
        
        query_vec = [0.1]*768
        results = self.search_service.search_books_semantic(query_vec)
        
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['title'], 'Book 1')
        self.assertAlmostEqual(results[0]['score'], 1.0, places=5)

    def test_search_books_fts(self):
        # Mock DB results
        self.search_service.db.get_connection.return_value.__enter__.return_value.cursor.return_value.fetchall.return_value = [
            {'id': 1, 'title': 'Found Title', 'author': 'Author', 'path': 'path', 'snippet': '<b>match</b>', 'year': 2020, 'publisher': 'pub', 'rank': 0.1, 'summary': 'sum', 'index_text': 'idx'}
        ]
        
        results = self.search_service.search_books_fts("match")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['title'], 'Found Title')

if __name__ == '__main__':
    unittest.main()
