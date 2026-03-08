"""
Post-Extraction Pipeline: Runs after term extraction completes.
Chains: Embed New Terms -> Anchor to Concepts -> Backfill concept_ids to ES
"""
import sys
import time
import sqlite3

sys.path.insert(0, '/library/mathstudio')

from core.database import db

def wait_for_extraction(book_id):
    """Poll until no more unharvested pages remain."""
    while True:
        with db.get_connection() as conn:
            remaining = conn.execute(
                "SELECT COUNT(*) FROM extracted_pages WHERE book_id = ? AND quality_score >= 0.7 AND harvested_at IS NULL",
                (book_id,)
            ).fetchone()[0]
        if remaining == 0:
            print(f"[Pipeline] All pages for book {book_id} have been harvested.")
            return
        print(f"[Pipeline] Waiting for extraction... {remaining} pages remaining.")
        time.sleep(30)

def run_embedding():
    print("\n[Pipeline] === Step 1: Embedding New Terms ===")
    from scripts.batch_embed_terms import main as embed_terms
    embed_terms()

def run_anchoring():
    print("\n[Pipeline] === Step 2: Anchoring to Concepts ===")
    from services.anchoring import AnchoringService
    svc = AnchoringService()
    svc.run_clustering()

def run_backfill():
    print("\n[Pipeline] === Step 3: Backfilling concept_ids to ES ===")
    from scripts.backfill_concept_ids import backfill
    backfill()

if __name__ == "__main__":
    book_id = int(sys.argv[1]) if len(sys.argv) > 1 else 238
    
    print(f"[Pipeline] Waiting for book {book_id} extraction to complete...")
    wait_for_extraction(book_id)
    
    run_embedding()
    run_anchoring()
    run_backfill()
    
    print("\n[Pipeline] === ALL DONE === New terms are fully embedded, anchored, and searchable!")
