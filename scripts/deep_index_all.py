import sys
import os
import time

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import db
from services.indexer import indexer_service

def deep_index_all():
    print("--- Starting Library-Wide Deep Indexing (v2) ---")
    
    with db.get_connection() as conn:
        # Find books that are NOT in the deep_indexed_books table
        books = conn.execute("""
            SELECT id, title FROM books 
            WHERE id NOT IN (SELECT book_id FROM deep_indexed_books)
            ORDER BY id ASC
        """).fetchall()
    
    total = len(books)
    print(f"Found {total} books to deep-index.")
    
    success_count = 0
    fail_count = 0
    
    for i, book in enumerate(books):
        book_id = book['id']
        # Handle None title gracefully
        raw_title = book['title'] or "Untitled Book"
        title = raw_title[:50]
        
        print(f"[{i+1}/{total}] Indexing ID {book_id}: {title}...")
        sys.stdout.flush()
        
        try:
            success, message = indexer_service.deep_index_book(book_id)
            if success:
                success_count += 1
            else:
                fail_count += 1
                print(f"  [FAIL] {message}")
        except Exception as e:
            fail_count += 1
            print(f"  [ERROR] {str(e)}")
            
        if (i + 1) % 10 == 0:
            time.sleep(0.1)

    print("\n--- Deep Indexing Complete ---")
    print(f"Successful: {success_count}")
    print(f"Failed:     {fail_count}")

if __name__ == "__main__":
    deep_index_all()
