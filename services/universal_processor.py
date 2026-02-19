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
from core.config import LIBRARY_ROOT
from services.zbmath import zbmath_service

logger = logging.getLogger(__name__)

class UniversalProcessor:
    """Universal Processor with strict sequential I/O and exhaustive metadata extraction."""

    def __init__(self):
        self.ai = ai
        self.db = db

    def process_book(self, book_id: int) -> Dict[str, Any]:
        with self.db.get_connection() as conn:
            book = conn.execute("SELECT id, path, title, author FROM books WHERE id = ?", (book_id,)).fetchone()
        if not book: return {"success": False, "error": "Book not found"}
        
        abs_path = LIBRARY_ROOT / book['path']
        handler = PDFHandler(abs_path)
        
        try:
            ranges = handler.estimate_slicing_ranges()
            
            # Phase 3: Detailed Metadata Pass
            meta_slice = Path(f"/tmp/ms_meta_{book_id}.pdf")
            handler.create_slice(ranges["metadata"], meta_slice)
            
            print(f" -> Analyzing Metadata for Book {book_id}...", flush=True)
            uploaded_meta = self.ai.upload_file(meta_slice)
            initial_json = self._initial_holistic_pass(uploaded_meta)
            
            if uploaded_meta: self.ai.delete_file(uploaded_meta.name)
            if meta_slice.exists(): meta_slice.unlink()
            gc.collect()

            if not initial_json or 'metadata' not in initial_json: 
                return {"success": False, "error": "AI Metadata analysis failed to return structured data"}

            # Phase 3.5: Iterative Chunked Bib Scan
            full_bibliography = []
            bib_pages = ranges["bibliography"]
            chunk_size = 10 
            
            for i in range(0, len(bib_pages), chunk_size):
                chunk = bib_pages[i : i + chunk_size]
                chunk_slice = Path(f"/tmp/ms_bib_{book_id}_{i}.pdf")
                handler.create_slice(chunk, chunk_slice)
                
                print(f" -> Scanning Bibliography Chunk {i//chunk_size + 1}...", flush=True)
                uploaded_chunk = self.ai.upload_file(chunk_slice)
                if uploaded_chunk:
                    chunk_entries = self._scan_bibliography_chunk(uploaded_chunk)
                    if chunk_entries:
                        full_bibliography.extend(chunk_entries)
                    self.ai.delete_file(uploaded_chunk.name)
                
                if chunk_slice.exists(): chunk_slice.unlink()
                gc.collect()
                time.sleep(1)

            initial_json['bibliography'] = full_bibliography
            final_data = initial_json

            # Phase 4 & 5: Verification & Reflection
            verification = zbmath_service.verify_metadata(initial_json.get('metadata', {}))
            conflicts = self._detect_conflicts(initial_json, verification, abs_path.name)
            
            if conflicts:
                print(f" -> Conflicts detected: {conflicts}. Triggering Reflection...", flush=True)
                handler.create_slice(ranges["metadata"], meta_slice)
                uploaded_ref = self.ai.upload_file(meta_slice)
                final_data = self._reflection_pass(uploaded_ref, initial_json, verification, conflicts)
                final_data['bibliography'] = full_bibliography
                
                if uploaded_ref: self.ai.delete_file(uploaded_ref.name)
                if meta_slice.exists(): meta_slice.unlink()
                gc.collect()

            # Phase 6: Transactional Persistence
            self._save_to_db(book_id, final_data)
            return {"success": True, "count": len(full_bibliography), "data": final_data}

        except Exception as e:
            logger.error(f"Pipeline failed: {e}")
            return {"success": False, "error": str(e)}

    def _initial_holistic_pass(self, file_obj) -> Optional[Dict[str, Any]]:
        prompt = (
            "You are a mathematical librarian. Analyze the provided PDF (title pages and ToC).\n"
            "Extract book metadata and the structured Table of Contents.\n"
            "Return a strictly valid JSON object with this schema:\n"
            "{\n"
            "  \"metadata\": {\n"
            "    \"title\": \"Full official title\",\n"
            "    \"author\": \"Authors\",\n"
            "    \"publisher\": \"Publisher\",\n"
            "    \"year\": 2024,\n"
            "    \"isbn\": \"...\",\n"
            "    \"doi\": \"...\",\n"
            "    \"msc_class\": \"Primary MSC code (e.g. 81-01)\",\n"
            "    \"summary\": \"One sentence summary\",\n"
            "    \"description\": \"Detailed description\",\n"
            "    \"audience\": \"e.g. Graduate\",\n"
            "    \"has_exercises\": bool, \"has_solutions\": bool\n"
            "  },\n"
            "  \"toc\": [{\"title\": \"...\", \"page\": 1, \"level\": 0}],\n"
            "  \"page_offset\": 0\n"
            "}"
        )
        contents = [types.Content(role="user", parts=[
            types.Part.from_uri(file_uri=file_obj.uri, mime_type=file_obj.mime_type),
            types.Part.from_text(text=prompt)
        ])]
        return self.ai.generate_json(contents)

    def _scan_bibliography_chunk(self, file_obj) -> List[Dict]:
        prompt = (
            "EXTRACT EVERY SINGLE BIBLIOGRAPHY ENTRY from this PDF fragment.\n"
            "Do not skip any entries. Maintain exact mathematical notation.\n"
            "Return a JSON array: [{ \"title\", \"author\", \"year\", \"raw_text\" }]"
        )
        contents = [types.Content(role="user", parts=[
            types.Part.from_uri(file_uri=file_obj.uri, mime_type=file_obj.mime_type),
            types.Part.from_text(text=prompt)
        ])]
        return self.ai.generate_json(contents) or []

    def _detect_conflicts(self, initial_json, verification, filename) -> List[str]:
        conflicts = []
        meta = initial_json.get('metadata', {})
        master = verification.get('master_data', {})
        from rapidfuzz import fuzz
        
        # Check against filename (Local Anchor)
        if meta.get('title') and fuzz.partial_ratio(meta['title'].lower(), filename.lower()) < 40:
            conflicts.append(f"Title mismatch: AI='{meta['title']}' vs File='{filename}'")
        
        # Check against Registry (Global Anchor)
        if verification.get('verified') and master.get('title'):
            if fuzz.token_set_ratio(meta.get('title', ''), master['title']) < 70:
                conflicts.append(f"AI Title deviates from DOI-registry title '{master['title']}'")
        
        return conflicts

    def _reflection_pass(self, file_obj, initial_json, verification, conflicts) -> Dict[str, Any]:
        prompt = (
            "Perform a self-correction pass. Conflicts identified:\n" + "\n".join(conflicts) + "\n\n"
            "REGISTRY DATA: " + json.dumps(verification.get('master_data')) + "\n"
            "Re-analyze the PDF and return the FINAL corrected JSON matching the schema."
        )
        contents = [types.Content(role="user", parts=[
            types.Part.from_uri(file_uri=file_obj.uri, mime_type=file_obj.mime_type),
            types.Part.from_text(text=prompt)
        ])]
        return self.ai.generate_json(contents)

    def _save_to_db(self, book_id, final_data):
        meta = final_data.get('metadata', {})
        toc = final_data.get('toc', [])
        bib = final_data.get('bibliography', [])
        
        with db.get_connection() as conn:
            # 1. Update EVERY metadata field
            conn.execute("""
                UPDATE books SET 
                    title=?, author=?, publisher=?, year=?, isbn=?, doi=?, 
                    msc_class=?, summary=?, description=?, audience=?, 
                    has_exercises=?, has_solutions=?, last_modified=unixepoch() 
                WHERE id=?
            """, (
                meta.get('title'), meta.get('author'), meta.get('publisher'), meta.get('year'),
                meta.get('isbn'), meta.get('doi'), meta.get('msc_class'), meta.get('summary'),
                meta.get('description'), meta.get('audience'),
                1 if meta.get('has_exercises') else 0, 
                1 if meta.get('has_solutions') else 0,
                book_id
            ))
            
            # 2. Sync ToC
            conn.execute("DELETE FROM chapters WHERE book_id = ?", (book_id,))
            for item in toc:
                try:
                    pdf_p = int(item.get('page')) + final_data.get('page_offset', 0)
                    conn.execute("INSERT INTO chapters (book_id, title, level, page) VALUES (?, ?, ?, ?)",
                                 (book_id, item['title'], item.get('level', 0), pdf_p))
                except: pass

            # 3. Sync Bibliography
            conn.execute("DELETE FROM bib_entries WHERE book_id = ?", (book_id,))
            for entry in bib:
                if isinstance(entry, dict):
                    conn.execute("INSERT INTO bib_entries (book_id, raw_text, title, author) VALUES (?, ?, ?, ?)",
                        (book_id, entry.get('raw_text', ''), entry.get('title', ''), entry.get('author', '')))

universal_processor = UniversalProcessor()
