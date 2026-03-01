import time
import os
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.database import db
from services.zbmath import zbmath_service
from services.enrichment import enrichment_service

LOG_FILE = PROJECT_ROOT / "grand_sweep.log"

def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {message}\n"
    print(entry.strip())
    with open(LOG_FILE, "a") as f:
        f.write(entry)

def phase_1_deep_search():
    log("--- Phase 1: Deep Search for Raw/Not Found ---")
    with db.get_connection() as conn:
        targets = conn.execute("""
            SELECT id, title FROM books 
            WHERE (metadata_status IN ('raw', 'not_found') OR metadata_status IS NULL)
            AND title IS NOT NULL AND title != '' AND title NOT LIKE 'Unknown%'
            ORDER BY id ASC
        """).fetchall()
    
    log(f"Found {len(targets)} candidates for search.")
    for row in targets:
        bid = row['id']
        log(f"Hunting ID {bid}: {row['title']}...")
        try:
            res = zbmath_service.enrich_book(bid)
            if res.get('success'):
                enrichment_service.sync_fts_after_enrichment(bid)
                log(f"  ✓ FOUND: Zbl {res.get('zbl_id')} (Status: {res.get('status')})")
            else:
                log(f"  ✗ STILL NOT FOUND: {res.get('error')}")
        except Exception as e:
            log(f"  ‼ ERROR: {str(e)}")
        time.sleep(2.5)

def phase_2_refill_cache():
    log("--- Phase 2: Metadata Refill for Verified Books ---")
    with db.get_connection() as conn:
        # Fetch verified books where we might be missing the cache entry
        targets = conn.execute("""
            SELECT id, zbl_id, title FROM books 
            WHERE zbl_id IS NOT NULL AND zbl_id != ''
        """).fetchall()
    
    log(f"Found {len(targets)} linked books. Ensuring full cache...")
    for row in targets:
        zbl = row['zbl_id']
        # Check if cache is actually empty or missing fields
        with db.get_connection() as conn:
            cache = conn.execute("SELECT review_markdown, keywords FROM zbmath_cache WHERE zbl_id = ?", (zbl,)).fetchone()
        
        needs_update = not cache or not cache['review_markdown'] or not cache['keywords']
        
        if needs_update:
            log(f"Refilling ID {row['id']} (Zbl {zbl})...")
            try:
                zb_data = zbmath_service.get_full_metadata(zbl)
                if zb_data:
                    log(f"  ✓ Cache Refilled.")
                else:
                    log(f"  ✗ API fetch failed for refill.")
            except Exception as e:
                log(f"  ‼ ERROR during refill: {str(e)}")
            time.sleep(2.5)
        # else: Skip, already has the 'good shit'

def run():
    log("=== GRAND SWEEP STARTED ===")
    phase_1_deep_search()
    phase_2_refill_cache()
    log("=== GRAND SWEEP COMPLETED ===")

if __name__ == "__main__":
    run()
