import json
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import fitz  # PyMuPDF
from core.database import db
from core.ai import ai
from core.config import LIBRARY_ROOT, DB_FILE

BIB_KEYWORDS = [
    "bibliography", "references", "cited works", "works cited", "literature cited",
    "literaturverzeichnis", "bibliographie", "quellenverzeichnis", "literatur",
    "list of references", "reference list"
]

class BibliographyService:
    def __init__(self):
        self.db = db
        self.ai = ai

    def find_bib_pages(self, book_id: int) -> Tuple[Optional[List[int]], Optional[str]]:
        """Finds bibliography pages in a book (PDF only for now)."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT path FROM books WHERE id = ?", (book_id,))
            row = cursor.fetchone()
            
        if not row: return None, "Book not found"
        
        book_path = LIBRARY_ROOT / row['path']
        if not book_path.exists(): return None, "File not found"
        if book_path.suffix.lower() != '.pdf': return None, "Only PDF supported"

        try:
            doc = fitz.open(str(book_path))
            total_pages = len(doc)
            start_page = max(0, total_pages - 30)
            bib_pages = []
            
            for page_num in range(start_page, total_pages):
                text = doc[page_num].get_text().lower()
                for keyword in BIB_KEYWORDS:
                    if keyword in text and text.index(keyword) < 500:
                        bib_pages.append(page_num + 1)
                        break
            doc.close()
            
            if not bib_pages: return None, "No bibliography found in last 30 pages"
            
            first = min(bib_pages)
            last = min(first + 9, total_pages)
            return list(range(first, last + 1)), None
        except Exception as e:
            return None, str(e)

    def parse_citations(self, book_id: int, pages: List[int]) -> Tuple[Optional[List[Dict]], Optional[str]]:
        """Extracts book citations from specific pages using AI."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT path FROM books WHERE id = ?", (book_id,))
            row = cursor.fetchone()
            
        book_path = LIBRARY_ROOT / row['path']
        
        try:
            doc = fitz.open(str(book_path))
            bib_text = ""
            for p in pages:
                if p <= len(doc):
                    bib_text += f"\n--- Page {p} ---\n" + doc[p-1].get_text()
            doc.close()

            prompt = (
                "You are a bibliography extraction expert. Extract all BOOK citations from the following text.\n"
                "Return a JSON array of objects: [{'title': '...', 'author': '...'}].\n"
                "IGNORE journals and conference papers.\n\n"
                f"Text:\n{bib_text[:20000]}"
            )
            
            citations = self.ai.generate_json(prompt)
            if not citations: return None, "AI failed to extract citations"
            return citations, None
        except Exception as e:
            return None, str(e)

    def scan_book(self, book_id: int) -> Dict:
        """Full bibliography scan workflow."""
        pages, error = self.find_bib_pages(book_id)
        if error: return {"success": False, "error": error}
        
        citations, error = self.parse_citations(book_id, pages)
        if error: return {"success": False, "error": error, "pages": pages}
        
        # Cross-check logic
        from services.fuzzy_matcher import FuzzyBookMatcher
        matcher = FuzzyBookMatcher(str(DB_FILE), threshold=0.75)
        results = matcher.batch_match(citations)
        
        enriched = []
        owned_count = 0
        for i, res in enumerate(results):
            c = citations[i]
            status = 'owned' if res['found'] else 'missing'
            if res['found']: owned_count += 1
            enriched.append({**c, 'status': status, 'match': res.get('match')})
            
        return {
            "success": True,
            "book_id": book_id,
            "pages": pages,
            "citations": enriched,
            "stats": {"total": len(enriched), "owned": owned_count, "missing": len(enriched) - owned_count}
        }

# Global instance
bibliography_service = BibliographyService()
