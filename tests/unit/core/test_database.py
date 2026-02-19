import unittest
import os
import sqlite3
from core.database import DatabaseManager
from core.config import PROJECT_ROOT

class TestDatabaseManager(unittest.TestCase):
    def setUp(self):
        self.test_db = PROJECT_ROOT / "test_refactor.db"
        self.db_mgr = DatabaseManager(str(self.test_db))

    def tearDown(self):
        if self.test_db.exists():
            os.remove(self.test_db)

    def test_initialization(self):
        self.db_mgr.initialize_schema()
        with self.db_mgr.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='books'")
            self.assertIsNotNone(cursor.fetchone())
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='books_fts'")
            self.assertIsNotNone(cursor.fetchone())

    def test_connection_context_manager(self):
        self.db_mgr.initialize_schema()
        with self.db_mgr.get_connection() as conn:
            conn.execute("INSERT INTO books (filename, path) VALUES ('test.pdf', 'test/test.pdf')")
        
        # Verify persistence
        with self.db_mgr.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT filename FROM books WHERE path='test/test.pdf'")
            row = cursor.fetchone()
            self.assertEqual(row['filename'], 'test.pdf')

    def test_rollback_on_error(self):
        self.db_mgr.initialize_schema()
        try:
            with self.db_mgr.get_connection() as conn:
                conn.execute("INSERT INTO books (filename, path) VALUES ('error.pdf', 'error/error.pdf')")
                raise ValueError("Simulated Error")
        except ValueError:
            pass
        
        # Verify it was rolled back
        with self.db_mgr.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM books WHERE path='error/error.pdf'")
            self.assertIsNone(cursor.fetchone())

if __name__ == '__main__':
    unittest.main()
