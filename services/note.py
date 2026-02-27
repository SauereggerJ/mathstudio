import datetime
import json
import os
import shutil
import io
import time
import subprocess
import logging
from pathlib import Path
from PIL import Image
import numpy as np
from google.genai import types
from core.database import db
from core.ai import ai
from core.config import LIBRARY_ROOT, CONVERTED_NOTES_DIR, OBSIDIAN_INBOX, NOTES_OUTPUT_DIR, EMBEDDING_MODEL, PROJECT_ROOT

logger = logging.getLogger(__name__)

class NoteService:
    def __init__(self):
        self.db = db
        self.ai = ai

    def optimize_image(self, image_bytes, max_size=2048):
        """Resizes and compresses image for API efficiency."""
        try:
            img = Image.open(io.BytesIO(image_bytes))
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            w, h = img.size
            if max(w, h) > max_size:
                scale = max_size / max(w, h)
                img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
            out_io = io.BytesIO()
            img.save(out_io, format="JPEG", quality=85, optimize=True)
            return out_io.getvalue()
        except Exception as e:
            print(f"[NoteService] Image optimization failed: {e}")
            return image_bytes

    def transcribe_note(self, image_data):
        """Uses Gemini Vision to transcribe handwritten notes to LaTeX/Markdown."""
        import tempfile
        from core.config import TEMP_UPLOADS_DIR
        
        optimized_data = self.optimize_image(image_data)
        
        # Save to temp file for File API upload
        temp_file_path = TEMP_UPLOADS_DIR / f"transcribe_{int(time.time())}.jpg"
        with open(temp_file_path, "wb") as f:
            f.write(optimized_data)
            
        prompt = (
            "You are a mathematical transcription expert. Convert this handwritten note into two formats:\n"
            "1. High-quality, clean LaTeX code for PDF generation.\n"
            "2. Obsidian-flavored Markdown for digital notes.\n\n"
            "Requirements:\n"
            "- **LaTeX**: Use standard amsmath environments. Expand abbreviations.\n"
            "- **Markdown**: Use $...$ for inline math and $$...$$ for block math. Include a YAML frontmatter.\n"
            "- **Output**: Return a JSON object with keys: 'latex_source', 'markdown_source', 'title', 'tags', 'msc'.\n"
            "IMPORTANT: Return ONLY the JSON object. Ensure all LaTeX backslashes are properly escaped within the JSON strings."
        )
        
        try:
            # 1. Upload to File API
            uploaded_file = self.ai.upload_file(temp_file_path)
            if not uploaded_file:
                return None
                
            # 2. Generate Content using URI
            contents = [
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(text=prompt),
                        types.Part.from_uri(file_uri=uploaded_file.uri, mime_type=uploaded_file.mime_type)
                    ]
                )
            ]
            
            data = self.ai.generate_json(contents)
            
            # 3. Cleanup
            self.ai.delete_file(uploaded_file.name)
            if temp_file_path.exists():
                temp_file_path.unlink()
                
            return data
        except Exception as e:
            logger.error(f"[NoteService] Transcription failed: {e}")
            if temp_file_path.exists():
                temp_file_path.unlink()
            return None

    def get_recommendations(self, text, limit=3):
        """Finds relevant books based on note content."""
        if not text: return []
        
        try:
            from google.genai import types
            res = self.ai.client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=[text[:9000]],
                config={"task_type": "RETRIEVAL_QUERY", "output_dimensionality": 768}
            )
            query_vec = np.array(res.embeddings[0].values, dtype=np.float32)
            
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, title, author, embedding FROM books WHERE embedding IS NOT NULL")
                rows = cursor.fetchall()
                
                candidates = []
                for r in rows:
                    if not r['embedding']: continue
                    vec = np.frombuffer(r['embedding'], dtype=np.float32)
                    if len(vec) == len(query_vec):
                        score = np.dot(vec, query_vec) / (np.linalg.norm(vec) * np.linalg.norm(query_vec))
                        if score > 0.4:
                            candidates.append({'id': r['id'], 'title': r['title'], 'author': r['author'], 'score': float(score)})
                
                candidates.sort(key=lambda x: x['score'], reverse=True)
                return candidates[:limit]
        except Exception as e:
            print(f"[NoteService] Recommendation failed: {e}")
            return []

    # --- CRUD: Notes Table ---

    def add_note(self, title, source_type, source_book_id=None, source_page_number=None,
                 latex_path=None, markdown_path=None, pdf_path=None, json_meta_path=None,
                 tags=None, msc=None, content_preview=None):
        """Adds a note record to the database and syncs FTS."""
        
        # Convert absolute paths to relative paths (relative to PROJECT_ROOT)
        def make_rel(p):
            if not p: return None
            try:
                path_obj = Path(p)
                if path_obj.is_absolute() and PROJECT_ROOT in path_obj.parents:
                    return str(path_obj.relative_to(PROJECT_ROOT))
                elif path_obj.is_absolute() and LIBRARY_ROOT in path_obj.parents:
                    # If it's in the library but outside mathstudio (unlikely for notes)
                    return str(path_obj.relative_to(LIBRARY_ROOT))
                return str(p)
            except:
                return str(p)

        rel_latex = make_rel(latex_path)
        rel_markdown = make_rel(markdown_path)
        rel_pdf = make_rel(pdf_path)
        rel_json = make_rel(json_meta_path)

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO notes (title, source_type, source_book_id, source_page_number,
                                  latex_path, markdown_path, pdf_path, json_meta_path, 
                                  tags, msc, content_preview)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (title, source_type, source_book_id, source_page_number,
                  rel_latex, rel_markdown, rel_pdf, rel_json,
                  tags, msc, content_preview))
            note_id = cursor.lastrowid
            
            # Sync FTS
            content = ""
            if markdown_path and Path(markdown_path).exists():
                try:
                    with open(markdown_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                except: pass
            
            conn.execute("INSERT INTO notes_fts (rowid, title, tags, content) VALUES (?, ?, ?, ?)",
                         (note_id, title, tags or "", content))
            
        return note_id

    def list_notes(self, source_type=None, book_id=None, limit=50):
        """Returns notes from the database, sorted by latest first."""
        query = "SELECT * FROM notes"
        params = []
        where = []
        if source_type:
            where.append("source_type = ?")
            params.append(source_type)
        if book_id:
            where.append("source_book_id = ?")
            params.append(book_id)
            
        if where:
            query += " WHERE " + " AND ".join(where)
            
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        with self.db.get_connection() as conn:
            return [dict(r) for r in conn.execute(query, params).fetchall()]

    def get_note(self, note_id):
        """Returns full note details from DB, including relations."""
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
            if not row: return None
            note = dict(row)
            
            # Resolve relative paths to absolute paths
            for path_key in ['latex_path', 'markdown_path', 'pdf_path', 'json_meta_path']:
                if note.get(path_key):
                    # Check if it's already absolute (legacy)
                    p = Path(note[path_key])
                    if not p.is_absolute():
                        note[path_key] = str((PROJECT_ROOT / p).resolve())
            
            # Fetch book details if applicable
            if note['source_book_id']:
                book = conn.execute("SELECT title, author FROM books WHERE id = ?", (note['source_book_id'],)).fetchone()
                if book:
                    note['book_title'] = book['title']
                    note['book_author'] = book['author']
            
            # Fetch relations
            relations = conn.execute("""
                SELECT n.id, n.title, r.relation_type
                FROM note_relations r
                JOIN notes n ON r.to_note_id = n.id
                WHERE r.from_note_id = ?
            """, (note_id,)).fetchall()
            note['related_notes'] = [dict(r) for r in relations]
            
            # Fetch book relations
            books = conn.execute("""
                SELECT b.id, b.title, b.author, b.path, r.page_number, r.relation_type
                FROM note_book_relations r
                JOIN books b ON r.book_id = b.id
                WHERE r.note_id = ?
                ORDER BY b.title ASC, r.page_number ASC
            """, (note_id,)).fetchall()
            note['referenced_books'] = [dict(b) for b in books]
            
            return note

    def add_book_relation(self, note_id, book_id, page_number=None, rel_type='references'):
        """Associates a note with a book and an optional page number."""
        with self.db.get_connection() as conn:
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO note_book_relations (note_id, book_id, page_number, relation_type)
                    VALUES (?, ?, ?, ?)
                """, (note_id, book_id, page_number, rel_type))
                return True
            except: return False

    def delete_book_relation(self, note_id, book_id, page_number=None):
        """Removes an association between a note and a book/page."""
        with self.db.get_connection() as conn:
            if page_number is not None:
                conn.execute("""
                    DELETE FROM note_book_relations 
                    WHERE note_id = ? AND book_id = ? AND page_number = ?
                """, (note_id, book_id, page_number))
            else:
                conn.execute("""
                    DELETE FROM note_book_relations 
                    WHERE note_id = ? AND book_id = ? AND page_number IS NULL
                """, (note_id, book_id))
        return True

    def update_note_metadata(self, note_id, data):
        """Updates title, tags, msc, etc."""
        allowed = {'title', 'tags', 'msc', 'content_preview'}
        updates = {k: v for k, v in data.items() if k in allowed}
        if not updates: return False
        
        updates['updated_at'] = int(datetime.datetime.now().timestamp())
        query = "UPDATE notes SET " + ", ".join(f"{k} = ?" for k in updates.keys())
        query += " WHERE id = ?"
        
        with self.db.get_connection() as conn:
            conn.execute(query, list(updates.values()) + [note_id])
            # Re-sync FTS
            note = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
            conn.execute("DELETE FROM notes_fts WHERE rowid = ?", (note_id,))
            
            # Get markdown content for FTS
            content = ""
            if note['markdown_path'] and os.path.exists(note['markdown_path']):
                try:
                    with open(note['markdown_path'], 'r', encoding='utf-8') as f:
                        content = f.read()
                except: pass
                
            conn.execute("INSERT INTO notes_fts (rowid, title, tags, content) VALUES (?, ?, ?, ?)",
                         (note_id, note['title'], note['tags'] or "", content))
        return True

    def update_note_content(self, note_id, markdown_content=None, latex_content=None):
        """Updates the physical MD/LaTeX files for a note and syncs FTS."""
        note = self.get_note(note_id)
        if not note: return False
        
        updated = False
        if markdown_content is not None and note.get('markdown_path'):
            try:
                with open(note['markdown_path'], 'w', encoding='utf-8') as f:
                    f.write(markdown_content)
                updated = True
            except Exception as e:
                logger.error(f"Failed to update markdown for note {note_id}: {e}")
                
        if latex_content is not None and note.get('latex_path'):
            try:
                with open(note['latex_path'], 'w', encoding='utf-8') as f:
                    f.write(latex_content)
                updated = True
            except Exception as e:
                logger.error(f"Failed to update latex for note {note_id}: {e}")
                
        if updated:
            # Re-sync FTS if markdown changed
            if markdown_content is not None:
                with self.db.get_connection() as conn:
                    conn.execute("UPDATE notes_fts SET content = ? WHERE rowid = ?", 
                                 (markdown_content, note_id))
            return True
        return False

    def get_tag_suggestions(self, prefix, limit=10):
        """Returns suggestions from existing tags and zbmath keywords."""
        suggestions = set()
        prefix = f"%{prefix}%"
        with self.db.get_connection() as conn:
            # 1. Existing note tags
            rows = conn.execute("SELECT tags FROM notes WHERE tags LIKE ?", (prefix,)).fetchall()
            for r in rows:
                if r['tags']:
                    for t in r['tags'].split(','):
                        t = t.strip()
                        if prefix[1:-1].lower() in t.lower():
                            suggestions.add(t)
            
            # 2. ZBMath keywords
            if len(suggestions) < limit:
                rows = conn.execute("SELECT keywords FROM zbmath_cache WHERE keywords LIKE ?", (prefix,)).fetchall()
                for r in rows:
                    if r['keywords']:
                        for k in r['keywords'].split(','):
                            k = k.strip()
                            if prefix[1:-1].lower() in k.lower():
                                suggestions.add(k)
                                
        return sorted(list(suggestions))[:limit]

    def add_relation(self, from_id, to_id, rel_type='related'):
        """Connects two notes."""
        if from_id == to_id: return False
        with self.db.get_connection() as conn:
            try:
                conn.execute("""
                    INSERT INTO note_relations (from_note_id, to_note_id, relation_type)
                    VALUES (?, ?, ?)
                """, (from_id, to_id, rel_type))
                # Symmetric? User usually expects undirected for 'related'
                conn.execute("""
                    INSERT OR IGNORE INTO note_relations (from_note_id, to_note_id, relation_type)
                    VALUES (?, ?, ?)
                """, (to_id, from_id, rel_type))
                return True
            except: return False

    def delete_relation(self, from_id, to_id):
        """Removes a connection."""
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM note_relations WHERE from_note_id = ? AND to_note_id = ?", (from_id, to_id))
            conn.execute("DELETE FROM note_relations WHERE from_note_id = ? AND to_note_id = ?", (to_id, from_id))
        return True

    def search_notes(self, query, limit=50):
        """FTS search over notes table."""
        with self.db.get_connection() as conn:
            rows = conn.execute("""
                SELECT n.*, f.rank
                FROM notes_fts f
                JOIN notes n ON f.rowid = n.id
                WHERE notes_fts MATCH ?
                ORDER BY rank LIMIT ?
            """, (query, limit)).fetchall()
            return [dict(r) for r in rows]

    def delete_note(self, note_id_or_name):
        """Deletes a note from DB, FTS, and removes associated files from disk.
           Accepts both integer ID and string filename/base_name."""
        if isinstance(note_id_or_name, int) or (isinstance(note_id_or_name, str) and note_id_or_name.isdigit()):
            note = self.get_note(int(note_id_or_name))
        else:
            # Try to find by path/filename
            with self.db.get_connection() as conn:
                row = conn.execute("""
                    SELECT * FROM notes 
                    WHERE latex_path LIKE ? OR markdown_path LIKE ? 
                    LIMIT 1
                """, (f"%{note_id_or_name}%", f"%{note_id_or_name}%")).fetchone()
                note = dict(row) if row else None

        if not note: return False

        # Physical file cleanup
        paths = [note.get('latex_path'), note.get('markdown_path'), 
                 note.get('pdf_path'), note.get('json_meta_path')]
        
        for p in paths:
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                    logger.info(f"Deleted file: {p}")
                except Exception as e:
                    logger.error(f"Failed to delete file {p}: {e}")

        # DB cleanup
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM notes WHERE id = ?", (note['id'],))
            conn.execute("DELETE FROM notes_fts WHERE rowid = ?", (note['id'],))
        return True

    # --- Legacy Compatibility & Extraction Logic ---

    def get_cached_page(self, book_id, page_number):
        """Checks if a page has already been extracted and returns its content and quality."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT latex_path, markdown_path, quality_score, quality_comments FROM extracted_pages WHERE book_id = ? AND page_number = ?",
                (book_id, page_number)
            )
            row = cursor.fetchone()
            
        if row:
            latex_path = Path(PROJECT_ROOT / row['latex_path'])
            markdown_path = Path(PROJECT_ROOT / row['markdown_path'])
            
            result = {
                'quality_score': row['quality_score'],
                'quality_comments': row['quality_comments']
            }
            
            if latex_path.exists():
                with open(latex_path, 'r', encoding='utf-8') as f:
                    result['latex'] = f.read()
            if markdown_path.exists():
                with open(markdown_path, 'r', encoding='utf-8') as f:
                    result['markdown'] = f.read()
            
            return result
        return None

    def save_page_to_cache(self, book_id, page_number, latex, markdown, quality_score=1.0, quality_comments=None):
        """Saves extracted page content to the structured repository and database with quality metrics."""
        book_dir = CONVERTED_NOTES_DIR / str(book_id)
        book_dir.mkdir(parents=True, exist_ok=True)
        
        latex_path = book_dir / f"page_{page_number}.tex"
        markdown_path = book_dir / f"page_{page_number}.md"
        
        with open(latex_path, 'w', encoding='utf-8') as f:
            f.write(latex)
        with open(markdown_path, 'w', encoding='utf-8') as f:
            f.write(markdown)
            
        # Store as relative paths
        rel_latex = str(latex_path.relative_to(PROJECT_ROOT))
        rel_markdown = str(markdown_path.relative_to(PROJECT_ROOT))

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO extracted_pages 
                (book_id, page_number, latex_path, markdown_path, quality_score, quality_comments, created_at)
                VALUES (?, ?, ?, ?, ?, ?, unixepoch())
            """, (book_id, page_number, rel_latex, rel_markdown, quality_score, quality_comments))

    def evaluate_latex_quality(self, latex_content, original_text_preview):
        """Uses Gemini to rate the quality of a LaTeX conversion."""
        prompt = f"""Evaluate the quality of the following mathematical LaTeX conversion against the raw OCR text.
