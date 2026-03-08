import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import db
from services.pipeline import pipeline_service
from services.knowledge import knowledge_service

def fix_corrupted_terms():
    with db.get_connection() as conn:
        bad_terms = conn.execute("SELECT id, book_id, page_start FROM knowledge_terms WHERE latex_content LIKE '%### %'").fetchall()

    if not bad_terms:
        print("No corrupted terms found.")
        return

    pages_by_book = {}
    for term in bad_terms:
        b = term['book_id']
        p = term['page_start']
        if b not in pages_by_book:
            pages_by_book[b] = set()
        pages_by_book[b].add(p)
        
        print(f"Deleting corrupted term {term['id']} from page {p} of book {b}...")
        knowledge_service.delete_term(term['id'])

    print(f"\nDeleted {len(bad_terms)} bad terms.")

    for b, pages in pages_by_book.items():
        pages_list = sorted(list(pages))
        print(f"\nRe-running Pass 2 for book {b} on {len(pages_list)} affected pages...")
        stats = pipeline_service.run_pass_2(b, pages=pages_list)
        print(f"Finished Pass 2 for book {b}: {stats}")

if __name__ == "__main__":
    fix_corrupted_terms()
