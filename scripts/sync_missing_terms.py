import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import db
from services.knowledge import knowledge_service

def sync_all():
    print("Fetching all terms from SQLite...")
    with db.get_connection() as conn:
        terms = conn.execute("SELECT id FROM knowledge_terms").fetchall()
    
    print(f"Found {len(terms)} terms. Syncing to federated search...")
    success = 0
    for row in terms:
        tid = row['id']
        print(f"Syncing term {tid}...")
        try:
            res = knowledge_service.sync_term_to_federated(tid)
            success += 1
            print(f"Result for {tid}: {res}")
        except Exception as e:
            print(f"Failed to sync {tid}: {e}")
            
    print(f"Done! Successfully synced {success}/{len(terms)} terms.")

if __name__ == "__main__":
    sync_all()
