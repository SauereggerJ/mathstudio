import json
import logging
import time
from pathlib import Path
from typing import List, Dict, Any
from core.database import db
from core.ai import ai
from core.utils import PDFHandler
from core.config import LIBRARY_ROOT

logger = logging.getLogger(__name__)

class BibliographyService:
    """Specialized service for deep, iterative bibliography scanning."""

    def __init__(self):
        self.ai = ai
        self.db = db

    def process_book_bibliography(self, book_id: int):
        """Wrapper for scan_book to match standard service naming."""
        return self.scan_book(book_id)

    def resolve_citations(self, book_id: int) -> Dict[str, Any]:
        """Resolves raw bibliography entries to Zbl IDs using zbmath_service."""
        from .zbmath import zbmath_service
        
        with self.db.get_connection() as conn:
            entries = conn.execute("""
                SELECT id, raw_text FROM bib_entries 
                WHERE book_id = ? AND resolved_zbl_id IS NULL
            """, (book_id,)).fetchall()
            
        if not entries:
            return {"success": True, "message": "No pending entries to resolve"}
            
        resolved_count = 0
        for row in entries:
            try:
                # 1. Resolve raw text to official metadata + Zbl ID
                # match_citation returns full metadata if matched
                data = zbmath_service.match_citation(row['raw_text'])
                
                if data and data.get('zbl_id'):
                    with self.db.get_connection() as conn:
                        conn.execute("""
                            UPDATE bib_entries SET resolved_zbl_id = ?, confidence = 1.0 
                            WHERE id = ?
                        """, (data['zbl_id'], row['id']))
                        
                        # Add to many-to-many graph
                        conn.execute("""
                            INSERT OR IGNORE INTO book_citations (book_id, zbl_id)
                            VALUES (?, ?)
                        """, (book_id, data['zbl_id']))
                    resolved_count += 1
                
                # Small sleep to be polite to zbMATH API
                time.sleep(1)
            except Exception as e:
                logger.error(f"Failed to resolve citation {row['id']}: {e}")
                
        return {"success": True, "resolved": resolved_count, "total": len(entries)}

    def scan_book(self, book_id: int) -> Dict[str, Any]:
        """Iterative Vision-First scan for every citation."""
        with self.db.get_connection() as conn:
            book = conn.execute("SELECT title, path FROM books WHERE id = ?", (book_id,)).fetchone()
        if not book: return {"success": False, "error": "Book not found"}
        
        abs_path = LIBRARY_ROOT / book['path']
        handler = PDFHandler(abs_path)
        
        try:
            # 1. Target Detection
            ranges = handler.estimate_slicing_ranges()
            bib_pages = ranges["bibliography"]
            if not bib_pages: return {"success": False, "error": "No bibliography found"}

            full_bib = []
            chunk_size = 8 # Safety first
            
            for i in range(0, len(bib_pages), chunk_size):
                chunk = bib_pages[i : i + chunk_size]
                chunk_slice = Path(f"/tmp/bib_deep_{book_id}_{i}.pdf")
                handler.create_slice(chunk, chunk_slice)
                
                uploaded = self.ai.upload_file(chunk_slice)
                prompt = "EXTRACT EVERY SINGLE BIBLIOGRAPHY ENTRY on EVERY page. NO SUMMARIES. JSON array: [{title, author, year, raw_text}]"
                
                # Manual SDK call for speed/directness
                from google.genai import types
                contents = [types.Content(role="user", parts=[
                    types.Part.from_uri(file_uri=uploaded.uri, mime_type=uploaded.mime_type),
                    types.Part.from_text(text=prompt)
                ])]
                chunk_entries = self.ai.generate_json(contents)
                
                if isinstance(chunk_entries, list):
                    full_bib.extend(chunk_entries)
                
                self.ai.delete_file(uploaded.name)
                chunk_slice.unlink()
                time.sleep(1)

            # 2. Persistence
            with self.db.get_connection() as conn:
                conn.execute("DELETE FROM bib_entries WHERE book_id = ?", (book_id,))
                for entry in full_bib:
                    if isinstance(entry, dict):
                        conn.execute("""
                            INSERT INTO bib_entries (book_id, raw_text, title, author)
                            VALUES (?, ?, ?, ?)
                        """, (book_id, entry.get('raw_text', ''), entry.get('title', ''), entry.get('author', '')))

            return {
                "success": True, 
                "count": len(full_bib), 
                "citations": full_bib,
                "book_title": book['title']
            }

        except Exception as e:
            logger.error(f"Bib scan failed: {e}")
            return {"success": False, "error": str(e)}

bibliography_service = BibliographyService()
