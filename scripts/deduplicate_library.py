import os
import sys
import logging
from pathlib import Path

# Add project root to path
sys.path.append(os.getcwd())

from core.database import db
from core.config import LIBRARY_ROOT
from services.library import library_service

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def deduplicate():
    logger.info("Starting Library Deduplication Process...")
    
    # 1. Identify books without hashes
    with db.get_connection() as conn:
        books_to_hash = conn.execute(
            "SELECT id, path FROM books WHERE file_hash IS NULL OR file_hash = ''"
        ).fetchall()
    
    total = len(books_to_hash)
    logger.info(f"Found {total} books missing file hashes.")
    
    # 2. Calculate and update hashes
    updated_count = 0
    for i, row in enumerate(books_to_hash):
        book_id = row['id']
        rel_path = row['path']
        abs_path = LIBRARY_ROOT / rel_path
        
        if not abs_path.exists():
            logger.warning(f"[{i+1}/{total}] File missing: {rel_path} (ID: {book_id})")
            continue
            
        try:
            file_hash = library_service.calculate_hash(str(abs_path))
            with db.get_connection() as conn:
                conn.execute(
                    "UPDATE books SET file_hash = ? WHERE id = ?", 
                    (file_hash, book_id)
                )
            updated_count += 1
            if updated_count % 50 == 0:
                logger.info(f"Progress: {updated_count}/{total} hashes calculated...")
        except Exception as e:
            logger.error(f"Failed to hash book {book_id}: {e}")
            
    logger.info(f"Completed hashing. {updated_count} books updated.")
    
    # 3. Run Sanity Check with fix=True
    logger.info("Running search for duplicates and fixing...")
    results = library_service.check_sanity(fix=True)
    
    dup_count = len(results.get("duplicates", []))
    broken_count = len(results.get("broken", []))
    
    logger.info(f"Deduplication finished.")
    logger.info(f"- Duplicates found and fixed: {dup_count}")
    logger.info(f"- Broken paths removed: {broken_count}")
    
    if dup_count > 0:
        for dup in results["duplicates"]:
            logger.info(f"Merged: {dup['best']['title']} (Removed {len(dup['redundant'])} copies)")

if __name__ == "__main__":
    deduplicate()
