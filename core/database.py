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
                    zbl_id TEXT,
                    index_text TEXT,
                    summary TEXT,
                    level TEXT,
                    audience TEXT,
                    has_exercises INTEGER, -- 0 or 1
                    has_solutions INTEGER, -- 0 or 1
                    page_count INTEGER,
                    toc_json TEXT,
                    msc_class TEXT,
                    tags TEXT,
                    embedding BLOB,
                    file_hash TEXT,
                    index_version INTEGER,
                    reference_url TEXT,
                    last_metadata_refresh INTEGER DEFAULT 0,
                    page_offset INTEGER DEFAULT 0,
                    metadata_status TEXT DEFAULT 'raw', -- raw, verified, conflict
                    trust_score REAL DEFAULT 0.0
                ) STRICT
            ''')

            # 1.1 Simple Migration Loop for missing columns in 'books'
            for col, col_type in [
                ("last_metadata_refresh", "INTEGER DEFAULT 0"), 
                ("page_offset", "INTEGER DEFAULT 0"),
                ("zbl_id", "TEXT"),
                ("metadata_status", "TEXT DEFAULT 'raw'"),
                ("trust_score", "REAL DEFAULT 0.0")
            ]:
                try:
                    conn.execute(f"ALTER TABLE books ADD COLUMN {col} {col_type}")
                except sqlite3.OperationalError:
                    pass # Already exists

            # 1.2 Data Migration: Transfer zbMATH IDs from arxiv_id to zbl_id
            try:
                # If zbl_id is null, try to take from arxiv_id if it looks like a Zbl ID
                conn.execute("UPDATE books SET zbl_id = arxiv_id WHERE zbl_id IS NULL AND (arxiv_id LIKE 'Zbl%' OR arxiv_id LIKE '%:%')")
            except: pass

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
                    msc_code TEXT,
                    topics TEXT,
                    FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
                ) STRICT
            ''')

            # 3.1 Migration for chapters
            for col in ["msc_code", "topics"]:
                try:
                    conn.execute(f"ALTER TABLE chapters ADD COLUMN {col} TEXT")
                except sqlite3.OperationalError:
                    pass

            # 4. Bookmarks table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bookmarks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_id INTEGER NOT NULL,
                    page_range TEXT,
                    tags TEXT,
                    notes TEXT,
                    created_at INTEGER DEFAULT (unixepoch()),
                    FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
                ) STRICT
            ''')

            # 5. Page-level FTS and Deep Index Tracking
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pages_fts'")
            if not cursor.fetchone():
                cursor.execute('''
                    CREATE VIRTUAL TABLE pages_fts USING fts5(
                        book_id UNINDEXED,
                        page_number UNINDEXED,
                        content,
                        tokenize='porter unicode61 remove_diacritics 1'
                    );
                ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS deep_indexed_books (
                    book_id INTEGER PRIMARY KEY,
                    indexed_at INTEGER DEFAULT (unixepoch()),
                    FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
                ) STRICT;
            ''')

            # 6. Extracted Pages (LaTeX/Markdown Cache)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS extracted_pages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_id INTEGER NOT NULL,
                    page_number INTEGER NOT NULL,
                    latex_path TEXT,
                    markdown_path TEXT,
                    created_at INTEGER DEFAULT (unixepoch()),
                    UNIQUE(book_id, page_number),
                    FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
                ) STRICT
            ''')

            # 7. zbMATH Cache (The Lazy Mirror) - Using SQLite STRICT and JSONB
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS zbmath_cache (
                    zbl_id TEXT PRIMARY KEY,
                    msc_code TEXT,
                    authors TEXT, 
                    title TEXT,
                    keywords TEXT,
                    links TEXT,
                    bibtex TEXT,
                    review_markdown TEXT,
                    fetched_at INTEGER DEFAULT (unixepoch()), -- Using unixepoch for STRICT
                    needs_refresh INTEGER DEFAULT 0
                ) STRICT
            ''')

            # 8. Raw Bibliography Entries (Extracted from PDFs)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bib_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_id INTEGER NOT NULL,
                    raw_text TEXT NOT NULL,
                    title TEXT,
                    author TEXT,
                    extracted_at INTEGER DEFAULT (unixepoch()),
                    resolved_zbl_id TEXT,
                    confidence REAL,
                    FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE,
                    FOREIGN KEY(resolved_zbl_id) REFERENCES zbmath_cache(zbl_id)
                ) STRICT
            ''')

            # 8.1 Migration for bib_entries
            for col in ["title", "author"]:
                try:
                    conn.execute(f"ALTER TABLE bib_entries ADD COLUMN {col} TEXT")
                except sqlite3.OperationalError:
                    pass

            # 9. Literature Graph
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS book_citations (
                    book_id INTEGER NOT NULL,
                    zbl_id TEXT NOT NULL,
                    PRIMARY KEY(book_id, zbl_id),
                    FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE,
                    FOREIGN KEY(zbl_id) REFERENCES zbmath_cache(zbl_id)
                ) STRICT
            ''')

            # 10. Metadata Proposals
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS metadata_proposals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_id INTEGER NOT NULL,
                    field_name TEXT NOT NULL,
                    proposed_value TEXT NOT NULL,
                    source TEXT,
                    confidence REAL,
                    proposed_at INTEGER DEFAULT (unixepoch()),
                    FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
                ) STRICT
            ''')

            # 11. Wishlist
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS wishlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    author TEXT,
                    doi TEXT UNIQUE,
                    zbl_id TEXT,
                    source_book_id INTEGER,
                    status TEXT DEFAULT 'pending', -- pending, acquired, rejected
                    created_at INTEGER DEFAULT (unixepoch()),
                    FOREIGN KEY(source_book_id) REFERENCES books(id) ON DELETE SET NULL
                ) STRICT
            ''')

            # 12. Knowledge Base: Concepts
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS concepts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    aliases TEXT,
                    domain TEXT,
                    kind TEXT NOT NULL,
                    canonical_entry_id INTEGER,
                    obsidian_path TEXT,
                    created_at INTEGER DEFAULT (unixepoch()),
                    updated_at INTEGER DEFAULT (unixepoch()),
                    FOREIGN KEY(canonical_entry_id) REFERENCES entries(id) ON DELETE SET NULL
                ) STRICT
            ''')

            # 13. Knowledge Base: Entries (specific formulations)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    concept_id INTEGER NOT NULL,
                    book_id INTEGER,
                    page_start INTEGER,
                    page_end INTEGER,
                    statement TEXT NOT NULL,
                    proof TEXT,
                    notes TEXT,
                    scope TEXT,
                    language TEXT DEFAULT 'en',
                    style TEXT,
                    is_canonical INTEGER DEFAULT 0,
                    confidence REAL DEFAULT 1.0,
                    extracted_by TEXT DEFAULT 'llm',
                    embedding BLOB,
                    created_at INTEGER DEFAULT (unixepoch()),
                    FOREIGN KEY(concept_id) REFERENCES concepts(id) ON DELETE CASCADE,
                    FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE SET NULL
                ) STRICT
            ''')

            # 14. Knowledge Base: Relations (graph edges)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS relations (
                    from_concept_id INTEGER NOT NULL,
                    to_concept_id INTEGER NOT NULL,
                    relation_type TEXT NOT NULL,
                    context TEXT,
                    source_entry_id INTEGER,
                    confidence REAL DEFAULT 1.0,
                    created_at INTEGER DEFAULT (unixepoch()),
                    PRIMARY KEY(from_concept_id, to_concept_id, relation_type),
                    FOREIGN KEY(from_concept_id) REFERENCES concepts(id) ON DELETE CASCADE,
                    FOREIGN KEY(to_concept_id) REFERENCES concepts(id) ON DELETE CASCADE,
                    FOREIGN KEY(source_entry_id) REFERENCES entries(id) ON DELETE SET NULL
                ) STRICT
            ''')

            # 15. Knowledge Base: FTS over concepts + entries
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='concept_fts'")
            if not cursor.fetchone():
                cursor.execute('''
                    CREATE VIRTUAL TABLE concept_fts USING fts5(
                        name, aliases, statement, notes,
                        tokenize='porter unicode61 remove_diacritics 1'
                    );
                ''')

            # 16. LLM Task Queue
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS llm_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_type TEXT NOT NULL,
                    payload TEXT,
                    status TEXT DEFAULT 'pending',
                    priority INTEGER DEFAULT 5,
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    error_log TEXT,
                    result TEXT,
                    created_at INTEGER DEFAULT (unixepoch()),
                    completed_at INTEGER
                ) STRICT
            ''')

# Global instance
db = DatabaseManager()
