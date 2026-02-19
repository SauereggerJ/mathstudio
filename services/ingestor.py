import os
import json
import shutil
import time
import subprocess
from pathlib import Path
import fitz  # PyMuPDF
from core.database import db
from core.ai import ai
from core.config import LIBRARY_ROOT, GEMINI_MODEL, UNSORTED_DIR, DUPLICATES_DIR, IGNORED_FOLDERS
from services.library import library_service

class IngestorService:
    def __init__(self):
        self.db = db
        self.ai = ai

    def extract_structure(self, file_path):
        """Extracts text sample and page count with Vision fallback."""
        from core.config import get_api_key, GEMINI_MODEL
        try:
            if file_path.suffix.lower() == '.pdf':
                doc = fitz.open(file_path)
                page_count = doc.page_count
                
                # Try text layer first (skip initial empty pages to find TOC)
                text_pages = []
                found_content = False
                for i in range(min(50, page_count)): # Check up to first 50 pages
                    page_text = doc[i].get_text()
                    if len(page_text.strip()) > 200 or found_content:
                        text_pages.append(page_text)
                        found_content = True
                    if len(text_pages) >= 20: # Get 20 pages of actual content
                        break
                head_text = "".join(text_pages)
                
                # Vision fallback if text layer is empty
                if len(head_text.strip()) < 100:
                    print(f"[Ingestor] No text layer found for {file_path.name}, using OCR fallback.")
                    # We mark this for the AI analyzer
                    head_text = "[SCANNED DOCUMENT - NO TEXT LAYER]"
                
                toc = doc.get_toc()
                doc.close()
                return {'page_count': page_count, 'text_sample': head_text[:50000], 'toc': toc}
            
            elif file_path.suffix.lower() == '.djvu':
                result = subprocess.run(['djvutxt', str(file_path)], capture_output=True, text=True, check=True)
                pages = result.stdout.split('\f')
                return {
                    'page_count': len(pages), 
                    'text_sample': "".join(pages[:20])[:50000], 
                    'toc': []
                }
        except Exception as e:
            print(f"[Ingestor] Extraction error for {file_path.name}: {e}")
        return None

    def reprocess_book(self, book_id, ai_care=True):
        """Forces a re-ingestion of a specific book."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT path, author, title FROM books WHERE id = ?", (book_id,))
            result = cursor.fetchone()
            if not result: return {"success": False, "error": f"Book ID {book_id} not found."}
            
            db_path, old_author, old_title = result['path'], result['author'], result['title']
            full_path = LIBRARY_ROOT / db_path
            if not full_path.exists(): return {"success": False, "error": f"File not found: {db_path}"}

        print(f"Reprocessing book: {full_path.name} (AI Care: {ai_care})")
        try:
             structure = self.extract_structure(full_path)
             if not structure: return {"success": False, "error": "Failed to extract structure."}
             
             ai_data = self.analyze_book_content(structure.get('text_sample', ''), ai_care=ai_care, book_path=full_path)
             if not ai_data: return {"success": False, "error": "AI Analysis failed."}

             self.sync_chapters(book_id, ai_data.get('toc') or structure.get('toc', []), page_offset=ai_data.get('page_offset', 0))

             with self.db.get_connection() as conn:
                 cursor = conn.cursor()
                 cursor.execute("""
                     UPDATE books SET 
                         author = ?, title = ?, 
                         description = ?, summary = ?, 
                         page_count = ?, 
                         msc_class = ?, msc_code = ?,
                         audience = ?, publisher = ?,
                         year = ?, isbn = ?,
                         has_exercises = ?, has_solutions = ?, 
                         last_modified = ? 
                     WHERE id = ?
                 """, (
                     ai_data.get('author') or old_author, 
                     ai_data.get('title') or old_title,
                     ai_data.get('description') or '',
                     ai_data.get('summary') or '',
                     structure.get('page_count', 0),
                     ai_data.get('msc_class') or '',
                     ai_data.get('msc_class') or '',
                     ai_data.get('audience') or '',
                     ai_data.get('publisher') or '',
                     ai_data.get('year'),
                     ai_data.get('isbn') or '',
                     ai_data.get('has_exercises') or False,
                     ai_data.get('has_solutions') or False,
                     time.time(),
                     book_id
                 ))
                 # Sync FTS
                 cursor.execute("DELETE FROM books_fts WHERE rowid = ?", (book_id,))
                 cursor.execute("""
                     INSERT INTO books_fts (rowid, title, author, index_content)
                     SELECT id, title, author, index_text FROM books WHERE id = ?
                 """, (book_id,))
             
             return {"success": True, "message": f"Successfully re-indexed '{ai_data.get('title', old_title)}'", "data": ai_data}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def preview_reindex(self, book_id, ai_care=True):
        """Runs the AI analysis but does NOT save to database."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT path, author, title, publisher, year, isbn, msc_class, summary FROM books WHERE id = ?", (book_id,))
            result = cursor.fetchone()
            if not result: return {"success": False, "error": f"Book ID {book_id} not found."}
            
            db_path = result['path']
            full_path = LIBRARY_ROOT / db_path
            if not full_path.exists(): return {"success": False, "error": f"File not found: {db_path}"}
                 
        try:
             structure = self.extract_structure(full_path)
             if not structure: return {"success": False, "error": "Failed to extract structure."}
             
             text_sample = structure.get('text_sample', '')
             # Removed strict length check to allow Vision-based processing or partial text analysis

             ai_data = self.analyze_book_content(text_sample, ai_care=ai_care, book_path=full_path)
             if not ai_data: return {"success": False, "error": "AI Analysis failed."}

             return {
                 "success": True,
                 "current": dict(result),
                 "proposed": ai_data
             }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def sync_chapters(self, book_id, toc_data, page_offset=0):
        if not toc_data: return
        final_toc = []
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM chapters WHERE book_id = ?", (book_id,))
            for item in toc_data:
                title, page, level = None, None, 0
                if isinstance(item, dict):
                    title = item.get('title')
                    try:
                        p = item.get('page')
                        page = int(p) + page_offset if p is not None else None
                    except: page = None
                    level = item.get('level', 0)
                    item['pdf_page'] = page
                    final_toc.append(item)
                elif isinstance(item, list) and len(item) >= 2:
                    level = item[0] - 1 if isinstance(item[0], int) else 0
                    title, page = item[1], item[2] if len(item) > 2 else None
                    final_toc.append(item)
                if title:
                    cursor.execute("INSERT INTO chapters (book_id, title, level, page) VALUES (?, ?, ?, ?)", (book_id, str(title), level, page))
            cursor.execute("UPDATE books SET toc_json = ? WHERE id = ?", (json.dumps(final_toc), book_id))

    def analyze_book_content(self, text_sample, ai_care=False, book_path=None):
        care_instruction = "CRITICAL: This is a RE-INDEXING request. CLEAN everything thoroughly." if ai_care else ""
        
        if text_sample == "[SCANNED DOCUMENT - NO TEXT LAYER]" and book_path:
            # Vision path using direct SDK client access via self.ai.client
            try:
                from google.genai import types
                doc = fitz.open(str(book_path))
                parts = [
                    types.Part.from_text(text="You are a mathematical librarian. Analyze these images (title page and ToC) of a scanned book.\n"
                    "Return a JSON object with: title, author, publisher, year (int), isbn, description, summary, msc_class, audience, has_exercises, has_solutions, toc, page_offset.")
                ]
                for i in range(min(3, len(doc))):
                    pix = doc[i].get_pixmap(matrix=fitz.Matrix(2, 2))
                    parts.append(types.Part.from_bytes(data=pix.tobytes("jpeg"), mime_type="image/jpeg"))
                doc.close()
                
                response = self.ai.client.models.generate_content(
                    model=self.ai.model_name,
                    contents=types.Content(role="user", parts=parts),
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )
                return json.loads(response.text)
            except Exception as e:
                print(f"Vision analysis failed: {e}")

        prompt = (
            f"You are a librarian. Analyze this math book text sample.\n{care_instruction}\n"
            "Return a JSON object with: title, author, publisher, year (int), isbn, description, summary, msc_class, audience, has_exercises, has_solutions, toc, page_offset.\n"
            f"Text Sample:\n{text_sample[:50000]}"
        )
        return self.ai.generate_json(prompt)

    def analyze_content(self, structure, existing_folders=None, ai_care=False):
        """Uses AI to determine metadata and target path."""
        care_instruction = "CRITICAL: The previous metadata was poor, be extremely thorough." if ai_care else ""
        
        prompt = (
            "You are a mathematical librarian. Analyze this book fragment (ToC + Start).\n"
            f"{care_instruction}\n"
            "Return a strictly valid JSON object with these keys:\n"
            "- 'title', 'author', 'publisher', 'year' (int), 'isbn', 'msc_class' (e.g. 14A05),\n"
            "- 'target_path': Relative folder path from library root,\n"
            "- 'audience': ['Undergrad', 'Grad', 'Research', 'Popular'],\n"
            "- 'has_exercises', 'has_solutions' (booleans),\n"
            "- 'summary': One sentence summary,\n"
            "- 'description': Richer description,\n"
            "- 'toc': List of objects [{'title': '...', 'page': ...}],\n"
            "- 'page_offset': int (PDF page - Printed page)\n\n"
            f"TOC: {json.dumps(structure.get('toc', [])[:50])}\n"
            f"TEXT: {structure.get('text_sample', '')[:5000]}"
        )
        
        return self.ai.generate_json(prompt)

    def process_file(self, file_path, execute=False, dry_run=True):
        """Processes a single file from ingestion source."""
        print(f"Ingesting: {file_path.name}")
        file_hash = library_service.calculate_hash(file_path)
        
        # Duplicate check
        dup_type, dup_match = library_service.check_duplicate(file_hash)
        if dup_type == "HASH":
            return {"status": "duplicate", "type": "HASH", "match": dup_match}

        structure = self.extract_structure(file_path)
        if not structure:
            return {"status": "error", "message": "Structure extraction failed"}

        ai_data = self.analyze_content(structure)
        if not ai_data:
            return {"status": "error", "message": "AI analysis failed"}

        # Routing logic (Simplified for service)
        target_folder = ai_data.get('target_path') or "99_General_and_Diverse"
        safe_title = "".join(c for c in ai_data['title'] if c.isalnum() or c in " -_").strip()
        safe_author = "".join(c for c in ai_data.get('author', '') if c.isalnum() or c in " -_").strip()
        dest_name = f"{safe_author} - {safe_title}{file_path.suffix.lower()}"
        
        target_rel_path = Path(target_folder) / dest_name
        
        if execute:
            target_abs = LIBRARY_ROOT / target_rel_path
            target_abs.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(file_path, target_abs)
            
            # Save to DB
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO books (
                        filename, path, directory, author, title, publisher, year, isbn,
                        file_hash, toc_json, msc_class, audience, 
                        has_exercises, has_solutions, page_count, summary, description,
                        index_version, last_modified
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    dest_name, str(target_rel_path), str(target_rel_path.parent),
                    ai_data.get('author'), ai_data['title'], ai_data.get('publisher'),
                    ai_data.get('year'), ai_data.get('isbn'), file_hash,
                    json.dumps(ai_data.get('toc', [])), ai_data.get('msc_class'),
                    ai_data.get('audience'), ai_data.get('has_exercises', False),
                    ai_data.get('has_solutions', False), structure['page_count'],
                    ai_data.get('summary'), ai_data.get('description'),
                    1, time.time()
                ))
                
                # NEU: Wunschliste bereinigen, wenn DOI übereinstimmt
                if ai_data.get('doi'):
                    cursor.execute("UPDATE wishlist SET status = 'acquired' WHERE doi = ?", (ai_data['doi'],))
                    
            return {"status": "success", "path": str(target_rel_path)}
        
        return {"status": "plan", "target": str(target_rel_path), "metadata": ai_data}

# Global instance
ingestor_service = IngestorService()
