import time
import sys
import os
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.append(str(PROJECT_ROOT))

from services.note import note_service
from core.database import db

LOG_FILE = PROJECT_ROOT / "zorich_ingestion.log"

def log(msg):
    with open(LOG_FILE, "a") as f:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"[{timestamp}] {msg}\n")
    print(msg)

def run_ingestion():
    book_id = 554
    # Find last processed page from extracted_pages
    with db.get_connection() as conn:
        row = conn.execute("SELECT max(page_number) FROM extracted_pages WHERE book_id = ?", (book_id,)).fetchone()
        last_page = row[0] if row and row[0] else 21
    
    start_at = last_page + 1
    end_page = 630
    
    log(f"Resuming Zorich I Ingestion from page {start_at} to {end_page}")
    
    for start in range(start_at, end_page + 1, 5):
        pages = list(range(start, min(start + 5, end_page + 1)))
        log(f"Processing Chunk: {pages}")
        
        try:
            count, error = note_service.extract_and_save_knowledge_terms_batch(book_id, pages, force=True)
            if error:
                log(f"  [ERROR] {error}")
            else:
                log(f"  [SUCCESS] Found {count} terms.")
        except Exception as e:
            log(f"  [CRASH] {str(e)}")
            time.sleep(10)
        
        time.sleep(5)

if __name__ == "__main__":
    run_ingestion()
