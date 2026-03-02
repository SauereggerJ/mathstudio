import json
import logging
import time
import gc
from pathlib import Path
from typing import Dict, Any, Optional, List
from google.genai import types

from core.database import db
from core.ai import ai
from core.utils import PDFHandler
from core.config import LIBRARY_ROOT, IGNORED_FOLDERS
from services.zbmath import zbmath_service

logger = logging.getLogger(__name__)

class UniversalProcessor:
    """Fast Pipeline for Metadata, ToC, and Index Keywords with high-quality AI prompts."""

    def __init__(self):
        self.ai = ai
        self.db = db

    def _get_library_folders(self) -> List[str]:
        """Returns a list of existing library folders for the AI to choose from."""
        folders = []
        try:
            # Look for top-level numeric folders
            for p in LIBRARY_ROOT.glob("[0-9]*"):
                if p.is_dir() and p.name not in IGNORED_FOLDERS:
                    folders.append(p.name)
                    # Also look one level deeper
                    for sub in p.glob("*"):
                        if sub.is_dir() and not sub.name.startswith(('.', '_')):
                            folders.append(f"{p.name}/{sub.name}")
            folders.sort()
        except: pass
        return folders

    def process_book(self, book_id: int, save_to_db: bool = True) -> Dict[str, Any]:
        with self.db.get_connection() as conn:
            book = conn.execute("SELECT id, path, title, author FROM books WHERE id = ?", (book_id,)).fetchone()
        if not book: return {"success": False, "error": "Book not found"}
        
        abs_path = LIBRARY_ROOT / book['path']
        handler = PDFHandler(abs_path)
        
        try:
            # 1. Extract Native MuPDF TOC as baseline
            native_toc = []
            if abs_path.suffix.lower() == '.pdf':
                try:
                    import fitz
                    doc = fitz.open(abs_path)
                    native_toc = doc.get_toc()
                    doc.close()
                except: pass

            ranges = handler.estimate_slicing_ranges()
            
            # Combine Front pages and potential Index pages
            combined_pages = sorted(list(set(ranges["metadata"] + ranges["bibliography"][-10:])))
            
            meta_slice = Path(f"/tmp/ms_fast_{book_id}.pdf")
            handler.create_slice(combined_pages, meta_slice)
            
            folders = self._get_library_folders()
            uploaded = self.ai.upload_file(meta_slice)
            
            # Short cooldown after upload to let Google's backend stabilize the file
            if uploaded:
                time.sleep(3)
                
            initial_json = self._initial_holistic_pass(uploaded, folders, native_toc)
            
            if uploaded: self.ai.delete_file(uploaded.name)
            if meta_slice.exists(): meta_slice.unlink()
            gc.collect()

            if not initial_json: return {"success": False, "error": "AI analysis failed"}

            # Phase 4 & 5: Verification & Reflection
            verification = zbmath_service.verify_metadata(initial_json.get('metadata', {}))
            conflicts = self._detect_conflicts(initial_json, verification, abs_path.name)
            
            final_data = initial_json
            if conflicts:
                handler.create_slice(ranges["metadata"], meta_slice)
                uploaded_ref = self.ai.upload_file(meta_slice)
                final_data = self._reflection_pass(uploaded_ref, initial_json, verification, conflicts)
                if uploaded_ref: self.ai.delete_file(uploaded_ref.name)
                if meta_slice.exists(): meta_slice.unlink()
                gc.collect()

            if save_to_db:
                self._save_to_db(book_id, final_data)
            
            return {"success": True, "data": final_data, "proposed": final_data.get('metadata')}

        except Exception as e:
            logger.error(f"Fast Pipeline failed: {e}")
            return {"success": False, "error": str(e)}

    def _initial_holistic_pass(self, file_obj, folders: List[str] = None, native_toc: List = None) -> Optional[Dict[str, Any]]:
        folder_list = "\n".join(folders) if folders else "No folders found."
        native_toc_str = json.dumps(native_toc[:100]) if native_toc else "None found."
        
        prompt = (
            "You are an expert mathematical librarian. Analyze the provided PDF (front matter and ToC).\n"
            "TASK: Extract high-fidelity metadata and a structured Table of Contents.\n"
            "TOC VERIFICATION: A baseline Table of Contents from PDF metadata is provided below. Use it to verify page numbers and titles, but prioritize what you see visually on the provided pages if there are discrepancies.\n"
            "SUMMARY: Write a sophisticated, one-to-two sentence academic summary capturing the pedagogical approach and key themes.\n"
            "DESCRIPTION: Provide a detailed professional review (2-3 paragraphs) for a research database.\n"
            "ROUTING: Select the best existing folder from the list below. Be CONSERVATIVE: prefer placing special cases into a broader existing category (e.g. '04_Algebra' for a book on Group Theory) rather than creating new folders. Only suggest a new sub-path (Format: 'ExistingFolder/NewSub') if the topic is distinct and warrants its own directory.\n"
            "TITLE: If the book is in German, ensure the German title is returned as the primary title. Do not translate it to English.\n"
            "Return a strictly valid JSON object: {\"metadata\": {\"title\", \"author\", \"publisher\", \"year\", \"isbn\", \"doi\", \"msc_class\", \"target_path\", \"summary\", \"description\", \"audience\", \"has_exercises\", \"has_solutions\", \"language\"}, \"toc\": [{\"title\", \"page\", \"level\"}], \"index_terms\": [], \"page_offset\": 0}\n\n"
            f"BASELINE TOC FROM PDF METADATA:\n{native_toc_str}\n\n"
            f"EXISTING FOLDERS:\n{folder_list}"
        )
        contents = [types.Content(role="user", parts=[
            types.Part.from_uri(file_uri=file_obj.uri, mime_type=file_obj.mime_type),
            types.Part.from_text(text=prompt)
        ])]
        return self.ai.generate_json(contents)

    def _detect_conflicts(self, initial_json, verification, filename) -> List[str]:
        conflicts = []
        meta = initial_json.get('metadata', {})
        if meta.get('title'):
            from rapidfuzz import fuzz
            if fuzz.partial_ratio(meta['title'].lower(), filename.lower()) < 40:
                conflicts.append("Title mismatch with filename")
        return conflicts

    def _reflection_pass(self, file_obj, initial_json, verification, conflicts) -> Dict[str, Any]:
        prompt = f"Resolve these metadata conflicts: {conflicts}. Registry data: {json.dumps(verification.get('master_data'))}. Return FINAL corrected JSON matching the schema."
        contents = [types.Content(role="user", parts=[
            types.Part.from_uri(file_uri=file_obj.uri, mime_type=file_obj.mime_type),
            types.Part.from_text(text=prompt)
        ])]
        return self.ai.generate_json(contents)

    def _save_to_db(self, book_id, final_data):
        meta = final_data.get('metadata', {})
        toc = final_data.get('toc', [])
        
        # Defensive conversion for author (might be list or dict from AI)
        author_val = meta.get('author')
        if isinstance(author_val, list):
            author_str = ", ".join([str(a) for a in author_val])
        else:
            author_str = str(author_val) if author_val else "Unknown"

        # Defensive conversion for index_terms
        index_terms = final_data.get('index_terms', [])
        if isinstance(index_terms, list):
            index_text = ", ".join([str(t) for t in index_terms])
        else:
            index_text = str(index_terms)

        with db.get_connection() as conn:
            conn.execute("""
                UPDATE books SET title=?, author=?, publisher=?, year=?, isbn=?, doi=?, 
                msc_class=?, summary=?, description=?, audience=?, has_exercises=?, 
                has_solutions=?, index_text=?, page_offset=?, language=?, last_metadata_refresh=unixepoch() WHERE id=?
            """, (
                meta.get('title'), author_str, meta.get('publisher'), meta.get('year'),
                meta.get('isbn'), meta.get('doi'), meta.get('msc_class'), meta.get('summary'),
                meta.get('description'), meta.get('audience'),
                1 if meta.get('has_exercises') else 0, 1 if meta.get('has_solutions') else 0,
                index_text, final_data.get('page_offset', 0), meta.get('language'), book_id
            ))
            
            # --- Push to Elasticsearch ---
            try:
                from core.search_engine import index_book
                import numpy as np
                
                # Fetch full state from DB for indexing
                book = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
                if book:
                    # Fetch TOC text
                    chapters = conn.execute("SELECT title FROM chapters WHERE book_id = ? ORDER BY page ASC", (book_id,)).fetchall()
                    toc_text = "\n".join([c['title'] for c in chapters])
                    
                    vector = None
                    if book['embedding']:
                        vector = list(np.frombuffer(book['embedding'], dtype=np.float32))

                    es_doc = {
                        "id": book['id'],
                        "title": book['title'],
                        "author": book['author'],
                        "summary": book['summary'],
                        "description": book['description'],
                        "msc_class": book['msc_class'],
                        "tags": book['tags'],
                        "zbl_id": book['zbl_id'],
                        "doi": book['doi'],
                        "isbn": book['isbn'],
                        "year": book['year'],
                        "publisher": book['publisher'],
                        "toc": toc_text,
                        "index_text": book['index_text'],
                        "zb_review": book['zb_review'],
                        "embedding": vector
                    }
                    index_book(es_doc)
            except Exception as e:
                logging.error(f"Failed to sync book {book_id} to ES: {e}")
            # -----------------------------

            conn.execute("DELETE FROM chapters WHERE book_id = ?", (book_id,))
            for item in toc:
                try:
                    p = item.get('page')
                    if p is not None:
                        conn.execute("INSERT INTO chapters (book_id, title, level, page) VALUES (?, ?, ?, ?)",
                                     (book_id, item['title'], item.get('level', 0), int(p) + final_data.get('page_offset', 0)))
                except: pass

universal_processor = UniversalProcessor()
