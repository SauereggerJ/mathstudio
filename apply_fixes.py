from services.library import library_service
from core.database import db

def apply_housekeeping_fixes():
    print("=== Applying Language and Metadata Fixes ===")
    
    # 1. Fix Language Mismatches
    mismatches = library_service.find_language_mismatches(limit=50)
    fixed_count = 0
    
    for m in mismatches:
        book_id = m['id']
        print(f"Checking ID {book_id}: {m['title']}...")
        
        # Detect actual language
        lang = library_service.detect_book_language(book_id)
        
        if lang == 'german':
            old_title = m['title']
            if library_service.fix_language_mismatch(book_id):
                fixed_count += 1
                with db.get_connection() as conn:
                    new_title = conn.execute("SELECT title FROM books WHERE id = ?", (book_id,)).fetchone()[0]
                print(f" -> FIXED: '{old_title}' -> '{new_title}'")
            else:
                print(f" -> Could not determine better German title for {book_id}")
        else:
            print(f" -> Confirmed as {lang}, no fix applied.")

    print(f"\nFinished. Total language mismatches fixed: {fixed_count}")

    # 2. Run deduplication (fix=True)
    print("\nRunning deduplication fix...")
    sanity_results = library_service.check_sanity(fix=True)
    duplicates = sanity_results.get('duplicates', [])
    print(f"Deduplication complete. {len(duplicates)} duplicate groups processed.")

if __name__ == "__main__":
    apply_housekeeping_fixes()
