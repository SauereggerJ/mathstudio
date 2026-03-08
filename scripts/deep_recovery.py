
import sys
import os
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.append(str(PROJECT_ROOT))

from services.recovery import recovery_service
from core.database import db

def run_deep_recovery(book_id=None, limit=500):
    print(f"Starting DEEP LaTeX recovery (limit={limit}, book_id={book_id or 'All'})...")
    
    with db.get_connection() as conn:
        query = "SELECT id FROM knowledge_terms WHERE latex_content LIKE '%(marker: %'"
        params = []
        if book_id:
            query += " AND book_id = ?"
            params.append(book_id)
        query += " LIMIT ?"
        params.append(limit)
        
        rows = conn.execute(query, params).fetchall()
        
    total = len(rows)
    print(f"Found {total} terms with placeholders.")
    
    recovered = 0
    for i, row in enumerate(rows):
        term_id = row['id']
        if recovery_service.recover_term(term_id):
            recovered += 1
            if recovered % 10 == 0:
                print(f"Progress: {i+1}/{total} (Recovered: {recovered})")
        
    print(f"Finished! Deeply recovered {recovered} out of {total} terms.")

if __name__ == "__main__":
    b_id = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run_deep_recovery(b_id)
