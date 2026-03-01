import time
import os
import sys
from datetime import datetime

# Add project root to path
sys.path.append('/library/mathstudio')

from core.database import db
from services.zbmath import zbmath_service
from services.enrichment import enrichment_service

LOG_FILE = "enrichment_full_run.log"

def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {message}\n"
    print(entry.strip())
    with open(LOG_FILE, "a") as f:
        f.write(entry)

def run():
    log("=== Global Enrichment Run Started ===")
    
    while True:
        with db.get_connection() as conn:
            # Get the next batch of raw books
            targets = conn.execute("""
                SELECT id, title FROM books 
                WHERE (metadata_status = 'raw' OR metadata_status IS NULL)
                AND title IS NOT NULL AND title != '' AND title NOT LIKE 'Unknown%'
                ORDER BY id ASC
                LIMIT 10
            """).fetchall()

        if not targets:
            log("No more raw books to process. Execution finished.")
            break

        for row in targets:
            bid = row['id']
            title = row['title']
            log(f"Processing ID {bid}: {title}")
            
            try:
                # Use global zbmath_service instead of incorrect enrichment_service attribute
                res = zbmath_service.enrich_book(bid)
                if res.get('success'):
                    enrichment_service.sync_fts_after_enrichment(bid)
                    log(f"  ✓ SUCCESS: Zbl {res.get('zbl_id')} (Status: {res.get('status')})")
                else:
                    log(f"  ✗ FAILED: {res.get('error')}")
            except Exception as e:
                log(f"  ‼ CRITICAL ERROR: {str(e)}")
            
            # Respectful delay
            time.sleep(2.5)

    log("=== Global Enrichment Run Completed ===")

if __name__ == "__main__":
    run()
