
import sys
import os
from pathlib import Path
import json

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.append(str(PROJECT_ROOT))

from services.knowledge import knowledge_service
from core.database import db
from core.search_engine import es_client

def resync_all_terms(start_id=None, force=False):
    """Fetches all approved terms from SQLite and syncs them to ES/MWS."""
    print(f"Starting re-sync of knowledge terms (force={force})...")
    
    with db.get_connection() as conn:
        query = "SELECT * FROM knowledge_terms WHERE status = 'approved'"
        params = []
        if start_id:
            query += " AND id >= ?"
            params.append(start_id)
        terms = conn.execute(query, params).fetchall()
        
    total = len(terms)
    print(f"Found {total} approved terms in SQLite to process.")
    
    success_count = 0
    skipped_count = 0
    for i, row in enumerate(terms):
        term_id = row['id']
        
        # Check if already in ES and if content matches
        if not force:
            try:
                res = es_client.get(index="mathstudio_terms", id=str(term_id))
                if res['found']:
                    es_latex = res['_source'].get('latex_content', '')
                    db_latex = row['latex_content'] or ''
                    if es_latex == db_latex:
                        skipped_count += 1
                        if (i + 1) % 100 == 0:
                            print(f"Progress: {i+1}/{total} (Skipped: {skipped_count}, Success: {success_count})")
                        continue
            except Exception:
                pass

        if knowledge_service.sync_term_to_federated(term_id):
            success_count += 1
        
        if (i + 1) % 10 == 0:
            print(f"Progress: {i+1}/{total} (Skipped: {skipped_count}, Success: {success_count})")
            
    print(f"Finished! Successfully synced {success_count} terms. Skipped {skipped_count} already indexed.")

if __name__ == "__main__":
    start_at = int(sys.argv[1]) if len(sys.argv) > 1 else None
    force_sync = "--force" in sys.argv
    resync_all_terms(start_at, force_sync)
