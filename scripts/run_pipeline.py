#!/usr/bin/env python3
"""
Decoupled Book Ingestion Pipeline v3 (CLI Wrapper)
Powered by PipelineService
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.pipeline import pipeline_service

# ─── Logging Setup ───────────────────────────────────────────────────────────

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

def setup_logging(book_id: int, pass_num: int) -> logging.Logger:
    """Creates a logger that writes to both console and a book-specific log file."""
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"pipeline_book{book_id}_pass{pass_num}_{timestamp}.log"

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    # File handler
    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setFormatter(logging.Formatter('%(asctime)s | %(levelname)-8s | %(message)s'))
    logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter('%(asctime)s | %(levelname)-8s | %(message)s'))
    logger.addHandler(ch)

    logger.info(f"═══ Pipeline CLI: Book {book_id}, Pass {pass_num} ═══")
    return logger

# ─── Main Entry Point ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Decoupled Book Ingestion Pipeline")
    parser.add_argument("--book-id", type=int, required=True, help="Book ID to process")
    parser.add_argument("--pass", type=int, required=True, choices=[0, 1, 2], dest="pass_num")
    parser.add_argument("--api", choices=["gemini", "deepseek"], default="gemini")
    parser.add_argument("--pages", type=str, default=None, help="Page range e.g. '17-27'")
    parser.add_argument("--retry-failed", action="store_true")

    args = parser.parse_args()
    logger = setup_logging(args.book_id, args.pass_num)

    # Parse page range
    page_list = None
    if args.pages:
        try:
            parts = args.pages.split("-")
            if len(parts) == 2:
                page_list = list(range(int(parts[0]), int(parts[1]) + 1))
            else:
                page_list = [int(p) for p in args.pages.split(",")]
        except:
            logger.error(f"Invalid page range: {args.pages}")
            sys.exit(1)

    try:
        if args.pass_num == 0:
            success = pipeline_service.run_pass_0(args.book_id)
        elif args.pass_num == 1:
            stats = pipeline_service.run_pass_1(args.book_id, retry_failed=args.retry_failed, pages=page_list)
            logger.info(f"Pass 1 Stats: {stats}")
            success = stats.get("failed", 0) == 0
        elif args.pass_num == 2:
            stats = pipeline_service.run_pass_2(args.book_id, api=args.api, pages=page_list)
            logger.info(f"Pass 2 Stats: {stats}")
            success = stats.get("error", 0) == 0

        if success:
            logger.info("═══ Pipeline pass completed successfully ═══")
        else:
            logger.warning("═══ Pipeline pass completed with some issues ═══")

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
