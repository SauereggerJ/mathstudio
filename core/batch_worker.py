import time
import logging
import gc
import sys
import os
from pathlib import Path

# Add project root to sys.path so 'core' and 'services' can be found
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import db
from services.universal_processor import universal_processor

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("GrandSweep")

def run_grand_sweep(limit=None):
    """
    Orchestrates a mass metadata refresh for the entire library.
    Uses the 7-Phase Vision-Reflection Pipeline.
    """
    logger.info("INITIATING GRAND SWEEP: Starting mass metadata enrichment...")
    
    processed = 0
    errors = 0
    
    while True:
        if limit and processed >= limit:
            logger.info(f"Reached batch limit of {limit}. Stopping.")
            break

        # 1. Fetch next candidate (Checkpointing)
        with db.get_connection() as conn:
            # We pick books that haven't been refreshed by the new v2.2 pipeline yet
            book = conn.execute("""
                SELECT id, title FROM books 
                WHERE last_metadata_refresh = 0 
                ORDER BY id ASC 
                LIMIT 1
            """).fetchone()
        
        if not book:
            logger.info("GRAND SWEEP COMPLETE: All books are up to date.")
            break

        safe_title = (book['title'] or "Untitled")[:50]
        logger.info(f"[{processed+1}] Processing Book ID {book['id']}: {safe_title}...")
        
        start_time = time.time()
        try:
            # 2. Execute Universal Pipeline
            result = universal_processor.process_book(book['id'], save_to_db=True)
            
            if result.get('success'):
                # 3. Mark Checkpoint
                with db.get_connection() as conn:
                    conn.execute("""
                        UPDATE books SET last_metadata_refresh = unixepoch() WHERE id = ?
                    """, (book['id'],))
                elapsed = time.time() - start_time
                logger.info(f" -> SUCCESS: Processed in {elapsed:.1f}s.")
                processed += 1
            else:
                logger.error(f" -> FAILED: {result.get('error')}")
                # Mark as 'attempted with error' to avoid infinite loops, but allow retry later
                with db.get_connection() as conn:
                    conn.execute("""
                        UPDATE books SET last_metadata_refresh = -1 WHERE id = ?
                    """, (book['id'],))
                errors += 1

        except Exception as e:
            logger.error(f" -> CRITICAL ERROR on ID {book['id']}: {e}")
            errors += 1
            time.sleep(10) # Safety backoff

        # 4. RESTLESS RESOURCE RELEASE
        gc.collect()
        time.sleep(2) # Cooldown for Gemini API and local I/O

    logger.info(f"Sweep debrief: {processed} books enriched, {errors} errors encountered.")

if __name__ == '__main__':
    batch_limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run_grand_sweep(limit=batch_limit)
