#!/usr/bin/env python3
import os
import sys
import logging
from pathlib import Path

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.ingestor import ingestor_service
from core.config import UNSORTED_DIR

# Setup logging to both console and file
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("batch_ingestion.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("batch-ingest")

def run_batch():
    logger.info(f"Starting batch ingestion from: {UNSORTED_DIR}")
    
    if not UNSORTED_DIR.exists():
        logger.error(f"Unsorted directory not found: {UNSORTED_DIR}")
        return

    # List all supported files
    files = [f for f in UNSORTED_DIR.glob("*") if f.suffix.lower() in ('.pdf', '.djvu')]
    total = len(files)
    logger.info(f"Found {total} files to process.")

    for i, file_path in enumerate(files):
        logger.info(f"[{i+1}/{total}] Processing: {file_path.name}")
        try:
            result = ingestor_service.process_file(file_path, execute=True)
            if result.get('status') == 'success':
                logger.info(f"  ✓ Success: {result.get('path')}")
            elif result.get('status') == 'duplicate':
                logger.warning(f"  ! Duplicate skipped: {file_path.name}")
            else:
                logger.error(f"  ✗ Failed: {result.get('message') or 'Unknown error'}")
        except Exception as e:
            logger.error(f"  ✗ Fatal error processing {file_path.name}: {e}", exc_info=True)
        
        # Brief pause between books to let services settle
        import time
        time.sleep(2)

if __name__ == "__main__":
    run_batch()
