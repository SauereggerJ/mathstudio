
import sys
import os
import time

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

from services.note import note_service
from core.database import db

def full_extraction(book_id, start_page, end_page):
    print(f"Starting FRESH extraction for Zorich I (Book {book_id}) from page {start_page} to {end_page}...")
    
    # Process in batches of 5
    batch_size = 5
    for p in range(start_page, end_page + 1, batch_size):
        pages_list = list(range(p, min(p + batch_size, end_page + 1)))
        print(f"Processing Zorich I batch: {pages_list}")
        
        try:
            # This method will use cached LaTeX where available
            count, error = note_service.extract_and_save_knowledge_terms_batch(book_id, pages_list)
            if error:
                print(f"  [ERROR] {error}")
            else:
                print(f"  [SUCCESS] Found {count} terms.")
        except Exception as e:
            print(f"  [CRASH] {str(e)}")
        
        time.sleep(0.5)

if __name__ == "__main__":
    # Zorich Analysis I is ID 554
    # Chapter 1 starts around page 22
    full_extraction(554, 22, 630)
