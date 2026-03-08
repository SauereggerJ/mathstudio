#!/usr/bin/env python3
import sys
import shutil
import logging
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.database import db
from core.config import CONVERTED_NOTES_DIR, NOTES_OUTPUT_DIR, PROJECT_ROOT

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

def cleanup():
    logger.info("☢ Starting Nuclear Cleanup ☢")

    # 1. Database Cleanup
    logger.info("Cleaning up database tables...")
    with db.get_connection() as conn:
        tables = [
            "knowledge_terms",
            "knowledge_terms_fts",
            "extracted_pages",
            "extracted_pages_fts",
            "book_scans",
            "processing_errors",
            "note_book_relations" # Remove relations to deleted book extractions
        ]
        for table in tables:
            try:
                conn.execute(f"DELETE FROM {table}")
                logger.info(f"  ✓ Cleared table: {table}")
            except Exception as e:
                logger.warning(f"  ⚠ Failed to clear table {table}: {e}")

    # 2. Filesystem Cleanup
    logger.info("Cleaning up filesystem extractions...")
    targets = [
        CONVERTED_NOTES_DIR,
        NOTES_OUTPUT_DIR,
        PROJECT_ROOT / "knowledge_vault" # Legacy vault
    ]
    
    for target in targets:
        if target.exists():
            logger.info(f"  Removing {target}...")
            # We don't want to delete the directory itself if it's a standard path,
            # just its contents.
            for item in target.iterdir():
                try:
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                except Exception as e:
                    logger.warning(f"  ⚠ Failed to delete {item}: {e}")
            logger.info(f"  ✓ Cleared directory: {target}")

    # 3. Search Index Cleanup (MWS Harvest)
    logger.info("Cleaning up MathWebSearch harvest file...")
    harvest_file = PROJECT_ROOT / "mathstudio.harvest"
    if harvest_file.exists():
        try:
            harvest_file.write_text("<harvest xmlns=\"http://www.mathweb.org/mws/harvest\">\n</harvest>", encoding='utf-8')
            logger.info("  ✓ Truncated mathstudio.harvest")
        except Exception as e:
            logger.warning(f"  ⚠ Failed to truncate harvest file: {e}")

    # 4. Elasticsearch Purge
    logger.info("Purging Elasticsearch indices...")
    from core.search_engine import es_client, create_mathstudio_indices
    indices_to_wipe = ["mathstudio_terms", "mathstudio_pages"]
    for idx in indices_to_wipe:
        try:
            if es_client.indices.exists(index=idx):
                es_client.indices.delete(index=idx)
                logger.info(f"  ✓ Deleted ES index: {idx}")
        except Exception as e:
            logger.warning(f"  ⚠ Failed to delete ES index {idx}: {e}")
    
    # Re-create them empty
    try:
        create_mathstudio_indices()
        logger.info("  ✓ Re-initialized empty ES indices.")
    except Exception as e:
        logger.error(f"  ⚠ Failed to re-initialize ES indices: {e}")

    logger.info("☢ Cleanup Complete. System is now in a clean state (Tula Rasa). ☢")

if __name__ == "__main__":
    confirm = input("This will DELETE ALL extracted data. Type 'yes' to confirm: ")
    if confirm.lower() == 'yes':
        cleanup()
    else:
        print("Cleanup aborted.")
