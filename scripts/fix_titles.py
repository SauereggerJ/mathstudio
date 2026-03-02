import sys
import os
from pathlib import Path
import numpy as np

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import db
from core.search_engine import index_book

def fix_none_titles():
    print("--- Fixing None Titles ---")
    
    with db.get_connection() as conn:
        books = conn.execute("SELECT id, path FROM books WHERE title IS NULL OR title = '';").fetchall()
        
        if not books:
            print("No books found with None titles.")
            return

        for row in books:
            book_id = row['id']
            path = row['path']
            
            # Extract filename without extension as the new title
            new_title = Path(path).stem
            print(f"Fixing ID {book_id}: Setting title to '{new_title}'")
            
            # 1. Update SQLite
            conn.execute("UPDATE books SET title = ? WHERE id = ?", (new_title, book_id))
            
            # 2. Sync to Elasticsearch
            try:
                # Fetch full state for ES indexing
                full_book = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
                if full_book:
                    # Fetch TOC text
                    chapters = conn.execute("SELECT title FROM chapters WHERE book_id = ? ORDER BY page ASC", (book_id,)).fetchall()
                    toc_text = "\n".join([c['title'] for c in chapters])
                    
                    vector = None
                    if full_book['embedding']:
                        vector = list(np.frombuffer(full_book['embedding'], dtype=np.float32))

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
                    print(f"  [OK] Synced to Elasticsearch.")
            except Exception as e:
                print(f"  [ERROR] Failed to sync to ES: {e}")

    print("--- Fix Complete ---")

if __name__ == "__main__":
    fix_none_titles()
