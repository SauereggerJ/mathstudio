import sys
import os
import re
from pathlib import Path
import numpy as np

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import db
from core.search_engine import index_book

def sync_to_es(book_id, conn):
    """Utility to push updated DB state to ES."""
    full_book = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if full_book:
        chapters = conn.execute("SELECT title FROM chapters WHERE book_id = ? ORDER BY page ASC", (book_id,)).fetchall()
        toc_text = "\n".join([c['title'] for c in chapters])
        vector = list(np.frombuffer(full_book['embedding'], dtype=np.float32)) if full_book['embedding'] else None
        
        es_doc = {
            "id": full_book['id'],
            "title": full_book['title'],
            "author": full_book['author'],
            "summary": full_book['summary'],
            "description": full_book['description'],
            "msc_class": full_book['msc_class'],
            "tags": full_book['tags'],
            "zbl_id": full_book['zbl_id'],
            "doi": full_book['doi'],
            "isbn": full_book['isbn'],
            "year": full_book['year'],
            "publisher": full_book['publisher'],
            "toc": toc_text,
            "index_text": full_book['index_text'],
            "zb_review": full_book['zb_review'],
            "embedding": vector
        }
        index_book(es_doc)

def run_metadata_cleanup():
    print("--- Starting Metadata Cleanup (Tasks 1, 2, 4) ---")
    
    with db.get_connection() as conn:
        # Task 2: Split "Title - Author" where author is missing
        print("Processing Task 2: Splitting 'Title - Author'...")
        rows = conn.execute("SELECT id, title, author FROM books WHERE (author IS NULL OR author = '' OR author = 'Unknown') AND title LIKE '% - %';").fetchall()
        for r in rows:
            parts = r['title'].split(' - ')
            if len(parts) >= 2:
                new_title = " - ".join(parts[:-1]).strip()
                new_author = parts[-1].strip()
                print(f"  ID {r['id']}: Split '{r['title']}' -> T: '{new_title}', A: '{new_author}'")
                conn.execute("UPDATE books SET title = ?, author = ? WHERE id = ?", (new_title, new_author, r['id']))
                sync_to_es(r['id'], conn)

        # Task 1: Truncate very long titles
        print("Processing Task 1: Truncating long titles...")
        rows = conn.execute("SELECT id, title FROM books WHERE length(title) > 150;").fetchall()
        for r in rows:
            clean_title = r['title'].split('. ')[0].split(': ')[0].strip()
            if len(clean_title) > 150:
                clean_title = clean_title[:147] + "..."
            
            if clean_title != r['title']:
                print(f"  ID {r['id']}: Truncated long title.")
                conn.execute("UPDATE books SET title = ?, description = COALESCE(description, '') || '\nOriginal Title: ' || ? WHERE id = ?", (clean_title, r['title'], r['id']))
                sync_to_es(r['id'], conn)

        # Task 4: Fix Series-only titles
        print("Processing Task 4: Cleaning series titles...")
        rows = conn.execute("SELECT id, title, path FROM books WHERE title LIKE '%Mathematics Series%';").fetchall()
        for r in rows:
            if len(r['title']) < 50:
                filename_title = Path(r['path']).stem
                print(f"  ID {r['id']}: Replaced series title with filename '{filename_title}'")
                conn.execute("UPDATE books SET title = ? WHERE id = ?", (filename_title, r['id']))
                sync_to_es(r['id'], conn)

    print("\n--- Remaining Problematic IDs ---")
    with db.get_connection() as conn:
        long = conn.execute("SELECT id FROM books WHERE length(title) > 150").fetchall()
        if long: print(f"Still Long (>150): {[row['id'] for row in long]}")
        
        no_auth = conn.execute("SELECT id FROM books WHERE author IS NULL OR author = '' OR author = 'Unknown'").fetchall()
        if no_auth: print(f"Still No Author: {[row['id'] for row in no_auth]}")
        
        series = conn.execute("SELECT id FROM books WHERE title LIKE '%Series%' AND length(title) < 40").fetchall()
        if series: print(f"Still Series-only Titles: {[row['id'] for row in series]}")

if __name__ == "__main__":
    run_metadata_cleanup()
