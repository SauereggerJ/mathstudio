import os
import sys
import sqlite3
import difflib
import re
from collections import defaultdict
import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import db
from services.knowledge import knowledge_service

def run_corrections():
    with db.get_connection() as conn:
        conn.row_factory = sqlite3.Row
        terms = conn.execute("SELECT id, book_id, page_start, name, term_type, latex_content FROM knowledge_terms ORDER BY book_id, page_start").fetchall()
        
    print(f"Loaded {len(terms)} terms.")
    
    # 1. Strip [LaTeX Body] and [LaTeX body]
    cleaned = 0
    for term in terms:
        content = term['latex_content'] or ""
        new_content = content
        
        # Various forms of the leak
        patterns = [
            r'\[\s*latex\s*body\s*\]',
            r'\[\s*latex\s*body\s*:\s*\]',
            r'latex\s*body\s*:',
            r'\[\s*latex\s*body\s*'
        ]
        
        for p in patterns:
            new_content = re.sub(p, '', new_content, flags=re.IGNORECASE)
            
        new_content = new_content.strip()
        
        if new_content != content:
            with db.get_connection() as conn:
                conn.execute("UPDATE knowledge_terms SET latex_content = ? WHERE id = ?", (new_content, term['id']))
            # Fast Sync to Elasticsearch (bypassing slow MWS LateXML generator)
            try:
                from core.search_engine import es_client
                es_client.update(index="mathstudio_terms", id=term['id'], body={"doc": {"latex_content": new_content}})
                cleaned += 1
            except Exception as e:
                pass
                #print(f"Error syncing {term['id']}: {e}")

    print(f"Cleaned formatting leaks from {cleaned} terms.")

    # 2. Delete Semantic Duplicates
    # Re-fetch terms after cleaning
    with db.get_connection() as conn:
        conn.row_factory = sqlite3.Row
        terms = conn.execute("SELECT id, book_id, page_start, name, term_type, latex_content FROM knowledge_terms ORDER BY book_id, page_start, id").fetchall()
        
    books = defaultdict(list)
    for term in terms:
        books[term['book_id']].append(term)
        
    deleted_count = 0
    deleted_ids = set()
    
    for book_id, book_terms in books.items():
        for i in range(len(book_terms)):
            t1 = book_terms[i]
            if t1['id'] in deleted_ids: continue
            
            for j in range(i + 1, len(book_terms)):
                t2 = book_terms[j]
                if t2['id'] in deleted_ids: continue
                
                # Check within 5 pages
                if abs(t2['page_start'] - t1['page_start']) <= 5:
                    c1 = t1['latex_content'] or ""
                    c2 = t2['latex_content'] or ""
                    if not c1 or not c2: continue
                    if abs(len(c1) - len(c2)) / max(len(c1), len(c2)) > 0.3: continue
                        
                    sim = difflib.SequenceMatcher(None, c1, c2).ratio()
                    if sim > 0.85:
                        print(f"Deleting duplicate term {t2['id']} ('{t2['name']}') which is {sim*100:.1f}% similar to {t1['id']} ('{t1['name']}').")
                        try:
                            # Delete from SQLite
                            with db.get_connection() as conn:
                                conn.execute("DELETE FROM knowledge_terms WHERE id = ?", (t2['id'],))
                            # Delete from Elasticsearch
                            from core.search_engine import es_client
                            try:
                                es_client.delete(index="mathstudio_terms", id=t2['id'])
                            except Exception:
                                pass
                            # Mark as deleted so we skip future comparisons
                            deleted_ids.add(t2['id'])
                            deleted_count += 1
                        except Exception as e:
                            print(f"Failed deleting {t2['id']}: {e}")

    print(f"Deleted {deleted_count} semantic duplicate terms.")

if __name__ == "__main__":
    run_corrections()
