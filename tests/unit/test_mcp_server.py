import unittest
from unittest.mock import patch, MagicMock
import asyncio
import json
from mcp_server.server import search_books, get_book_details

class TestMCPServer(unittest.IsolatedAsyncioTestCase):
    @patch('mcp_server.server.requests.get')
    async def test_search_books_tool(self, mock_get):
        # Mock API response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"id": 1, "title": "Test Book", "author": "Author", "score": 0.9}
            ],
            "total_count": 1
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        
        args = {"query": "test"}
        result = await search_books(args)
        
        self.assertIn("Test Book", result[0].text)
        self.assertIn("Found 1 results", result[0].text)

    @patch('mcp_server.server.requests.get')
    async def test_get_book_details_tool(self, mock_get):
        # Mock API response for book details
        mock_details = MagicMock()
        mock_details.json.return_value = {
            "id": 1, "title": "Detailed Book", "author": "Expert", 
            "page_count": 300, "has_index": True, "page_offset": 10
        }
        mock_details.ok = True
        
        # Mock API response for TOC
        mock_toc = MagicMock()
        mock_toc.ok = True
        mock_toc.json.return_value = {"toc": []}
        
        mock_get.side_effect = [mock_details, mock_toc]
        
        args = {"book_id": 1}
        result = await get_book_details(args)
        
        self.assertIn("Detailed Book", result[0].text)
        self.assertIn("Back-of-Book Index ✓", result[0].text)

if __name__ == '__main__':
    unittest.main()
