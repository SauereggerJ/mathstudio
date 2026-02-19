import json
import re
import logging
import requests
import fitz  # PyMuPDF
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from core.database import db
from core.config import LIBRARY_ROOT, GEMINI_MODEL, get_api_key

logger = logging.getLogger(__name__)

class BibliographyService:
    BIB_KEYWORDS = ["bibliography", "references", "cited works", "works cited", "literature cited",
                    "literaturverzeichnis", "bibliographie", "quellenverzeichnis", "literatur",
                    "list of references", "reference list"]

    def __init__(self):
        self.api_key = get_api_key()
        self.model = GEMINI_MODEL

    def find_bib_pages(self, book_path: Path) -> List[int]:
        pages = []
        try:
            doc = fitz.open(str(book_path))
            total_pages = len(doc)
            for i in range(total_pages - 1, max(-1, total_pages - 60), -1):
                text = doc[i].get_text().lower()
                if any(kw in text[:500] for kw in self.BIB_KEYWORDS):
                    pages.append(i + 1)
                    curr = i - 1
                    while curr >= 0:
                        prev_text = doc[curr].get_text().lower()
                        if len(re.findall(r"\[\d+\]", prev_text)) > 5 or len(re.findall(r"19\d{2}|20\d{2}", prev_text)) > 5:
                            pages.append(curr + 1)
                            curr -= 1
                        else: break
                    break
            doc.close()
        except Exception as e: logger.error(f"Error finding bib pages: {e}")
        return sorted(list(set(pages)))

    def extract_and_structure_page(self, pdf_path: Path, page_num: int) -> List[Dict]:
        try:
            doc = fitz.open(str(pdf_path))
            text = doc[page_num - 1].get_text()
            doc.close()
            if len(text.strip()) < 100: return []
            
            prompt = (
                "You are a bibliography expert. Extract all bibliography entries from the following text.\n"
                "For each entry, create a JSON object with: 'title', 'author', 'year', and 'raw_text' (verbatim).\n"
                "Return a JSON array of these objects.\n"
                f"TEXT:\n{text}"
            )
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
            payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json"}}
            res = requests.post(url, json=payload, timeout=60)
            if res.status_code == 200:
                return json.loads(res.json()['candidates'][0]['content']['parts'][0]['text'])
        except Exception as e: logger.error(f"Extraction failed: {e}")
        return []

    def scan_book(self, book_id: int) -> Dict:
        """Schneller Scan: Extrahiert nur die Daten, Auflösung macht der Background-Worker."""
        with db.get_connection() as conn:
            book = conn.execute("SELECT title, path FROM books WHERE id = ?", (book_id,)).fetchone()
        
        if not book: return {"success": False, "error": "Book not found"}
        abs_path = LIBRARY_ROOT / book['path']
        pages = self.find_bib_pages(abs_path)
        if not pages: return {"success": False, "error": "No bibliography pages found"}

        # 1. Extraktion (nur wenn noch nicht geschehen)
        with db.get_connection() as conn:
            exists = conn.execute("SELECT COUNT(*) FROM bib_entries WHERE book_id = ?", (book_id,)).fetchone()[0]
        
        if exists == 0:
            for p in pages:
                structured_entries = self.extract_and_structure_page(abs_path, p)
                if structured_entries:
                    with db.get_connection() as conn:
                        for entry in structured_entries:
                            if not isinstance(entry, dict): continue
                            conn.execute('''
                                INSERT INTO bib_entries (book_id, raw_text, title, author)
                                VALUES (?, ?, ?, ?)
                            ''', (book_id, entry.get('raw_text', ''), entry.get('title'), entry.get('author')))

        # 2. Aktuellen Stand aus DB laden (schnell)
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, raw_text, title, author, resolved_zbl_id as doi, confidence 
                FROM bib_entries WHERE book_id = ?
            """, (book_id,))
            rows = [dict(r) for r in cursor.fetchall()]

        citations = []
        owned_count = 0
        for r in rows:
            status = 'owned' if r['confidence'] and r['confidence'] >= 1.0 else 'missing'
            if status == 'owned': owned_count += 1
            citations.append({**r, 'status': status})
            
        return {
            "success": True,
            "book_title": book['title'],
            "pages": pages,
            "citations": citations,
            "stats": {"total": len(citations), "owned": owned_count, "missing": len(citations) - owned_count}
        }

bibliography_service = BibliographyService()
