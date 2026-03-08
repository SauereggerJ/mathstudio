
import sys
import os
import time

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

from services.note import note_service
from core.database import db

def resume_extraction(book_id, start_page, end_page):
    print(f"Resuming extraction for Book {book_id} from page {start_page} to {end_page}...")
    
    # We use a window size of 5 for extraction
    batch_size = 5
    for p in range(start_page, end_page + 1, batch_size):
        pages_list = list(range(p, min(p + batch_size, end_page + 1)))
        print(f"Processing batch: {pages_list}")
        
        try:
            count, error = note_service.extract_and_save_knowledge_terms_batch(book_id, pages_list)
            if error:
                print(f"  [ERROR] {error}")
            else:
                print(f"  [SUCCESS] Found {count} terms.")
        except Exception as e:
            print(f"  [CRASH] {str(e)}")
        
        # Cooldown to avoid API rate limits
        time.sleep(1)

if __name__ == "__main__":
    # Zorich Analysis I is ID 554
    # Last processed was 488, total is 630
    resume_extraction(554, 489, 630)
