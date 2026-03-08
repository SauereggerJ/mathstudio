
import sys
import os
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.append(str(PROJECT_ROOT))

from services.note import note_service
from core.database import db

def run_backfill(book_id=None, limit=500):
    print(f"Starting LaTeX backfill (limit={limit}, book_id={book_id or 'All'})...")
    
    with db.get_connection() as conn:
        query = "SELECT id, book_id, page_start, name, latex_content FROM knowledge_terms WHERE latex_content LIKE '%(marker: %'"
        params = []
        if book_id:
            query += " AND book_id = ?"
            params.append(book_id)
        query += " LIMIT ?"
        params.append(limit)
        
        rows = conn.execute(query, params).fetchall()
        
    total = len(rows)
    print(f"Found {total} terms with placeholders.")
    
    repaired = 0
    for i, row in enumerate(rows):
        term_id = row['id']
        placeholder = row['latex_content']
        # Extract marker from: "% Term: Name (marker: START_MARKER)"
        import re
        match = re.search(r'\(marker: (.*?)\)', placeholder)
        if not match: continue
        
        start_marker = match.group(1)
        # Attempt repair with improved matching
        new_latex = note_service._extract_snippet_from_cache(row['book_id'], row['page_start'], start_marker)
        
        if new_latex and not new_latex.startswith('% Term:'):
            with db.get_connection() as conn:
                conn.execute("UPDATE knowledge_terms SET latex_content = ? WHERE id = ?", (new_latex, term_id))
            repaired += 1
            if repaired % 10 == 0:
                print(f"Progress: {i+1}/{total} (Repaired: {repaired})")
        
    print(f"Finished! Repaired {repaired} out of {total} terms.")

if __name__ == "__main__":
    book_id = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run_backfill(book_id)
