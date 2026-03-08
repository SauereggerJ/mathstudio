import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.append(str(PROJECT_ROOT))

from services.note import note_service
from core.database import db

def fix_missing_page(book_id, page_num):
    print(f"Triggering conversion for Book {book_id}, Page {page_num} with low min_quality...")
    # Setting min_quality=0.1 to force save even if it doesn't compile
    results, error = note_service.get_or_convert_pages(book_id, [page_num], force_refresh=True, min_quality=0.1)
    if error:
        print(f"Error: {error}")
    else:
        print(f"Success! Page {page_num} converted and cached.")
        # Re-check the database
        with db.get_connection() as conn:
            row = conn.execute("SELECT * FROM extracted_pages WHERE book_id = ? AND page_number = ?", (book_id, page_num)).fetchone()
            if row:
                print(f"Database entry found: {row['latex_path']}")
            else:
                print("Database entry STILL missing. Checking quality score logic...")

if __name__ == "__main__":
    fix_missing_page(508, 232)
