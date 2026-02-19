import unittest
import os
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock
from services.note import NoteService
from core.database import DatabaseManager
from core.config import PROJECT_ROOT

class TestNoteCache(unittest.TestCase):
    def setUp(self):
        self.test_db = PROJECT_ROOT / "test_notes.db"
        self.db_mgr = DatabaseManager(str(self.test_db))
        self.db_mgr.initialize_schema()
        
        self.note_service = NoteService()
        self.note_service.db = self.db_mgr
        
        # Setup dummy book
        with self.db_mgr.get_connection() as conn:
            conn.execute("INSERT INTO books (id, filename, title, author, path) VALUES (1, 'test.pdf', 'Test Book', 'Author', 'test.pdf')")

    def tearDown(self):
        if self.test_db.exists():
            os.remove(self.test_db)
        # Cleanup test notes dir
        test_note_dir = PROJECT_ROOT / "converted_notes" / "1"
        if test_note_dir.exists():
            import shutil
            shutil.rmtree(test_note_dir)

    def test_save_and_get_cache(self):
        latex = "\section{Test}"
        markdown = "# Test"
        self.note_service.save_page_to_cache(1, 10, latex, markdown)
        
        # Verify DB entry
        with self.db_mgr.get_connection() as conn:
            row = conn.execute("SELECT * FROM extracted_pages WHERE book_id=1 AND page_number=10").fetchone()
            self.assertIsNotNone(row)
            self.assertIn("1/page_10.tex", row['latex_path'])
            
        # Verify file exists
        self.assertTrue(Path(row['latex_path']).exists())
        
        # Test retrieval
        cached = self.note_service.get_cached_page(1, 10)
        self.assertEqual(cached['latex'], latex)
        self.assertEqual(cached['markdown'], markdown)

if __name__ == '__main__':
    unittest.main()
