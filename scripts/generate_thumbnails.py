#!/usr/bin/env python3
import os
import sys
import logging
from pathlib import Path

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import db
from core.config import THUMBNAIL_DIR
from services.indexer import indexer_service

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("thumb-gen")

def run_repair(force=False):
    logger.info("Starting thumbnail repair/generation process...")
    
    with db.get_connection() as conn:
        books = conn.execute("SELECT id, title FROM books").fetchall()
    
    total = len(books)
    generated = 0
    skipped = 0
    errors = 0
    
    logger.info(f"Found {total} books in database.")
    
    for i, book in enumerate(books):
        book_id = book['id']
        title = book['title'] or "Unknown Title"
        
        # Check if already exists
        if not force and (THUMBNAIL_DIR / str(book_id) / "page_1.png").exists():
            skipped += 1
            if (i+1) % 50 == 0:
                logger.info(f"Progress: {i+1}/{total} (Skipped: {skipped}, Generated: {generated})")
            continue
            
        logger.info(f"[{i+1}/{total}] Generating thumbnails for: {title} (ID: {book_id})")
        try:
            success = indexer_service.generate_thumbnails(book_id, force=force)
            if success:
                generated += 1
            else:
                logger.warning(f"  ! Generation failed (file missing?) for ID: {book_id}")
                errors += 1
        except Exception as e:
            logger.error(f"  ✗ Fatal error for ID {book_id}: {e}")
            errors += 1
            
    logger.info("--- Thumbnail Generation Summary ---")
    logger.info(f"Total Books: {total}")
    logger.info(f"Generated:   {generated}")
    logger.info(f"Skipped:     {skipped} (already had thumbnails)")
    logger.info(f"Errors:      {errors}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate missing book thumbnails.")
    parser.add_argument("--force", action="store_true", help="Force regeneration of existing thumbnails.")
    args = parser.parse_args()
    
    run_repair(force=args.force)
