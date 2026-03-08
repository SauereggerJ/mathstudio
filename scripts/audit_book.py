import sys
import os
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.append(str(PROJECT_ROOT))

from core.database import db

def audit_book(book_id):
    with db.get_connection() as conn:
        book = conn.execute("SELECT title FROM books WHERE id = ?", (book_id,)).fetchone()
        if not book:
            print(f"Error: Book ID {book_id} not found.")
            return

        print("\n" + "="*60)
        print(f" HEALTH REPORT: {book['title']}")
        print("="*60)

        # 1. Page Stats
        total_pages = conn.execute("SELECT page_count FROM books WHERE id = ?", (book_id,)).fetchone()['page_count']
        cached_pages = conn.execute("SELECT count(*) as cnt FROM extracted_pages WHERE book_id = ?", (book_id,)).fetchone()['cnt']
        print(f" PDF Pages: {total_pages}")
        print(f" LaTeX Cached: {cached_pages} ({(cached_pages/total_pages*100):.1f}%)")

        # 2. Term Stats
        total_terms = conn.execute("SELECT count(*) as cnt FROM knowledge_terms WHERE book_id = ?", (book_id,)).fetchone()['cnt']
        placeholders = conn.execute("SELECT count(*) as cnt FROM knowledge_terms WHERE book_id = ? AND latex_content LIKE '%(marker: %'", (book_id,)).fetchone()['cnt']
        print(f" Total Terms Found: {total_terms}")
        print(f" Placeholders (Fixable): {placeholders} ({(placeholders/total_terms*100):.1f}%)")

        # 3. Explicit Hiccups (The new table)
        print("\n RECENT ERRORS (Last 20):")
        print("-" * 60)
        errors = conn.execute("""
            SELECT page_number, error_type, details 
            FROM processing_errors 
            WHERE book_id = ? 
            ORDER BY created_at DESC 
            LIMIT 20
        """, (book_id,)).fetchall()

        if not errors:
            print(" No errors logged in processing_errors table yet.")
        else:
            for err in errors:
                print(f" Page {err['page_number']:3} | {err['error_type']:18} | {err['details'][:50]}...")

        # 4. Actionable Gaps
        print("\n ACTIONABLE RECOMMENDATIONS:")
        if placeholders > 0:
            print(f" -> Run: docker exec mathstudio python3 scripts/deep_recovery.py {book_id}")
        if cached_pages < total_pages:
            print(f" -> Some pages failed conversion. Check app.log for 'Active Repair' results.")
        
        print("="*60 + "\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/audit_book.py <book_id>")
    else:
        audit_book(int(sys.argv[1]))
