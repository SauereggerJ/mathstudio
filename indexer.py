import os
import sqlite3
import re
import requests
import time
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from pypdf import PdfReader

# Configuration
LIBRARY_ROOT = Path("..").resolve() # Parent directory is the library root
DB_FILE = "library.db"
EXTENSIONS = {'.pdf', '.djvu', '.epub'}
TARGET_INDEX_VERSION = 1

def setup_database(force=False):
    """Creates the necessary tables if they don't exist and handles migrations."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Enable WAL mode for better concurrency
    cursor.execute("PRAGMA journal_mode=WAL;")

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
            doi TEXT
        )
    ''')
    
    # Simple migration strategy for books table
    cursor.execute("PRAGMA table_info(books)")
    columns = [info[1] for info in cursor.fetchall()]
    
    new_cols = {
        'isbn': 'TEXT',
        'publisher': 'TEXT',
        'year': 'INTEGER',
        'description': 'TEXT',
        'last_modified': 'REAL',
        'arxiv_id': 'TEXT',
        'doi': 'TEXT',
        'index_text': 'TEXT',
        'summary': 'TEXT',
        'level': 'TEXT',
        'exercises': 'TEXT',
        'solutions': 'TEXT',
        'reference_url': 'TEXT',
        'msc_code': 'TEXT',
        'tags': 'TEXT',
        'index_version': 'INTEGER',
        'index_version': 'INTEGER',
        'embedding': 'BLOB',
        'file_hash': 'TEXT',
        'toc_json': 'TEXT',
        'msc_class': 'TEXT',
        'audience': 'TEXT',
        'has_exercises': 'BOOLEAN',
        'has_solutions': 'BOOLEAN',
        'page_count': 'INTEGER'
    }
    
    for col, dtype in new_cols.items():
        if col not in columns:
            print(f"Migrating books table: adding {col} column...")
            try:
                cursor.execute(f"ALTER TABLE books ADD COLUMN {col} {dtype}")
            except sqlite3.OperationalError:
                pass 

    # 2. FTS Virtual Table with Advanced Tokenizer
    # We check if we need to recreate/migrate the FTS table
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='books_fts'")
    fts_exists = cursor.fetchone()
    
    needs_fts_migration = False
    if fts_exists:
        cursor.execute("PRAGMA table_info(books_fts)")
        fts_cols = [info[1] for info in cursor.fetchall()]
        if 'index_content' not in fts_cols or force:
            needs_fts_migration = True

    if not fts_exists or needs_fts_migration:
        if needs_fts_migration:
            print("Upgrading FTS index (new tokenizer and columns)...")
            # Create new table
            cursor.execute('''
                CREATE VIRTUAL TABLE IF NOT EXISTS books_fts_new USING fts5(
                    title, 
                    author, 
                    content, 
                    index_content, 
                    content_rowid='id',
                    tokenize='porter unicode61 remove_diacritics 1'
                );
            ''')
            # Copy data if possible
            try:
                print("  Copying existing search data...")
                cursor.execute('''
                    INSERT INTO books_fts_new (rowid, title, author, content)
                    SELECT rowid, title, author, content FROM books_fts
                ''')
                print("  Merging index register data...")
                cursor.execute('''
                    UPDATE books_fts_new 
                    SET index_content = (SELECT index_text FROM books WHERE books.id = books_fts_new.rowid)
                ''')
            except sqlite3.Error as e:
                print(f"  Warning: Could not fully migrate FTS data: {e}")
            
            cursor.execute("DROP TABLE IF EXISTS books_fts")
            cursor.execute("ALTER TABLE books_fts_new RENAME TO books_fts")
        else:
            print("Creating FTS index...")
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


    # 3. Bookmarks table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            page_range TEXT,
            tags TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(book_id) REFERENCES books(id)
        )
    ''')

    conn.commit()
    return conn

def extract_full_text(file_path):
    """
    Extracts full text from a PDF/DjVu file.
    """
    text_content = []
    
    if file_path.suffix.lower() == '.pdf':
        try:
            reader = PdfReader(file_path)
            for i, page in enumerate(reader.pages):
                text = page.extract_text()
                if text:
                    cleaned = " ".join(text.split())
                    text_content.append(f" [[PAGE_{i+1}]] {cleaned}")
        except Exception as e:
            print(f"Error extracting text from {file_path.name}: {e}")
            
    elif file_path.suffix.lower() == '.djvu':
        import shutil
        import subprocess
        if shutil.which('djvutxt'):
            try:
                result = subprocess.run(['djvutxt', str(file_path)], capture_output=True, text=True, check=True)
                pages = result.stdout.split('\f')
                for i, page_text in enumerate(pages):
                    if page_text.strip():
                        cleaned = " ".join(page_text.split())
                        text_content.append(f" [[PAGE_{i+1}]] {cleaned}")
            except Exception as e:
                print(f"Error extracting DJVU text from {file_path.name}: {e}")
    
    return " ".join(text_content)

def extract_first_lines(file_path, num_lines=3):
    """Extracts the first few lines of text from PDF for CrossRef lookup."""
    if file_path.suffix.lower() != '.pdf':
        return None
    try:
        reader = PdfReader(file_path)
        if len(reader.pages) > 0:
            text = reader.pages[0].extract_text()
            if text:
                lines = [l.strip() for l in text.splitlines() if l.strip()]
                return " ".join(lines[:num_lines])
    except Exception:
        pass
    return None

def extract_isbn(file_path):
    """Attempts to extract ISBN from the first few pages of a PDF."""
    if file_path.suffix.lower() != '.pdf':
        return None
    try:
        reader = PdfReader(file_path)
        num_pages = min(len(reader.pages), 5)
        text = ""
        for i in range(num_pages):
            text += reader.pages[i].extract_text() or ""
        isbn_pattern = re.compile(r'ISBN(?:-1[03])?:?\s*([\d\- X]{10,17})', re.IGNORECASE)
        match = isbn_pattern.search(text)
        if match:
            isbn_clean = re.sub(r'[^\dXx]', '', match.group(1))
            if len(isbn_clean) in [10, 13]:
                return isbn_clean
    except Exception:
        pass 
    return None

def get_arxiv_id_from_filename(filename):
    match_new = re.search(r'(\d{4}\.\d{4,5})', filename)
    if match_new: return match_new.group(1)
    match_old = re.search(r'([a-zA-Z\-]+\/\d{7})', filename)
    if match_old: return match_old.group(1)
    return None

def fetch_arxiv_metadata(arxiv_id):
    url = f'http://export.arxiv.org/api/query?id_list={arxiv_id}'
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            ns = {'atom': 'http://www.w3.org/2005/Atom', 'arxiv': 'http://arxiv.org/schemas/atom'}
            entry = root.find('atom:entry', ns)
            if entry:
                meta = {}
                meta['title'] = entry.find('atom:title', ns).text.strip().replace('\n', ' ')
                authors = [a.find('atom:name', ns).text for a in entry.findall('atom:author', ns)]
                meta['author'] = ", ".join(authors)
                published = entry.find('atom:published', ns).text
                if published: meta['year'] = int(published[:4])
                meta['publisher'] = "ArXiv"
                summary = entry.find('atom:summary', ns)
                meta['description'] = summary.text.strip() if summary is not None else ""
                meta['arxiv_id'] = arxiv_id
                return meta
    except Exception as e:
        print(f"ArXiv API Error: {e}")
    return None

def fetch_open_library_metadata(isbn):
    if not isbn: return None
    url = f"https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&jscmd=data&format=json"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            key = f"ISBN:{isbn}"
            if key in data:
                book_data = data[key]
                meta = {}
                meta['title'] = book_data.get('title')
                authors = book_data.get('authors', [])
                meta['author'] = ", ".join([a['name'] for a in authors]) if authors else None
                publishers = book_data.get('publishers', [])
                meta['publisher'] = publishers[0]['name'] if publishers else None
                year_text = book_data.get('publish_date')
                if year_text:
                    year_match = re.search(r'\d{4}', year_text)
                    if year_match: meta['year'] = int(year_match.group(0))
                meta['isbn'] = isbn
                return meta
    except Exception: pass
    return None

def fetch_crossref_metadata(query_text):
    if not query_text or len(query_text) < 10: return None
    url = "https://api.crossref.org/works"
    params = {'query.bibliographic': query_text, 'rows': 1}
    try:
        response = requests.get(url, params=params, timeout=5)
        if response.status_code == 200:
            items = response.json().get('message', {}).get('items', [])
            if items:
                item = items[0]
                meta = {'title': item.get('title', [''])[0]}
                authors = item.get('author', [])
                auth_names = [f"{a.get('given', '')} {a['family']}" for a in authors if 'family' in a]
                meta['author'] = ", ".join(auth_names) if auth_names else None
                meta['publisher'] = item.get('publisher')
                date_parts = item.get('created', {}).get('date-parts', [[None]])
                if date_parts and date_parts[0] and date_parts[0][0]:
                     meta['year'] = date_parts[0][0]
                meta['doi'] = item.get('DOI')
                return meta
    except Exception: pass
    return None

def parse_filename(filename):
    stem = Path(filename).stem
    parts = stem.split(' - ')
    if len(parts) >= 2:
        return parts[0].strip(), " - ".join(parts[1:]).strip()
    return stem, None

def resolve_metadata(filename, file_path):
    arxiv_id = get_arxiv_id_from_filename(filename)
    if arxiv_id:
        meta = fetch_arxiv_metadata(arxiv_id)
        if meta: return meta
    isbn = extract_isbn(file_path)
    if isbn:
        meta = fetch_open_library_metadata(isbn)
        if meta: return meta
    title, author = parse_filename(filename)
    if not author:
        head_text = extract_first_lines(file_path)
        if head_text:
            meta = fetch_crossref_metadata(head_text)
            if meta: return meta
    return {'title': title, 'author': author}

def scan_library(conn, force=False):
    """Scans the library directory and updates the database."""
    cursor = conn.cursor()
    count_new = 0
    count_updated = 0
    
    print(f"Scanning library in: {LIBRARY_ROOT.resolve()}")
    
    for root, dirs, files in os.walk(LIBRARY_ROOT):
        if "mathstudio" in root: continue
            
        for file in files:
            file_path = Path(root) / file
            if file_path.suffix.lower() in EXTENSIONS:
                try:
                    rel_path = str(file_path.relative_to(LIBRARY_ROOT))
                    mtime = file_path.stat().st_mtime
                    size = file_path.stat().st_size
                    
                    cursor.execute("SELECT id, last_modified, index_version, index_text FROM books WHERE path = ?", (rel_path,))
                    existing = cursor.fetchone()
                    
                    if not existing:
                        print(f"Processing new file: {file}")
                        meta = resolve_metadata(file, file_path)
                        
                        cursor.execute('''
                            INSERT INTO books (filename, path, directory, author, title, size_bytes, isbn, publisher, year, description, last_modified, arxiv_id, doi, index_version)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (file, rel_path, str(Path(root).relative_to(LIBRARY_ROOT)), meta.get('author'), meta.get('title', file), size, meta.get('isbn'), meta.get('publisher'), meta.get('year'), meta.get('description'), mtime, meta.get('arxiv_id'), meta.get('doi'), TARGET_INDEX_VERSION))
                        
                        book_id = cursor.lastrowid
                        full_text = extract_full_text(file_path)
                        cursor.execute('INSERT INTO books_fts (rowid, title, author, content, index_content) VALUES (?, ?, ?, ?, ?)', 
                                       (book_id, meta.get('title'), meta.get('author'), full_text, None))
                        count_new += 1
                    else:
                        book_id, db_mtime, db_version, db_index_text = existing
                        needs_update = force or (db_mtime is None or abs(mtime - db_mtime) > 1.0)
                        if not needs_update and (db_version is None or db_version < TARGET_INDEX_VERSION):
                             needs_update = True

                        if needs_update:
                             print(f"Updating indexed file: {file}")
                             meta = resolve_metadata(file, file_path)
                             cursor.execute('''
                                UPDATE books 
                                SET size_bytes=?, isbn=?, publisher=?, year=?, description=?, last_modified=?, title=?, author=?, arxiv_id=?, doi=?, index_version=?
                                WHERE id=?
                            ''', (size, meta.get('isbn'), meta.get('publisher'), meta.get('year'), meta.get('description'), mtime, meta.get('title', file), meta.get('author'), meta.get('arxiv_id'), meta.get('doi'), TARGET_INDEX_VERSION, book_id))
                             
                             # Reuse text from FTS if not forcing re-extraction
                             full_text = None
                             if not force:
                                 cursor.execute("SELECT content FROM books_fts WHERE rowid = ?", (book_id,))
                                 row = cursor.fetchone()
                                 if row: full_text = row[0]
                             
                             if not full_text:
                                 print(f"  Extracting text...")
                                 full_text = extract_full_text(file_path)
                             
                             cursor.execute("DELETE FROM books_fts WHERE rowid = ?", (book_id,))
                             cursor.execute('INSERT INTO books_fts (rowid, title, author, content, index_content) VALUES (?, ?, ?, ?, ?)', 
                                            (book_id, meta.get('title'), meta.get('author'), full_text, db_index_text))
                             count_updated += 1

                except Exception as e:
                    print(f"Error processing {file}: {e}")


    # 3. Bookmarks table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            page_range TEXT,
            tags TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(book_id) REFERENCES books(id)
        )
    ''')

    conn.commit()
    print(f"Scan complete. New: {count_new}, Updated: {count_updated}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Force re-indexing and FTS rebuild")
    args = parser.parse_args()
    
    start_time = time.time()
    conn = setup_database(force=args.force)
    scan_library(conn, force=args.force)
    conn.close()
    print(f"Total time: {time.time() - start_time:.2f}s")