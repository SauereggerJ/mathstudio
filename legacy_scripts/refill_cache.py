import time
import os
import sys
from datetime import datetime

# Add project root to path
sys.path.append('/library/mathstudio')

from core.database import db
from services.zbmath import zbmath_service

LOG_FILE = "/library/mathstudio/refill_progress.log"

def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {message}\n"
    print(entry.strip())
    with open(LOG_FILE, "a") as f:
        f.write(entry)

def run_refill():
    log("=== Cache Refill Started ===")
    
    with db.get_connection() as conn:
        # Find all books that have a Zbl ID but incomplete cache data
        targets = conn.execute("""
            SELECT b.id, b.zbl_id, b.title 
            FROM books b 
            LEFT JOIN zbmath_cache z ON b.zbl_id = z.zbl_id
            WHERE b.zbl_id IS NOT NULL AND b.zbl_id != ''
            AND (z.review_markdown IS NULL OR z.review_markdown = '' OR z.keywords IS NULL OR z.keywords = '')
        """).fetchall()

    log(f"Found {len(targets)} books needing cache refill.")
    
    for row in targets:
        bid = row['id']
        zbl = row['zbl_id']
        log(f"Refilling ID {bid} (Zbl {zbl}): {row['title']}...")
        
        try:
            zb_data = zbmath_service.get_full_metadata(zbl)
            if zb_data:
                log(f"  ✓ Cache updated.")
            else:
                log(f"  ✗ API returned no data.")
        except Exception as e:
            log(f"  ‼ ERROR: {str(e)}")
        
        time.sleep(2.5) # Gentle on the API

    log("=== Cache Refill Completed ===")

if __name__ == "__main__":
    run_refill()