Rate it on a scale from 0.0 to 1.0 (where 1.0 is perfect).
Consider:
- Mathematical accuracy
- Completeness
- Correct use of environments (amsmath, etc.)
- Handling of special symbols

RAW TEXT PREVIEW:
{original_text_preview}

LATEX CONTENT:
{latex_content}

Return a JSON object: {{"score": float, "comments": "brief explanation"}}
"""
        try:
            return self.ai.generate_json(prompt)
        except:
            return {"score": 0.5, "comments": "Evaluation failed"}

    def get_or_convert_pages(self, book_id, pages, force_refresh=False, min_quality=0.7):
        """Main pipeline: Reuse existing high-quality LaTeX or trigger new conversion.
        
        Always returns content for each page:
        - 'cache': high-quality LaTeX from previous conversion
        - 'ai_conversion': fresh LaTeX conversion (cached if quality >= min_quality)
        - 'text_fallback': raw text extraction (never cached) when AI fails
        
        Also creates KB proposals from any discovered theorems/definitions.
        """
        results = []
        
        with self.db.get_connection() as conn:
            book = conn.execute("SELECT path, title FROM books WHERE id = ?", (book_id,)).fetchone()
        if not book: return None, "Book not found"
        
        abs_path = (LIBRARY_ROOT / book['path']).resolve()
        import converter

        for page_num in pages:
            # 1. Try Cache
            cached = self.get_cached_page(book_id, page_num)
            
            if cached and not force_refresh:
                if cached.get('quality_score', 0) >= min_quality:
                    results.append({
                        'page': page_num,
                        'latex': cached.get('latex', ''),
                        'markdown': cached.get('markdown', ''),
                        'raw_text': None,
                        'quality': cached.get('quality_score'),
                        'source': 'cache'
                    })
                    continue

            # 2. Convert with retry
            result_data, error = None, None
            for attempt in range(2):
                logger.info(f"Converting Page {page_num} of Book {book_id} (attempt {attempt+1}/2, force={force_refresh})...")
                result_data, error = converter.convert_page(str(abs_path), page_num)
                if result_data is not None:
                    break  # Success
                if attempt == 0 and error:
                    logger.warning(f"Conversion attempt 1 failed for page {page_num}: {error}. Retrying in 2s...")
                    import time
                    time.sleep(2)
            
            # 3. If conversion failed after retry, fall back to raw text
            if error or result_data is None:
                logger.warning(f"AI conversion failed for page {page_num} after 2 attempts. Falling back to text extraction.")
                raw_text = converter.extract_raw_text(str(abs_path), page_num)
                results.append({
                    'page': page_num,
                    'latex': None,
                    'markdown': None,
                    'raw_text': raw_text or f"[Text extraction also failed for page {page_num}]",
                    'quality': 0.0,
                    'source': 'text_fallback'
                })
                continue
            
            latex = result_data.get('latex', '')
            markdown = result_data.get('markdown', '')
            raw_preview = result_data.get('raw_text', '')[:1000]
            discoveries = result_data.get('discoveries', [])
            
            # 4. Quality Check
            quality = self.evaluate_latex_quality(latex, raw_preview)
            q_score = quality.get('score', 0.5)
            q_comments = quality.get('comments', '')
            
            # 5. Save to Cache ONLY if quality is decent
            if q_score >= min_quality:
                self.save_page_to_cache(book_id, page_num, latex, markdown, q_score, q_comments)
                source_label = 'ai_conversion'
            else:
                logger.warning(f"Discarding low-quality conversion for Page {page_num} (Score: {q_score})")
                source_label = 'ai_conversion_discarded'
            
            # 6. Process theorem/definition discoveries into KB proposals
            if discoveries and q_score >= min_quality:
                self._create_proposals_from_discoveries(discoveries, book_id, page_num)
            
            results.append({
                'page': page_num,
                'latex': latex if q_score >= min_quality else None,
                'markdown': markdown if q_score >= min_quality else None,
                'raw_text': result_data.get('raw_text', '') if q_score < min_quality else None,
                'quality': q_score,
                'source': source_label,
                'comments': q_comments
            })
            
        return results, None

    def _create_proposals_from_discoveries(self, discoveries, book_id, page_number):
        """Creates KB proposals from theorem/definition discoveries found during LaTeX conversion.
        
        Fuzzy-matches against existing concepts to suggest merge targets.
        Skips if exact concept+book+page combo already exists in entries or proposals.
        """
        if not discoveries:
            return
        
        try:
            from rapidfuzz import fuzz
        except ImportError:
            logger.warning("rapidfuzz not installed, skipping proposal creation")
            return
        
        with self.db.get_connection() as conn:
            # Load all existing concept names for fuzzy matching
            existing_concepts = conn.execute("SELECT id, name FROM concepts").fetchall()
            concept_map = {c['name'].lower(): c['id'] for c in existing_concepts}
            concept_names = [(c['name'], c['id']) for c in existing_concepts]
            
            for disc in discoveries:
                if not isinstance(disc, dict):
                    continue
                name = disc.get('name', '').strip()
                kind = disc.get('kind', 'theorem').strip().lower()
                snippet = disc.get('snippet', '').strip()
                
                if not name or len(name) < 3:
                    continue
                
                # Valid kinds
                if kind not in {'definition', 'theorem', 'lemma', 'proposition', 'corollary', 'axiom'}:
                    kind = 'theorem'
                
                # Skip if exact concept+book+page already registered in entries
                existing_entry = conn.execute("""
                    SELECT e.id FROM entries e 
                    JOIN concepts c ON e.concept_id = c.id
                    WHERE LOWER(c.name) = ? AND e.book_id = ? AND e.page_start = ?
                """, (name.lower(), book_id, page_number)).fetchone()
                if existing_entry:
                    continue
                
                # Skip if already proposed for this exact book+page
                existing_proposal = conn.execute("""
                    SELECT id FROM kb_proposals 
                    WHERE LOWER(concept_name) = ? AND book_id = ? AND page_number = ? AND status != 'rejected'
                """, (name.lower(), book_id, page_number)).fetchone()
                if existing_proposal:
                    continue
                
                # Fuzzy match against existing concepts
                merge_target_id = None
                if name.lower() in concept_map:
                    # Exact match — suggest merge
                    merge_target_id = concept_map[name.lower()]
                else:
                    # Fuzzy match
                    best_score, best_id = 0, None
                    for cname, cid in concept_names:
                        score = fuzz.ratio(name.lower(), cname.lower())
                        if score > best_score and score >= 85:
                            best_score = score
                            best_id = cid
                    merge_target_id = best_id
                
                # Insert proposal
                conn.execute("""
                    INSERT INTO kb_proposals (concept_name, kind, snippet, book_id, page_number, merge_target_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (name, kind, snippet, book_id, page_number, merge_target_id))
                logger.info(f"KB proposal created: '{name}' ({kind}) from book {book_id} p.{page_number}"
                           + (f" [suggested merge with concept {merge_target_id}]" if merge_target_id else ""))

    def create_note_from_pdf(self, book_id, pages):
        """Converts PDF pages to structured notes, utilizing the cache and creating a Note record."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT path, title, author FROM books WHERE id = ?", (book_id,))
            res = cursor.fetchone()
            
        if not res: return None, "Book not found"
        
        rel_path, title, author = res['path'], res['title'], res['author']
        
        # Use the shared pipeline (which handles retry, caching, and proposal creation)
        page_results, convert_error = self.get_or_convert_pages(book_id, pages)
        
        if convert_error:
            return None, convert_error
        
        combined_markdown = ""
        combined_latex = ""
        
        for pr in page_results:
            page_num = pr.get('page')
            if pr.get('error'):
                combined_markdown += f"\n\n> [Error extracting Page {page_num}: {pr['error']}]\n\n"
                continue
            
            page_markdown = pr.get('markdown', '')
            page_latex = pr.get('latex', '')
            
            # Fall back to raw_text if no LaTeX/markdown available
            if not page_markdown and pr.get('raw_text'):
                page_markdown = pr['raw_text']
            if not page_latex and pr.get('raw_text'):
                page_latex = f"% Raw text fallback\n{pr['raw_text']}"

            combined_markdown += f"\n\n## Page {page_num}\n\n" + page_markdown
            combined_latex += f"\n% --- Page {page_num} ---\n" + page_latex

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        page_ref = f"p. {pages[0]}" if len(pages) == 1 else f"pp. {pages[0]}-{pages[-1]}"
        header = f"---\ntitle: Note from {title} ({page_ref})\nauthor: {author}\ndate: {timestamp}\ntags: [auto-note, {title}]\n---\n\n"
        full_markdown = header + combined_markdown
        
        # Save aggregate note
        safe_title = "".join(x for x in title if x.isalnum() or x in " -_")[:50]
        filename_base = f"{safe_title}_p{pages[0]}"
        if len(pages) > 1: filename_base += f"-{pages[-1]}"
        
        md_path = CONVERTED_NOTES_DIR / f"{filename_base}.md"
        tex_path = CONVERTED_NOTES_DIR / f"{filename_base}.tex"
        
        with open(md_path, 'w', encoding='utf-8') as f: f.write(full_markdown)
        # Also save TeX version for compilation
        with open(tex_path, 'w', encoding='utf-8') as f: 
            f.write("\\documentclass{article}\\usepackage{amsmath}\\begin{document}\n")
            f.write(combined_latex)
            f.write("\n\\end{document}")
            
        if OBSIDIAN_INBOX.exists():
            shutil.copy2(md_path, OBSIDIAN_INBOX / f"{filename_base}.md")
            
        # Create DB record
        self.add_note(
            title=f"Extraction: {title} ({page_ref})",
            source_type='book_extraction',
            source_book_id=book_id,
            source_page_number=pages[0],
            latex_path=tex_path,
            markdown_path=md_path,
            tags=f"extraction, {title}",
            content_preview=full_markdown[:500]
        )
            
        return {'filename': f"{filename_base}.md", 'content': full_markdown, 'path': str(md_path)}, None

    def get_note_metadata(self, base_name, directory):
        json_path = directory / f"{base_name}.json"
        if json_path.exists():
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else {}
            except: pass
        return {}

    def sync_filesystem_to_db(self):
        """Scans notes_output and converted_notes to backfill the database."""
        logger.info("Syncing filesystem notes to database...")
        count = 0
        
        # 1. Handwritten Notes (notes_output)
        if NOTES_OUTPUT_DIR.exists():
            for tex_file in NOTES_OUTPUT_DIR.glob("*.tex"):
                base = tex_file.stem
                # Check if already in DB
                with self.db.get_connection() as conn:
                    exists = conn.execute("SELECT 1 FROM notes WHERE latex_path LIKE ?", (f"%{base}.tex",)).fetchone()
                if exists: continue
                
                md_file = NOTES_OUTPUT_DIR / f"{base}.md"
                json_file = NOTES_OUTPUT_DIR / f"{base}.json"
                pdf_file = NOTES_OUTPUT_DIR / f"{base}.pdf"
                
                meta = self.get_note_metadata(base, NOTES_OUTPUT_DIR)
                title = meta.get('title', f"Handwritten {base}")
                tags = ", ".join(meta.get('tags', [])) if isinstance(meta.get('tags'), list) else meta.get('tags', 'handwritten')
                
                self.add_note(
                    title=title,
                    source_type='handwritten',
                    latex_path=tex_file,
                    markdown_path=md_file if md_file.exists() else None,
                    pdf_path=pdf_file if pdf_file.exists() else None,
                    json_meta_path=json_file if json_file.exists() else None,
                    tags=tags,
                    content_preview=None
                )
                count += 1

        # 2. PDF Extractions (converted_notes)
        if CONVERTED_NOTES_DIR.exists():
            for md_file in CONVERTED_NOTES_DIR.glob("*.md"):
                base = md_file.stem
                if base.startswith("page_"): continue # Skip raw page cache
                
                with self.db.get_connection() as conn:
                    exists = conn.execute("SELECT 1 FROM notes WHERE markdown_path LIKE ?", (f"%{base}.md",)).fetchone()
                if exists: continue
                
                tex_file = CONVERTED_NOTES_DIR / f"{base}.tex"
                pdf_file = CONVERTED_NOTES_DIR / f"{base}.pdf"
                
                # Heuristic: try to find book title from filename "Title_p123"
                title = base.replace("_", " ")
                book_id = None
                
                self.add_note(
                    title=f"Archived: {title}",
                    source_type='book_extraction',
                    markdown_path=md_file,
                    latex_path=tex_file if tex_file.exists() else None,
                    pdf_path=pdf_file if pdf_file.exists() else None,
                    tags="extraction, archive",
                    content_preview=None
                )
                count += 1
                
        return count

    def process_uploaded_note(self, transcription, image_data):
        """Saves transcription files and creates a DB record."""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        title = transcription.get('title', f"Handwritten {timestamp}")
        tags = transcription.get('tags', 'handwritten')
        if isinstance(tags, list): tags = ", ".join(tags)
        msc = transcription.get('msc', '')
        
        filename_base = f"note_{timestamp}"
        
        # Paths
        tex_path = NOTES_OUTPUT_DIR / f"{filename_base}.tex"
        md_path = NOTES_OUTPUT_DIR / f"{filename_base}.md"
        json_path = NOTES_OUTPUT_DIR / f"{filename_base}.json"
        img_path = NOTES_OUTPUT_DIR / f"{filename_base}.jpg"
        
        # Save Files
        latex_source = transcription.get('latex_source', '')
        with open(tex_path, 'w', encoding='utf-8') as f:
            if "\\documentclass" not in latex_source:
                f.write("\\documentclass{article}\n\\usepackage[utf8]{inputenc}\n\\usepackage{amsmath,amssymb,amsfonts}\n")
                f.write(f"\\title{{{title}}}\n\\begin{document}\n\\maketitle\n")
                f.write(latex_source)
                f.write("\n\\end{document}")
            else:
                f.write(latex_source)

        # Build Markdown Footer instead of Header
        markdown_body = transcription.get('markdown_source', '')
        
        # Defensive Cleanup: remove any AI-generated YAML or Title if it slipped through
        if markdown_body.startswith('---'):
            parts = markdown_body.split('---', 2)
            if len(parts) >= 3:
                markdown_body = parts[2].strip()
        
        # Remove repeated title if AI included it as # Header
        lines = markdown_body.split('\n')
        if lines and lines[0].strip().startswith('# ') and title.lower() in lines[0].lower():
            markdown_body = '\n'.join(lines[1:]).strip()

        full_md = f"# {title}\n\n{markdown_body}"
        full_md += "\n\n---\n### Document Metadata\n"
        full_md += f"- **Created**: {timestamp}\n"
        if msc: full_md += f"- **MSC Classification**: {msc}\n"
        if tags: full_md += f"- **Tags**: {tags}\n"
        full_md += "- **Source**: Handwritten Note Scan\n"

        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(full_md)
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(transcription, f, indent=2)
        with open(img_path, 'wb') as f:
            f.write(image_data)
            
        # Add to DB
        return self.add_note(
            title=title,
            source_type='handwritten',
            latex_path=tex_path,
            markdown_path=md_path,
            json_meta_path=json_path,
            tags=tags,
            msc=msc,
            content_preview=transcription.get('markdown_source', '')[:500]
        )

    def create_note(self, title, markdown_content, latex_content=None, tags=None, msc=None, source_book_id=None):
        """Creates a new note from text content, saves files, and records in DB."""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = "".join(x for x in title if x.isalnum() or x in " -_")[:50].strip()
        filename_base = f"note_{timestamp}_{safe_title.replace(' ', '_')}"
        
        # Paths
        tex_path = NOTES_OUTPUT_DIR / f"{filename_base}.tex"
        md_path = NOTES_OUTPUT_DIR / f"{filename_base}.md"
        
        # Build the Markdown Document with Metadata at the end
        # Defensive Cleanup: remove any AI-generated YAML or Title if it slipped through
        if markdown_content.startswith('---'):
            parts = markdown_content.split('---', 2)
            if len(parts) >= 3:
                markdown_content = parts[2].strip()
        
        # Remove repeated title if AI included it as # Header
        lines = markdown_content.split('\n')
        if lines and lines[0].strip().startswith('# ') and title.lower() in lines[0].lower():
            markdown_content = '\n'.join(lines[1:]).strip()

        full_md = f"# {title}\n\n"
        full_md += markdown_content
        full_md += "\n\n---\n### Document Metadata\n"
        full_md += f"- **Created**: {timestamp}\n"
        if msc: full_md += f"- **MSC Classification**: {msc}\n"
        if tags: full_md += f"- **Tags**: {tags}\n"
        
        if source_book_id:
            try:
                with self.db.get_connection() as conn:
                    book = conn.execute("SELECT title, author FROM books WHERE id = ?", (source_book_id,)).fetchone()
                    if book:
                        full_md += f"- **Source**: {book['title']} by {book['author']} (ID: {source_book_id})\n"
            except:
                full_md += f"- **Source Book ID**: {source_book_id}\n"

        # Save Files
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(full_md)
            
        if latex_content:
            with open(tex_path, 'w', encoding='utf-8') as f:
                # Wrap in minimal document if not provided
                if "\\documentclass" not in latex_content:
                    f.write("\\documentclass{article}\n\\usepackage{amsmath,amssymb,amsfonts}\n\\begin{document}\n")
                    f.write(latex_content)
                    f.write("\n\\end{document}")
                else:
                    f.write(latex_content)
        
        # Add to DB
        note_id = self.add_note(
            title=title,
            source_type='research_note',
            source_book_id=source_book_id,
            latex_path=tex_path if latex_content else None,
            markdown_path=md_path,
            tags=tags,
            content_preview=markdown_content[:500]
        )
        
        # Sync to Obsidian Inbox if it exists
        if OBSIDIAN_INBOX.exists():
            try:
                import shutil
                shutil.copy2(md_path, OBSIDIAN_INBOX / f"{filename_base}.md")
            except: pass
            
        return note_id

# Global instance
note_service = NoteService()
