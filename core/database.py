import sqlite3
import threading
from contextlib import contextmanager
from . import config

# Thread-local storage for database connections
_local = threading.local()

class DatabaseManager:
    def __init__(self, db_path=None):
        self._db_path = db_path

    @property
    def db_path(self):
        return self._db_path or config.DB_FILE

    @contextmanager
    def get_connection(self):
        """Provides a context-managed database connection with WAL mode enabled."""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row # Return rows as dictionaries
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize_schema(self, force_fts_rebuild=False):
        """Consolidated schema initialization and migration logic."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. Main books table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS books (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    path TEXT NOT NULL UNIQUE,
                    directory TEXT,
                    author TEXT,
                    title TEXT,
                    size_bytes INTEGER,
                    isbn TEXT,
                    publisher TEXT,
                    year INTEGER,
                    description TEXT,
                    last_modified REAL,
                    arxiv_id TEXT,
                    doi TEXT,
                    index_text TEXT,
                    summary TEXT,
                    level TEXT,
                    audience TEXT,
                    has_exercises BOOLEAN,
                    has_solutions BOOLEAN,
                    page_count INTEGER,
                    toc_json TEXT,
                    msc_class TEXT,
                    msc_code TEXT,
                    tags TEXT,
                    embedding BLOB,
                    file_hash TEXT,
                    index_version INTEGER,
                    reference_url TEXT
                )
            ''')

            # 2. FTS Virtual Table
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='books_fts'")
            if not cursor.fetchone() or force_fts_rebuild:
                cursor.execute("DROP TABLE IF EXISTS books_fts")
                cursor.execute('''
                    CREATE VIRTUAL TABLE books_fts USING fts5(
                        title, 
                        author, 
                        content, 
                        index_content, 
                        content_rowid='id',
                        tokenize='porter unicode61 remove_diacritics 1'
                    );
                ''')

            # 3. Chapters Table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chapters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    level INTEGER DEFAULT 0,
                    page INTEGER,
                    FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
                )
            ''')

            # 4. Bookmarks table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bookmarks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_id INTEGER NOT NULL,
                    page_range TEXT,
                    tags TEXT,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
                )
            ''')

            # 5. Page-level FTS and Deep Index Tracking
            cursor.execute('''
                CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
                    book_id UNINDEXED,
                    page_number UNINDEXED,
                    content,
                    tokenize='porter unicode61 remove_diacritics 1'
                );
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS deep_indexed_books (
                    book_id INTEGER PRIMARY KEY,
                    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
                );
            ''')

# Global instance
db = DatabaseManager()
