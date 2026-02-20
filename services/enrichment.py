import logging
import time
import os
from typing import List, Dict, Any
from core.database import db
from services.zbmath import zbmath_service

# Setup dedicated logger for enrichment
log_file = "enrichment_batch.log"
file_handler = logging.FileHandler(log_file)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger = logging.getLogger("enrichment")
logger.addHandler(file_handler)
logger.setLevel(logging.INFO)

class EnrichmentService:
    def __init__(self):
        self.db = db

    def sync_fts_after_enrichment(self, book_id: int):
        """Synchronizes the FTS index after metadata has changed."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            # Fetch updated metadata
            book = cursor.execute("SELECT title, author FROM books WHERE id = ?", (book_id,)).fetchone()
            if not book: return

            # Fetch existing FTS content
            fts = cursor.execute("SELECT content, index_content FROM books_fts WHERE rowid = ?", (book_id,)).fetchone()
            content = fts['content'] if fts else ""
            index_content = fts['index_content'] if fts else ""

            # Update FTS
            cursor.execute("DELETE FROM books_fts WHERE rowid = ?", (book_id,))
            cursor.execute("""
                INSERT INTO books_fts (rowid, title, author, content, index_content) 
                VALUES (?, ?, ?, ?, ?)
            """, (book_id, book['title'], book['author'], content, index_content))

    def enrich_batch(self, limit: int = 50) -> Dict[str, Any]:
        """Batch enrichment for books that aren't verified yet."""
        logger.info(f"--- Starting Enrichment Batch (Limit: {limit}) ---")
        with self.db.get_connection() as conn:
            candidates = conn.execute("""
                SELECT id, title, path, page_count FROM books 
                WHERE (metadata_status = 'raw' OR metadata_status IS NULL)
                AND title IS NOT NULL AND title != '' AND title NOT LIKE 'Unknown%'
                ORDER BY id ASC
                LIMIT ?
            """, (limit,)).fetchall()

        results = {"total": len(candidates), "healed": 0, "errors": 0}
        for cand in candidates:
            bid = cand['id']
            title = cand['title']
            path = cand['path']
            
            # 1. Heal Page Count if missing
            if not cand['page_count'] or cand['page_count'] <= 0:
                try:
                    abs_path = LIBRARY_ROOT / path
                    if abs_path.exists():
                        import fitz
                        if abs_path.suffix.lower() == '.djvu':
                            import subprocess
                            res = subprocess.run(['djvused', '-e', 'n', str(abs_path)], capture_output=True, text=True)
                            count = int(res.stdout.strip())
                        else:
                            doc = fitz.open(abs_path)
                            count = len(doc)
                            doc.close()
                        
                        if count > 0:
                            with self.db.get_connection() as conn:
                                conn.execute("UPDATE books SET page_count = ? WHERE id = ?", (count, bid))
                            logger.info(f"  📏 Healed Page Count: {count} for ID {bid}")
                except Exception as e:
                    logger.warning(f"  📏 Failed to heal page count for ID {bid}: {e}")

            # 2. zbMATH Enrichment
            logger.info(f"Processing Book ID {bid}: {title}...")
            try:
                res = zbmath_service.enrich_book(bid)
                if res.get('success'):
                    self.sync_fts_after_enrichment(bid)
                    logger.info(f"  ✓ SUCCESS: Zbl {res.get('zbl_id')} (Score: {res.get('trust_score')})")
                    results["healed"] += 1
                else:
                    logger.warning(f"  ✗ FAILED: {res.get('error')}")
                    results["errors"] += 1
            except Exception as e:
                logger.error(f"  ‼ CRITICAL ERROR for book {bid}: {e}")
                results["errors"] += 1
            
            time.sleep(1.2)
            
        logger.info(f"--- Batch Complete: {results['healed']} healed, {results['errors']} errors ---")
        return results

enrichment_service = EnrichmentService()
