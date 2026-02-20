import logging
import time
from typing import List, Dict, Any
from core.database import db
from services.zbmath import zbmath_service

logger = logging.getLogger(__name__)

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

            # Fetch existing FTS content (we don't want to lose the full text!)
            fts = cursor.execute("SELECT content, index_content FROM books_fts WHERE rowid = ?", (book_id,)).fetchone()
            content = fts['content'] if fts else ""
            index_content = fts['index_content'] if fts else ""

            # Update FTS
            cursor.execute("DELETE FROM books_fts WHERE rowid = ?", (book_id,))
            cursor.execute("""
                INSERT INTO books_fts (rowid, title, author, content, index_content) 
                VALUES (?, ?, ?, ?, ?)
            """, (book_id, book['title'], book['author'], content, index_content))

    def enrich_all_with_doi(self, limit: int = 50) -> Dict[str, Any]:
        """Batch enrichment for all books that have a DOI but aren't verified yet."""
        with self.db.get_connection() as conn:
            candidates = conn.execute("""
                SELECT id FROM books 
                WHERE doi IS NOT NULL 
                AND doi != '' 
                AND (metadata_status = 'raw' OR metadata_status IS NULL)
                LIMIT ?
            """, (limit,)).fetchall()

        results = {"total": len(candidates), "healed": 0, "errors": 0}
        for cand in candidates:
            bid = cand['id']
            try:
                res = zbmath_service.enrich_book(bid)
                if res.get('success'):
                    self.sync_fts_after_enrichment(bid)
                    results["healed"] += 1
                else:
                    results["errors"] += 1
            except Exception as e:
                logger.error(f"Enrichment failed for book {bid}: {e}")
                results["errors"] += 1
            
            # Respect rate limits
            time.sleep(1.0)
            
        return results

enrichment_service = EnrichmentService()
