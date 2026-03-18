import datetime
import json
import os
import shutil
import io
import time
import subprocess
import logging
import re
from pathlib import Path
from typing import List, Tuple
from PIL import Image
import numpy as np
from google.genai import types
import converter
from core.database import db
from core.ai import ai
from services.pipeline import pipeline_service
from core.config import LIBRARY_ROOT, CONVERTED_NOTES_DIR, NOTES_OUTPUT_DIR, EMBEDDING_MODEL, PROJECT_ROOT

logger = logging.getLogger(__name__)

class SectionalNoteService:
    def __init__(self, db):
        self.db = db

    def start_draft(self, session_id, title):
        with self.db.get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO note_drafts (session_id, title, sections_json)
                VALUES (?, ?, ?)
            """, (session_id, title, json.dumps([])))
        return True

    def append_section(self, session_id, section_content):
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT sections_json FROM note_drafts WHERE session_id = ?", (session_id,)).fetchone()
            if not row: return False
            sections = json.loads(row[0])
            sections.append(section_content)
            conn.execute("UPDATE note_drafts SET sections_json = ? WHERE session_id = ?", (json.dumps(sections), session_id))
        return True

    def finalize_draft(self, session_id, note_service_instance):
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT title, sections_json FROM note_drafts WHERE session_id = ?", (session_id,)).fetchone()
            if not row: return None
            
            title = row['title']
            sections = json.loads(row['sections_json'])
            
        # Combine sections
        full_content = "\n\n".join(sections)
        
        # In this new era, we generate ONE source (LaTeX) and ensure MD is derived or identical
        # For now, we'll use the existing create_note logic but with unified content
        note_id = note_service_instance.create_note(
            title=title,
            markdown_content=full_content,
            latex_content=full_content, # Unified
            tags="agentic-research"
        )
        
        # Cleanup
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM note_drafts WHERE session_id = ?", (session_id,))
            
        return note_id

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

    def is_toc_artifact(self, latex: str) -> bool:
        """Heuristic to detect if a LaTeX snippet is actually a Table of Contents entry."""
        if not latex: return False
        # 1. Look for sequences of dots or \dotfill (classic TOC breadcrumbs)
        if "....." in latex or ". . . . ." in latex or "\\dotfill" in latex or "\\hspace" in latex:
            return True
        # 2. Look for high density of dots combined with numbers at end of lines
        lines = latex.split('\n')
        toc_lines = 0
        for line in lines:
            line = line.strip()
            if not line: continue
            # If line ends with a number and has many dots or \dotfill
            if (re.search(r'\d+$', line) or line.endswith('.')) and (line.count('.') > 5 or "\\dotfill" in line):
                toc_lines += 1
        
        if len(lines) > 0 and (toc_lines / len(lines)) > 0.3:
            return True
        return False

    def is_ai_meta_discussion(self, latex: str) -> bool:
        """Detects if a LaTeX snippet contains internal AI repair or reflection text."""
        if not latex: return False
        markers = [
            "(Note:", "I will use", "Failed LaTeX", "Repaired (c)", "Original Text",
            "I'll try to match", "the original text", "I will fix", "repair attempt"
        ]
        count = 0
        for marker in markers:
            if marker.lower() in latex.lower():
                count += 1
        return count >= 2 or "(Note:" in latex  # (Note: is a very strong indicator)

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
            "TRIGGER DETECTION:\n"
            "Look at the bottom-right corner of the image for a single, possibly circled, uppercase letter: 'G', 'B', or 'S'.\n"
            "- 'G' (default): Grading mode.\n"
            "- 'B': Blank mode (transcription only).\n"
            "- 'S': Solve mode (solve the exercise).\n\n"
            "Requirements:\n"
            "- **LaTeX**: Use standard amsmath environments. Expand abbreviations.\n"
            "- **Markdown**: Use $...$ for inline math and $$...$$ for block math. Include a YAML frontmatter.\n"
            "- **Output**: Return a JSON object with keys: 'latex_source', 'markdown_source', 'title', 'tags', 'msc', 'trigger_mode'.\n"
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

    def lint_latex(self, latex_code: str) -> List[str]:
        """Performs fast local structural analysis of LaTeX code to catch common AI hallucination errors."""
        if not latex_code: return ["Empty LaTeX code"]
        errors = []
        import re

        # 1. Check for matching \begin and \end
        begins = re.findall(r'\\begin\{([^}]+)\}', latex_code)
        ends = re.findall(r'\\end\{([^}]+)\}', latex_code)
        if len(begins) != len(ends):
            errors.append(f"Mismatched environment counts: {len(begins)} begins vs {len(ends)} ends")
        else:
            # Check order/nesting roughly
            stack = []
            for match in re.finditer(r'\\(begin|end)\{([^}]+)\}', latex_code):
                tag_type, env_name = match.groups()
                if tag_type == 'begin':
                    stack.append(env_name)
                else:
                    if not stack:
                        errors.append(f"Unmatched \\end{{{env_name}}}")
                    else:
                        last = stack.pop()
                        if last != env_name:
                            errors.append(f"Environment nesting error: expected \\end{{{last}}}, found \\end{{{env_name}}}")
            if stack:
                errors.append(f"Unclosed environments remaining: {', '.join(stack)}")

        # 2. Advanced Brace Matching (ignoring escaped braces)
        # Strip escaped braces \{ and \} to count actual logical groups
        stripped_code = re.sub(r'\\\\', '', latex_code) # remove literal backslashes
        stripped_code = re.sub(r'\\\{', '', stripped_code)
        stripped_code = re.sub(r'\\\}', '', stripped_code)
        
        open_braces = stripped_code.count('{')
        close_braces = stripped_code.count('}')
        if open_braces != close_braces:
            errors.append(f"Mismatched curly braces: {open_braces} opening vs {close_braces} closing")
            
        # 3. Inline Math Delimiter Checking ($ ... $)
        # Remove literal \$ so they don't mess up counts
        stripped_dollar = re.sub(r'\\\$', '', latex_code)
        # Remove block math $$ so we only count isolated $
        stripped_dollar = re.sub(r'\$\$', '', stripped_dollar)
        
        dollar_count = stripped_dollar.count('$')
        if dollar_count % 2 != 0:
            errors.append(f"Unbalanced inline math decorators ($ sign count is odd: {dollar_count})")

        # 4. Check for common unescaped characters in text mode
        # (Very heuristic, ignore inside math mode or comments)
        raw_ampersands = re.findall(r'(?<!\\)&', latex_code)
        if raw_ampersands:
            math_envs = ['tabular', 'matrix', 'align', 'gather', 'split', 'cases', 'aligned', 'array', 'multline', 'eqnarray', 'bmatrix', 'pmatrix', 'vmatrix', 'Vmatrix']
            if not any(env in latex_code for env in math_envs):
                errors.append(f"Found {len(raw_ampersands)} potential unescaped ampersands outside tabular/matrix environments")

        return errors

    def verify_compilation(self, latex_snippet: str) -> Tuple[bool, str]:
        """Attempts to compile a LaTeX snippet using pdflatex."""
        import tempfile
        from core.config import TEMP_UPLOADS_DIR
        
        # Wrap snippet in an article with comprehensive math support
        full_doc = [
            "\\documentclass{article}",
            "\\usepackage[utf8]{inputenc}",
            "\\usepackage{amsmath,amssymb,amsfonts,amsthm,mathrsfs,mathtools}",
            "\\newtheorem{theorem}{Theorem}[section]",
            "\\newtheorem{lemma}[theorem]{Lemma}",
            "\\newtheorem{proposition}[theorem]{Proposition}",
            "\\newtheorem{corollary}[theorem]{Corollary}",
            "\\newtheorem{definition}[theorem]{Definition}",
            "\\newtheorem{remark}[theorem]{Remark}",
            "\\newtheorem{example}[theorem]{Example}",
            "\\newtheorem{exercise}[theorem]{Exercise}",
            "\\pagestyle{empty}",
            "\\begin{document}",
            latex_snippet,
            "\\end{document}"
        ]
        doc_str = "\n".join(full_doc)
        
        with tempfile.TemporaryDirectory(dir=TEMP_UPLOADS_DIR) as tmpdir:
            tmp_path = Path(tmpdir)
            tex_file = tmp_path / "test.tex"
            tex_file.write_text(doc_str, encoding='utf-8')
            
            try:
                result = subprocess.run(
                    ['pdflatex', '-interaction=nonstopmode', '-halt-on-error', 'test.tex'],
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    timeout=15
                )
                if result.returncode == 0:
                    return True, ""
                else:
                    # Extract last few lines of error
                    return False, result.stdout[-500:]
            except subprocess.TimeoutExpired:
                return False, "Compilation timed out"
            except Exception as e:
                return False, str(e)

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
                 tags=None, msc=None, content_preview=None, processing_mode='B'):
        """Adds a note record to the database and syncs FTS."""
        
        # Convert absolute paths to relative paths (relative to PROJECT_ROOT)
        def make_rel(p):
            if not p: return None
            try:
                p_str = str(p)
                path_obj = Path(p)
                
                # If already relative, just return it
                if not path_obj.is_absolute():
                    return p_str
                
                # 1. Try relativizing to PROJECT_ROOT
                if path_obj.is_relative_to(PROJECT_ROOT):
                    return str(path_obj.relative_to(PROJECT_ROOT))
                
                # 2. Try relativizing to LIBRARY_ROOT
                if path_obj.is_relative_to(LIBRARY_ROOT):
                    return str(path_obj.relative_to(LIBRARY_ROOT))
                
                # 3. Fallback: if it's absolute but contains 'mathstudio', truncate to that
                if 'mathstudio' in p_str:
                    parts = path_obj.parts
                    idx = parts.index('mathstudio')
                    return str(Path(*parts[idx+1:]))
                
                return p_str
            except Exception:
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
                                  tags, msc, content_preview, processing_mode)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (title, source_type, source_book_id, source_page_number,
                  rel_latex, rel_markdown, rel_pdf, rel_json,
                  tags, msc, content_preview, processing_mode))
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
                val = note.get(path_key)
                if not val: continue
                
                p = Path(val)
                if p.is_absolute():
                    # If absolute but doesn't exist, it might be a host path in a container
                    if not p.exists() and 'mathstudio' in val:
                        parts = p.parts
                        if 'mathstudio' in parts:
                            idx = parts.index('mathstudio')
                            rel_p = Path(*parts[idx+1:])
                            note[path_key] = str((PROJECT_ROOT / rel_p).resolve())
                else:
                    # Relative path, expand it
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
        allowed = {'title', 'tags', 'msc', 'content_preview', 'processing_mode'}
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
            cached = {
                'page': page_number,
                'latex': '',
                'markdown': '',
                'raw_text': None,
                'quality_score': row['quality_score'],
                'comments': row['quality_comments']
            }
            
            if row['latex_path']:
                full_tex = PROJECT_ROOT / row['latex_path']
                if full_tex.exists():
                    with open(full_tex, 'r', encoding='utf-8') as f:
                        cached['latex'] = f.read()
            
            return cached
        return None

    def save_page_to_cache(self, book_id, page_number, latex, markdown, quality_score=1.0, quality_comments=None):
        """Saves extracted page content to the structured repository and database with quality metrics."""
        book_dir = CONVERTED_NOTES_DIR / str(book_id)
        book_dir.mkdir(parents=True, exist_ok=True)
        
        latex_path = book_dir / f"page_{page_number}.tex"
        markdown_path = book_dir / f"page_{page_number}.md"
        
        with open(latex_path, 'w', encoding='utf-8') as f:
            f.write(latex)
            
        # Store as relative paths
        rel_latex = str(latex_path.relative_to(PROJECT_ROOT))
        rel_markdown = None # Markdown is deprecated for individual pages

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO extracted_pages 
                (book_id, page_number, latex_path, markdown_path, quality_score, quality_comments, created_at)
                VALUES (?, ?, ?, ?, ?, ?, unixepoch())
            """, (book_id, page_number, rel_latex, rel_markdown, quality_score, quality_comments))
            
            # Sync to extracted_pages_fts for full-text search over LaTeX content
            row = conn.execute(
                "SELECT id FROM extracted_pages WHERE book_id = ? AND page_number = ?",
                (book_id, page_number)
            ).fetchone()
            if row:
                # Delete existing FTS entry if any, then insert fresh
                conn.execute("DELETE FROM extracted_pages_fts WHERE rowid = ?", (row['id'],))
                conn.execute(
                    "INSERT INTO extracted_pages_fts (rowid, book_id, page_number, latex_content) VALUES (?, ?, ?, ?)",
                    (row['id'], book_id, page_number, latex)
                )

    # evaluate_latex_quality removed in favor of converter.repair_latex

    def backfill_latex_fts(self):
        """One-time migration: populate extracted_pages_fts from existing .tex files on disk."""
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT id, book_id, page_number, latex_path FROM extracted_pages"
            ).fetchall()
        
        count = 0
        for row in rows:
            latex_path = row['latex_path']
            if not latex_path:
                continue
            
            # Resolve relative path
            abs_path = PROJECT_ROOT / latex_path
            if not abs_path.exists():
                continue
            
            try:
                latex = abs_path.read_text(encoding='utf-8')
                with self.db.get_connection() as conn:
                    # Check if already indexed
                    existing = conn.execute(
                        "SELECT rowid FROM extracted_pages_fts WHERE rowid = ?", (row['id'],)
                    ).fetchone()
                    if not existing:
                        conn.execute(
                            "INSERT INTO extracted_pages_fts (rowid, book_id, page_number, latex_content) VALUES (?, ?, ?, ?)",
                            (row['id'], row['book_id'], row['page_number'], latex)
                        )
                        count += 1
            except Exception as e:
                logger.warning(f"Failed to backfill FTS for page {row['page_number']} of book {row['book_id']}: {e}")
        
        logger.info(f"Backfilled {count} pages into extracted_pages_fts")
        return count

    def get_context_window_latex(self, book_id, target_page, window_size_before=2, window_size_after=4):
        """Retrieves and concatenates LaTeX from a window of pages for context."""
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT page_count FROM books WHERE id = ?", (book_id,)).fetchone()
            if not row: return ""
            total_pages = row['page_count']

        start = max(1, target_page - window_size_before)
        end = min(total_pages, target_page + window_size_after)
        window_pages = list(range(start, end + 1))

        # Ensure all pages in window are digitized
        results, error = self.get_or_convert_pages(book_id, window_pages)
        if error:
            logger.error(f"Failed to digitize context window: {error}")
            return ""

        full_context = ""
        for pr in results:
            p_num = pr.get('page')
            p_latex = pr.get('latex') or f"% [Page {p_num} LaTeX missing/failed]"
            # Fix literal \n strings that AI sometimes returns
            p_latex = p_latex.replace('\\n', '\n')
            full_context += f"\n\n% --- PAGE {p_num} ---\n\n{p_latex}"
        
        return full_context

    def extract_and_save_knowledge_terms_batch(self, book_id, pages_list, window_buffer=2, force=False):
        """
        Performs contextual extraction for a batch of pages by grouping them into chunks 
        (e.g., 5 pages) to optimize token usage and avoid redundant API calls.
        Saves discovered terms to the knowledge_terms database.
        E7: force flag allows re-extraction even if terms already exist.
        """
        if not pages_list:
            return 0, "No pages provided"
            
        pages_list = sorted(pages_list)
        total_count = 0
        chunk_size = 5
        
        # Fetch metadata to help AI with descriptive naming
        with self.db.get_connection() as conn:
            book = conn.execute("SELECT title, author FROM books WHERE id = ?", (book_id,)).fetchone()
        metadata = dict(book) if book else None

        for i in range(0, len(pages_list), chunk_size):
            chunk = pages_list[i:i + chunk_size]
            start_page = chunk[0]
            end_page = chunk[-1]
            
            # E5: Skip re-extraction pre-check
            if not force:
                with self.db.get_connection() as conn:
                    existing = conn.execute(
                        "SELECT COUNT(*) FROM knowledge_terms WHERE book_id = ? AND page_start BETWEEN ? AND ?",
                        (book_id, start_page, end_page)
                    ).fetchone()[0]
                if existing > 0:
                    logger.info(f"Skipping term extraction for pages {start_page}-{end_page}: {existing} terms already exist (use force=True to override)")
                    continue
            
            fetch_start = max(1, start_page - window_buffer)
            fetch_end = end_page + window_buffer
            
            context_pages = list(range(fetch_start, fetch_end + 1))
            
            results, _ = self.get_or_convert_pages(book_id, context_pages, abort_on_failure=False)
            
            context_latex = ""
            for pr in results:
                p_num = pr.get('page')
                p_latex = pr.get('latex') or f"% [Page {p_num} LaTeX missing/failed]"
                p_latex = p_latex.replace('\\n', '\n')
                context_latex += f"\n\n% --- PAGE {p_num} ---\n\n{p_latex}"

            if not context_latex.strip():
                logger.warning(f"No LaTeX context found for batch {start_page}-{end_page}")
                continue
            
            # Cooldown between extraction calls to prevent API overload
            if i > 0:
                time.sleep(2)
                
            terms, error = converter.extract_terms_batch(context_latex, start_page, end_page, metadata=metadata)
            if error:
                logger.error(f"Batch extraction failed for {start_page}-{end_page}: {error}")
                continue
                
            for t in terms:
                # The AI now returns 'page_start' but if missing, fallback to start_page
                term_start = t.get('page_start', start_page)
                if self._save_knowledge_term(book_id, term_start, t):
                    total_count += 1
            
            # Mark pages in this chunk as harvested
            with self.db.get_connection() as conn:
                placeholders = ','.join(['?'] * len(chunk))
                conn.execute(f"""
                    UPDATE extracted_pages SET harvested_at = unixepoch()
                    WHERE book_id = ? AND page_number IN ({placeholders})
                """, [book_id] + chunk)
                    
        return total_count, None

    def check_and_trigger_term_extraction(self, book_id):
        """E6: Smart extraction scheduling — checks if contiguous cached pages 
        exist that haven't been term-extracted yet (harvested_at IS NULL), 
        and triggers extraction if so. Respects book content bounds."""
        with self.db.get_connection() as conn:
            book = conn.execute("""
                SELECT content_start_page, content_end_page FROM books WHERE id = ?
            """, (book_id,)).fetchone()
            
            # Find all cached pages with sufficient quality that HAVEN'T been harvested
            query = """
                SELECT page_number FROM extracted_pages 
                WHERE book_id = ? AND (quality_score >= 0.7 OR quality_score IS NULL) AND harvested_at IS NULL
            """
            params = [book_id]
            
            if book:
                if book['content_start_page']:
                    query += " AND page_number >= ?"
                    params.append(book['content_start_page'])
                if book['content_end_page']:
                    query += " AND page_number <= ?"
                    params.append(book['content_end_page'])
            
            query += " ORDER BY page_number"
            rows = conn.execute(query, params).fetchall()
        
        if not rows:
            return 0, "No pending cached pages found"
        
        pending_pages = sorted(r['page_number'] for r in rows)
        
        # Find contiguous blocks of ≥5 pages (to make chunking efficient)
        blocks = []
        if not pending_pages: return 0, "No pending pages"
        
        block_start = pending_pages[0]
        prev = pending_pages[0]
        for p in pending_pages[1:]:
            if p == prev + 1:
                prev = p
            else:
                if prev - block_start + 1 >= 5:
                    blocks.append((block_start, prev))
                block_start = p
                prev = p
        if prev - block_start + 1 >= 5:
            blocks.append((block_start, prev))
        
        if not blocks:
            # If no 5-page blocks, check if there's any pending at all and maybe take a smaller set
            if len(pending_pages) > 0:
                blocks.append((pending_pages[0], pending_pages[-1]))
            else:
                return 0, "No contiguous blocks found"
        
        total = 0
        for bs, be in blocks:
            logger.info(f"Auto-triggering term extraction for pages {bs}-{be} of book {book_id}")
            # We take up to 25 pages at a time to not blow up the chunking
            target_list = [p for p in pending_pages if bs <= p <= min(be, bs + 25)]
            count, _ = self.extract_and_save_knowledge_terms_batch(
                book_id, target_list, force=True # force=True because we KNOW they are pending via harvested_at
            )
            total += count
            break  # One block at a time to avoid overload
        
        return total, None

    def _extract_snippet_from_cache(self, book_id, page_start, start_marker, end_marker=None):
        """Extract LaTeX between markers from cached page content on disk."""
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT latex_path FROM extracted_pages WHERE book_id = ? AND page_number = ?",
                (book_id, page_start)
            ).fetchone()
        if not row or not row['latex_path']:
            return None
        
        abs_path = PROJECT_ROOT / row['latex_path']
        if not abs_path.exists():
            return None
        
        try:
            latex = abs_path.read_text(encoding='utf-8')
        except Exception:
            return None
        
        from rapidfuzz import fuzz
        
        def find_best_match_index(text, marker, is_end=False):
            if not marker: return -1
            # First try exact match
            idx = text.find(marker)
            if idx != -1: return idx
            
            # Try lower
            idx = text.lower().find(marker.lower())
            if idx != -1: return idx
            
            # Try removing common LaTeX formatting like \textbf{}, \textit{}, etc.
            import re
            clean_text = re.sub(r'\\[a-z]+\{([^}]*)\}', r'\1', text)
            clean_marker = re.sub(r'\\[a-z]+\{([^}]*)\}', r'\1', marker)
            
            # Normalize spacing and math $ symbols
            def normalize(s):
                s = s.replace('$', '').replace('\\', '').replace('{', '').replace('}', '')
                return re.sub(r'\s+', ' ', s).strip().lower()
                
            norm_text = normalize(text)
            norm_marker = normalize(marker)
            
            idx = norm_text.find(norm_marker)
            if idx != -1:
                # Approximate the index back in original text by searching for the first 8 non-space chars
                first_chars = re.sub(r'\s+', '', norm_marker)[:8]
                if not first_chars: return -1
                
                # Search for these chars in the original text, ignoring non-alphanumeric
                for i in range(len(text) - 8):
                    if re.sub(r'[^a-zA-Z0-9]', '', text[i:i+30]).lower().startswith(first_chars):
                        return i
            
            # Fallback to sliding window fuzzy search with a larger window for LaTeX noise
            window_size = len(marker) + 40
            best_ratio = 0
            best_idx = -1
            for i in range(0, len(text) - len(marker), 5): # Step by 5 for speed
                window = text[i:i+window_size]
                ratio = fuzz.partial_ratio(marker.lower(), window.lower())
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_idx = i
                    
            if best_ratio > 85:
                return best_idx
            return -1

        start_idx = find_best_match_index(latex, start_marker)
        if start_idx == -1:
            logger.warning(f"Start marker '{start_marker}' not found in page {page_start}")
            return None
        
        if end_marker:
            # Search for end marker on current and subsequent pages (up to 2 pages forward)
            def get_page_latex(p_num):
                with self.db.get_connection() as conn:
                    row = conn.execute(
                        "SELECT latex_path FROM extracted_pages WHERE book_id = ? AND page_number = ?",
                        (book_id, p_num)
                    ).fetchone()
                if not row or not row['latex_path']: return None
                abs_path = PROJECT_ROOT / row['latex_path']
                if not abs_path.exists(): return None
                try: return abs_path.read_text(encoding='utf-8')
                except Exception: return None

            accumulated_latex = latex
            for p_offset in range(0, 3): # Check p, p+1, p+2
                p_num = page_start + p_offset
                p_latex = get_page_latex(p_num) if p_offset > 0 else latex
                if not p_latex: break
                
                if p_offset > 0:
                    accumulated_latex += f"\n\n% --- PAGE {p_num} ---\n\n" + p_latex
                    search_text = p_latex
                else:
                    search_text = p_latex[start_idx + len(start_marker):]
                
                rel_end_idx = find_best_match_index(search_text, end_marker, is_end=True)
                if rel_end_idx != -1:
                    if p_offset == 0:
                        return latex[start_idx : start_idx + len(start_marker) + rel_end_idx]
                    else:
                        base_len = len(accumulated_latex) - len(p_latex)
                        return accumulated_latex[:base_len + rel_end_idx]
            return accumulated_latex
        
        return latex[start_idx:]

    def _save_knowledge_term(self, book_id, page_start, term_data):
        """Saves a single extracted term to the flat database table with deduplication.
        Uses the marker system to extract LaTeX snippets from the local cache."""
        name = term_data.get('name')
        t_type = term_data.get('type', 'theorem')
        keywords = term_data.get('used_terms')
        
        # Extract snippet locally from cached page using markers
        start_marker = term_data.get('start_marker')
        end_marker = term_data.get('end_marker')
        latex = None
        
        if start_marker:
            latex = self._extract_snippet_from_cache(book_id, page_start, start_marker, end_marker)
            if not latex:
                latex = f"% Term: {name} (marker: {start_marker})"
                logger.warning(f"Could not extract snippet for '{name}' using marker '{start_marker}' — using placeholder")
                self.log_processing_error(book_id, page_start, 'marker_not_found', f"Term: {name} | Marker: {start_marker}")

        if not name:
            return False

        # --- ORPHANED PROOF FILTER ---
        if t_type and t_type.lower() == 'proof':
            logger.warning(f"Discarding hallucinated standalone proof type: {name}")
            return False
            
        if name and name.lower().startswith('proof of'):
            logger.warning(f"Discarding term suspiciously named as a standalone proof: {name}")
            return False
            
        # --- TOC ARTIFACT FILTER ---
        if latex and self.is_toc_artifact(latex):
            logger.warning(f"Discarding hallucinated TOC artifact: {name}")
            return False

        # --- AI META-DISCUSSION FILTER ---
        if latex and self.is_ai_meta_discussion(latex):
            logger.warning(f"Discarding term with AI meta-discussion: {name}")
            return False
        # -----------------------------

        with self.db.get_connection() as conn:
            try:
                # Deduplication: Check exact name first
                existing_exact = conn.execute("""
                    SELECT id FROM knowledge_terms 
                    WHERE book_id = ? AND page_start = ? AND LOWER(name) = ?
                """, (book_id, page_start, name.lower())).fetchone()
                
                if existing_exact:
                    return False

                # Deduplication: Check fuzzy similarity to avoid duplicates
                if latex and len(latex) > 50:
                    from rapidfuzz import fuzz
                    existing_terms = conn.execute("""
                        SELECT id, latex_content FROM knowledge_terms 
                        WHERE book_id = ? AND page_start BETWEEN ? AND ?
                    """, (book_id, page_start - 1, page_start + 1)).fetchall()
                    
                    for row in existing_terms:
                        if row['latex_content']:
                            similarity = fuzz.ratio(latex[:200], row['latex_content'][:200])
                            if similarity > 85:
                                logger.info(f"Discarding duplicate term '{name}' ({similarity:.1f}% similar to ID {row['id']})")
                                return False

                cursor = conn.cursor()
                
                keywords_json = json.dumps(keywords) if keywords else ""
                keywords_text = ", ".join(keywords) if isinstance(keywords, list) else (keywords or "")
                
                cursor.execute("""
                    INSERT INTO knowledge_terms (book_id, page_start, name, term_type, latex_content, used_terms, status)
                    VALUES (?, ?, ?, ?, ?, ?, 'approved')
                """, (book_id, page_start, name, t_type, latex or "", keywords_json))
                term_id = cursor.lastrowid
                
                # Sync FTS (Legacy)
                conn.execute("INSERT INTO knowledge_terms_fts (rowid, name, used_terms, latex_content) VALUES (?, ?, ?, ?)",
                             (term_id, name, keywords_text, latex or ""))
                
                # Sync to Federated Search (ES + MWS)
                try:
                    from .knowledge import knowledge_service
                    knowledge_service.sync_term_to_federated(term_id)
                except Exception as e:
                    logger.error(f"Failed to sync new term {term_id} to federated search: {e}")
                return True
            except Exception as e:
                logger.error(f"Failed to save knowledge term: {e}")
                return False

    def backfill_all_term_latex(self, limit=100):
        """Identifies terms with missing LaTeX (placeholders) and attempts to restore them from cache."""
        with self.db.get_connection() as conn:
            # Find terms where latex_content starts with the marker placeholder
            rows = conn.execute("""
                SELECT id, book_id, page_start, name, latex_content, used_terms 
                FROM knowledge_terms 
                WHERE latex_content LIKE '%(marker: %' 
                LIMIT ?
            """, (limit,)).fetchall()
        
        repaired = 0
        for row in rows:
            term_id = row['id']
            # Extract marker from placeholder: "% Term: Name (marker: START_MARKER)"
            placeholder = row['latex_content']
            match = re.search(r'\(marker: (.*?)\)', placeholder)
            if not match: continue
            
            start_marker = match.group(1)
            # We don't have the end_marker stored in the placeholder, so we'll just take the rest of the page
            new_latex = self._extract_snippet_from_cache(row['book_id'], row['page_start'], start_marker)
            
            if new_latex and not new_latex.startswith('% Term:'):
                with self.db.get_connection() as conn:
                    conn.execute("UPDATE knowledge_terms SET latex_content = ? WHERE id = ?", (new_latex, term_id))
                    # Sync FTS
                    keywords_json = row['used_terms']
                    try:
                        import json as _json
                        kws = _json.loads(keywords_json)
                        keywords_text = ", ".join(kws) if isinstance(kws, list) else str(kws)
                    except:
                        keywords_text = str(keywords_json)
                        
                    conn.execute("UPDATE knowledge_terms_fts SET latex_content = ? WHERE rowid = ?", (new_latex, term_id))
                repaired += 1
                logger.info(f"Repaired term {term_id}: '{row['name']}'")
                
        return repaired

        
    def log_processing_error(self, book_id, page_num, error_type, details):
        """Records a failure in the processing_errors table for later auditing."""
        with self.db.get_connection() as conn:
            conn.execute("""
                INSERT INTO processing_errors (book_id, page_number, error_type, details)
                VALUES (?, ?, ?, ?)
            """, (book_id, page_num, error_type, str(details)))

    def get_or_convert_pages(self, book_id, pages, force_refresh=False, min_quality=0.7, abort_on_failure=False):
        """Standard portal for fetching page LaTeX. Checks cache, then triggers batched AI conversion."""
        results = []
        needed_pages = []
        final_results = {} # Map page_num -> result_dict

        with self.db.get_connection() as conn:
            book = conn.execute("SELECT path, title FROM books WHERE id = ?", (book_id,)).fetchone()
        if not book: return None, "Book not found"
        
        abs_path = (LIBRARY_ROOT / book['path']).resolve()

        # 1. Check Cache First
        for page_num in pages:
            cached = self.get_cached_page(book_id, page_num)
            if cached and not force_refresh and cached.get('quality_score', 0) >= min_quality:
                final_results[page_num] = {
                    'page': page_num,
                    'latex': cached.get('latex', ''),
                    'markdown': cached.get('markdown', ''),
                    'raw_text': None,
                    'quality': cached.get('quality_score'),
                    'source': 'cache'
                }
            else:
                needed_pages.append(page_num)

        # 2. Process needed pages in Batches (Adaptive sizing + padding)
        batch_size = 10  # Start optimistic
        
        # Get total page count for batch padding
        with self.db.get_connection() as conn:
            pc_row = conn.execute("SELECT page_count FROM books WHERE id = ?", (book_id,)).fetchone()
        total_pages = pc_row['page_count'] if pc_row else 0
        
        i = 0
        while i < len(needed_pages):
            batch = needed_pages[i:i + batch_size]
            
            # E8: Batch Padding — fill unused capacity with adjacent uncached pages
            if len(batch) < batch_size and total_pages > 0:
                cached_set = set(final_results.keys())
                needed_set = set(needed_pages)
                # Extend forward from the end of the batch
                for p in range(max(batch) + 1, min(max(batch) + batch_size, total_pages + 1)):
                    if len(batch) >= batch_size:
                        break
                    if p not in cached_set and p not in needed_set and p not in batch:
                        batch.append(p)
                # Extend backward from the start of the batch
                for p in range(min(batch) - 1, max(0, min(batch) - batch_size), -1):
                    if len(batch) >= batch_size:
                        break
                    if p not in cached_set and p not in needed_set and p not in batch:
                        batch.insert(0, p)
                batch.sort()
            
            logger.info(f"Batch Converting Pages {batch} of Book {book_id} (size={batch_size}, force={force_refresh})...")
            
            batch_results, error = converter.convert_pages_batch(str(abs_path), batch)
            
            if error or not batch_results:
                msg = f"Batch conversion failed for pages {batch}: {error}"
                logger.error(msg)
                
                # E1: Adaptive — halve batch size and retry this segment
                if batch_size > 3:
                    batch_size = max(3, batch_size // 2)
                    logger.warning(f"Retrying with reduced batch size: {batch_size}")
                    time.sleep(3)  # Cooldown before retry
                    continue  # Don't advance i — retry same pages
                
                if abort_on_failure:
                    return list(final_results.values()), msg
                
                # Final fallback to raw text
                for p_num in batch:
                    if p_num in set(pages):  # Only fallback for requested pages, not padding
                        raw_text = converter.extract_raw_text(str(abs_path), p_num)
                        final_results[p_num] = {
                            'page': p_num,
                            'latex': f"% Page {p_num} — AI conversion failed: {error}\n% Raw text fallback used.",
                            'markdown': None,
                            'raw_text': raw_text or "[Extraction failed]",
                            'quality': 0.0,
                            'source': 'text_fallback'
                        }
                i += len(needed_pages[i:i + batch_size])  # Advance past this segment
                continue

            # 3. Process each page result in the batch
            for p_data in batch_results:
                p_num = p_data.get('page_number')
                latex = p_data.get('latex', '').replace('\\n', '\n')
                raw_text = p_data.get('raw_text', '')
                
                # Fast Local Quality Check
                lint_errors = self.lint_latex(latex)
                compiles, comp_error = self.verify_compilation(latex)
                
                status_comments = "Passed local checks."
                
                if lint_errors or not compiles:
                    error_report = f"LINT: {', '.join(lint_errors)} | COMP: {comp_error}"
                    logger.warning(f"Page {p_num} quality check failed: {error_report}. Triggering Active Repair...")
                    
                    # E2: Cooldown before repair to prevent 503 cascade
                    time.sleep(2)
                    
                    # ACTIVE REPAIR LOOP (Round Two)
                    repaired = converter.repair_latex(latex, raw_text, error_report)
                    if repaired:
                        logger.info(f"Page {p_num} repaired successfully.")
                        latex = repaired
                        status_comments = f"Repaired: {error_report}"
                    else:
                        logger.error(f"Page {p_num} repair failed.")
                        status_comments = f"Repair failed: {error_report}"
                        self.log_processing_error(book_id, p_num, 'latex_compilation', error_report)

                # Final Cache Check: If it still doesn't compile after repair, we mark it low quality
                final_compiles, _ = self.verify_compilation(latex)
                q_score = 0.95 if final_compiles else 0.4
                
                if q_score >= min_quality:
                    self.save_page_to_cache(book_id, p_num, latex, "", q_score, status_comments)
                    source_label = 'ai_conversion'
                else:
                    source_label = 'ai_conversion_discarded'

                final_results[p_num] = {
                    'page': p_num,
                    'latex': latex if q_score >= min_quality else None,
                    'markdown': None,
                    'raw_text': raw_text if q_score < min_quality else None,
                    'quality': q_score,
                    'source': source_label,
                    'comments': status_comments
                }
            
            i += len(needed_pages[i:i + batch_size])  # Advance past this segment

        # 4. Assemble final ordered results
        ordered_results = [final_results[p] for p in pages if p in final_results]
        return ordered_results, None


    def create_note_from_pdf(self, book_id, pages):
        """Converts PDF pages into a cohesive math note, using batch processing."""
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
            page_latex = pr.get('latex') or pr.get('raw_text') or f"% [Page {page_num} extraction failed]"
            
            if pr.get('error'):
                combined_markdown += f"\n\n> [Error extracting Page {page_num}: {pr['error']}]\n\n"
                continue
            
            combined_markdown += f"\n\n## Page {page_num}\n\n```latex\n{page_latex}\n```"
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
            f.write("\\documentclass{article}\n")
            f.write("\\usepackage[utf8]{inputenc}\n")
            f.write("\\usepackage{amsmath,amssymb,amsfonts,amsthm}\n")
            f.write("\\newtheorem{theorem}{Theorem}[section]\n")
            f.write("\\newtheorem{lemma}[theorem]{Lemma}\n")
            f.write("\\newtheorem{proposition}[theorem]{Proposition}\n")
            f.write("\\newtheorem{corollary}[theorem]{Corollary}\n")
            f.write("\\newtheorem{definition}[theorem]{Definition}\n")
            f.write("\\newtheorem{remark}[theorem]{Remark}\n")
            f.write("\\newtheorem{example}[theorem]{Example}\n")
            f.write("\\begin{document}\n")
            f.write(combined_latex)
            f.write("\n\\end{document}")
            
        # Create DB record
        self.add_note(
            title=f"Extraction: {title} ({page_ref})",
            source_type='book_extraction',
            source_book_id=book_id,
            source_page_number=pages[0],
            latex_path=tex_path,
            markdown_path=md_path,
            tags=f"extraction, {title}",
            content_preview=combined_markdown[:500]
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

    def safe_filename(self, text: str) -> str:
        """Sanitizes text for use as a filename."""
        if not text: return "unnamed_note"
        # Remove non-alphanumeric except spaces, then replace spaces with underscores
        import re
        s = re.sub(r'[^\w\s-]', '', text).strip()
        s = re.sub(r'[-\s]+', '_', s)
        return s[:80] # Truncate to reasonable length

    def latex_escape(self, text: str) -> str:
        """Escapes common LaTeX special characters for use in text mode."""
        if not text: return ""
        # Order matters for backslash
        chars = [
            ('\\', r'\textbackslash{}'),
            ('&', r'\&'),
            ('%', r'\%'),
            ('$', r'\$'),
            ('#', r'\#'),
            ('_', r'\_'),
            ('{', r'\{'),
            ('}', r'\}'),
            ('~', r'\textasciitilde{}'),
            ('^', r'\textasciicircum{}'),
        ]
        s = text
        for old, new in chars:
            s = s.replace(old, new)
        return s

    def _get_grading(self, latex_content: str) -> str:
        """Sends LaTeX to DeepSeek Reasoner for rigorous grading and logical verification."""
        prompt = (
            "You are a Rigorous Proseminar Grader of Mathematics. Grade the student's mathematical work provided below.\n"
            "TASK:\n"
            "1. Use your internal reasoning trace to perform a step-by-step verification of the mathematical logic, specifically looking for subtle errors in sequences, continuity, and vector space axioms.\n"
            "2. Identify what is correct and what is incorrect. Provide a clear, rigorous correction for any errors.\n"
            "3. BE STRICT: Your final output MUST be a pure LaTeX payload. DO NOT use Markdown headers (# or ##). DO NOT use Markdown code blocks (```latex or ```). The output must be ready for immediate inclusion in a .tex document template. Omit all introductory conversational phrases.\n"
            "4. Structure your response using standard LaTeX sections ONLY: \\section*{Evaluation}, \\subsection*{Corrected Work}, and you MUST provide a \\section*{Model Solution} at the end, which serves as the definitive reference for the student.\n"
            "5. Use standard amsmath environments.\n"
            "6. Verify each logical transition before committing to the final LaTeX output.\n\n"
            f"STUDENT WORK (LaTeX):\n{latex_content}"
        )
        
        try:
            # Directly use DeepSeek Provider for this specific task
            if self.ai.routing_policy == "dual_stack" and self.ai.deepseek:
                logger.info("Using deepseek-reasoner for grading pipeline...")
                response = self.ai.deepseek.client.chat.completions.create(
                    model="deepseek-reasoner",
                    messages=[{"role": "user", "content": prompt}]
                )
                msg = response.choices[0].message
                reasoning = getattr(msg, 'reasoning_content', '')
                content = msg.content or ""
                
                if reasoning:
                    logger.info(f"[Grader] Reasoning trace generated ({len(reasoning)} chars). Logging to file.")
                    try:
                        from core.config import PROJECT_ROOT
                        log_path = PROJECT_ROOT / "logs" / "ai_reasoning.log"
                        log_path.parent.mkdir(exist_ok=True)
                        with open(log_path, "a", encoding="utf-8") as f:
                            import datetime
                            now = datetime.datetime.now().isoformat()
                            f.write(f"\n\n--- REASONING TRACE [{now}] ---\n{reasoning}\n")
                    except Exception as e:
                        logger.warning(f"[Grader] Failed to log reasoning: {e}")
                        
                grading_latex = content
            else:
                # Fallback to general AI text generation
                from google.genai import types
                contents = [types.Content(role="user", parts=[types.Part.from_text(text=prompt)])]
                grading_latex = self.ai.generate_text(contents)
            
            if not grading_latex:
                return "% Generation Error: Grading failed to generate content."
                
            # Post-processing: Aggressively sanitize of markdown and chat context
            import re
            grading_latex = re.sub(r'```latex\s*', '', grading_latex)
            grading_latex = re.sub(r'```\s*', '', grading_latex)
            grading_latex = re.sub(r'</?think>', '', grading_latex)
            
            grading_latex = grading_latex.strip()
            
            if not grading_latex:
                return "% Generation Error: Output was malformed or empty."
                
            return grading_latex
            
        except Exception as e:
            logger.error(f"Grading failed: {e}")
            return f"% Generation Error: {str(e)}"

    def _get_solution(self, latex_content: str) -> str:
        """Sends LaTeX exercise to DeepSeek Reasoner for a detailed step-by-step solution."""
        prompt = (
            "You are a Master Teacher of Mathematics. Solve the mathematical exercise provided below.\n"
            "TASK:\n"
            "1. Provide a comprehensive, step-by-step solution that is mathematically rigorous and educationally clear.\n"
            "2. Explain the intuition behind key steps. Ensure all edge cases or constraints are addressed.\n"
            "3. BE STRICT: Your final output MUST be a pure LaTeX payload. DO NOT use Markdown headers or code blocks. The output must be ready for immediate inclusion in a .tex document template.\n"
            "4. Structure your response using: \\section*{Problem Statement}, \\section*{Step-by-Step Solution}, and \\section*{Final Answer}.\n"
            "5. Use standard amsmath environments.\n"
            f"EXERCISE (LaTeX):\n{latex_content}"
        )
        
        try:
            if self.ai.routing_policy == "dual_stack" and self.ai.deepseek:
                logger.info("Using deepseek-reasoner for solution pipeline...")
                response = self.ai.deepseek.client.chat.completions.create(
                    model="deepseek-reasoner",
                    messages=[{"role": "user", "content": prompt}]
                )
                content = response.choices[0].message.content or ""
                return re.sub(r'```latex\s*|```\s*|</?think>', '', content).strip()
            else:
                from google.genai import types
                contents = [types.Content(role="user", parts=[types.Part.from_text(text=prompt)])]
                return self.ai.generate_text(contents)
        except Exception as e:
            logger.error(f"Solution generation failed: {e}")
            return f"% Generation Error: {str(e)}"

    def process_note_silent(self, transcription, image_data):
        """Saves transcription, handles triggered mode (G, B, S), and compiles PDF."""
        title = transcription.get('title', 'Handwritten Note')
        mode = transcription.get('trigger_mode', 'G').upper()
        filename_base = self.safe_filename(title)
        
        from core.config import NOTES_OUTPUT_DIR
        final_base = filename_base
        counter = 1
        while (NOTES_OUTPUT_DIR / f"{final_base}.tex").exists():
            final_base = f"{filename_base}_{counter}"
            counter += 1
            
        tex_path = NOTES_OUTPUT_DIR / f"{final_base}.tex"
        json_path = NOTES_OUTPUT_DIR / f"{final_base}.json"
        img_path = NOTES_OUTPUT_DIR / f"{final_base}.jpg"
        
        student_raw = transcription.get('latex_source', '')
        
        import re
        def clean_latex(text):
            text = re.sub(r'\\documentclass\{.*?\}', '', text, flags=re.DOTALL)
            text = re.sub(r'\\usepackage\{.*?\}', '', text, flags=re.DOTALL)
            text = re.sub(r'\\begin\{document\}', '', text, flags=re.DOTALL)
            text = re.sub(r'\\end\{document\}', '', text, flags=re.DOTALL)
            return text.strip()

        student_latex = clean_latex(student_raw).replace('\\n', '\n')
        safe_title = self.latex_escape(title)
        
        # --- Mode Branching ---
        ai_payload = ""
        doc_subtitle = ""
        
        if mode == 'B':
            logger.info(f"Mode B (Blank): Just transcribing {title}")
            doc_subtitle = "Note Transcription"
        elif mode == 'S':
            logger.info(f"Mode S (Solve): Solving exercise {title}")
            ai_payload = self._get_solution(student_latex).replace('\\n', '\n')
            doc_subtitle = "Exercise Solution"
        else: # Default to 'G'
            logger.info(f"Mode G (Grading): Grading submission {title}")
            ai_payload = self._get_grading(student_latex).replace('\\n', '\n')
            doc_subtitle = "Student Work \\& Professor's Feedback"

        # Handle potential AI errors
        if ai_payload.startswith("% Generation Error"):
            logger.error(f"AI Generation Error for {title}: {ai_payload}")
            # Fallback to just student work if AI failed
            ai_payload = f"\\section*{{AI Error}}\n{ai_payload}\n\\section*{{Original Transcription}}\n{student_latex}"

        # --- Build LaTeX Document ---
        combined_latex = [
            "\\documentclass{article}",
            "\\usepackage[utf8]{inputenc}",
            "\\usepackage{amsmath,amssymb,amsfonts,amsthm,geometry,xcolor}",
            "\\geometry{margin=1in}",
            "\\newtheorem{theorem}{Theorem}[section]",
            "\\newtheorem{lemma}[theorem]{Lemma}",
            "\\newtheorem{proposition}[theorem]{Proposition}",
            "\\newtheorem{corollary}[theorem]{Corollary}",
            "\\newtheorem{definition}{Definition}[section]",
            "\\newtheorem{remark}[theorem]{Remark}",
            "\\newtheorem{example}[theorem]{Example}",
            "\\newtheorem{exercise}[theorem]{Exercise}",
            "\\title{" + safe_title + "}",
            "\\author{" + doc_subtitle + "}",
            "\\date{\\today}",
            "\\begin{document}",
            "\\maketitle"
        ]

        if mode == 'B':
            combined_latex.append(student_latex)
        elif mode == 'S':
            combined_latex.append(ai_payload)
        else: # G
            combined_latex.extend([
                "\\section{Original Submission}",
                student_latex,
                "\\newpage",
                ai_payload
            ])
            
        combined_latex.append("\\end{document}")
        
        # --- Build Markdown Summary (for search and hub) ---
        tags = transcription.get('tags', 'handwritten')
        if isinstance(tags, list): tags = ", ".join(tags)
        msc = transcription.get('msc', '')
        
        md_path = NOTES_OUTPUT_DIR / f"{final_base}.md"
        
        md_content = f"# {title}\n\n"
        md_content += f"**Processing Mode**: {mode} ({doc_subtitle})\n"
        if msc: md_content += f"**MSC**: {msc}\n"
        if tags: md_content += f"**Tags**: {tags}\n\n"
        
        md_content += "## Transcription\n"
        md_content += f"```latex\n{student_latex}\n```\n\n"
        
        if ai_payload:
            md_content += "## AI Results\n"
            md_content += f"```latex\n{ai_payload}\n```\n"

        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

        # --- Save and Compile ---
        with open(tex_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(combined_latex))

        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump({**transcription, "ai_payload": ai_payload, "mode": mode}, f, indent=2)
            
        with open(img_path, 'wb') as f:
            f.write(image_data)
            
        from services.compilation import compilation_service
        pdf_path = compilation_service.compile_tex(tex_path)
        
        # --- Database Persistence ---
        note_id = self.add_note(
            title=title,
            source_type='handwritten',
            latex_path=f"notes_output/{final_base}.tex",
            markdown_path=f"notes_output/{final_base}.md",
            pdf_path=f"notes_output/{final_base}.pdf" if pdf_path else None,
            json_meta_path=f"notes_output/{final_base}.json",
            tags=tags,
            msc=msc,
            content_preview=md_content[:1000],
            processing_mode=mode
        )
        
        # Cleanup LaTeX auxiliary files
        for ext in ['.aux', '.log', '.out']:
            aux_file = tex_path.with_suffix(ext)
            if aux_file.exists():
                try: os.remove(aux_file)
                except: pass

        return {
            "title": title,
            "tex_path": str(tex_path),
            "pdf_path": str(pdf_path) if pdf_path else None,
            "success": True,
            "mode": mode
        }

    def reprocess_note(self, note_id, target_mode):
        """Changes the mode (B, G, S) of an existing note and recompiles."""
        note = self.get_note(note_id)
        if not note or not note.get('json_meta_path'):
            return {"success": False, "error": "Note or metadata not found."}
            
        json_path = Path(note['json_meta_path'])
        if not json_path.exists():
            return {"success": False, "error": "Original transcription JSON missing."}
            
        with open(json_path, 'r', encoding='utf-8') as f:
            meta = json.load(f)
            
        student_raw = meta.get('latex_source', '')
        if not student_raw:
            return {"success": False, "error": "No original student LaTeX found."}
            
        import re
        def clean_latex(text):
            text = re.sub(r'\\documentclass\{.*?\}', '', text, flags=re.DOTALL)
            text = re.sub(r'\\usepackage\{.*?\}', '', text, flags=re.DOTALL)
            text = re.sub(r'\\begin\{document\}', '', text, flags=re.DOTALL)
            text = re.sub(r'\\end\{document\}', '', text, flags=re.DOTALL)
            return text.strip()

        student_latex = clean_latex(student_raw).replace('\\n', '\n')
        safe_title = self.latex_escape(note['title'])
        target_mode = target_mode.upper()
        
        ai_payload = ""
        doc_subtitle = ""
        
        if target_mode == 'B':
            logger.info(f"Reprocessing {note_id} to B (Blank)")
            doc_subtitle = "Note Transcription"
        elif target_mode == 'S':
            logger.info(f"Reprocessing {note_id} to S (Solve)")
            ai_payload = self._get_solution(student_latex).replace('\\n', '\n')
            doc_subtitle = "Exercise Solution"
        else: # G
            logger.info(f"Reprocessing {note_id} to G (Grading)")
            ai_payload = self._get_grading(student_latex).replace('\\n', '\n')
            doc_subtitle = "Student Work \\& Professor's Feedback"

        # Build Document
        combined_latex = [
            "\\documentclass{article}",
            "\\usepackage[utf8]{inputenc}",
            "\\usepackage{amsmath,amssymb,amsfonts,amsthm,geometry,xcolor}",
            "\\geometry{margin=1in}",
            "\\newtheorem{theorem}{Theorem}[section]",
            "\\newtheorem{lemma}[theorem]{Lemma}",
            "\\newtheorem{proposition}[theorem]{Proposition}",
            "\\newtheorem{corollary}[theorem]{Corollary}",
            "\\newtheorem{definition}{Definition}[section]",
            "\\newtheorem{remark}[theorem]{Remark}",
            "\\newtheorem{example}[theorem]{Example}",
            "\\newtheorem{exercise}[theorem]{Exercise}",
            "\\title{" + safe_title + "}",
            "\\author{" + doc_subtitle + "}",
            "\\date{\\today}",
            "\\begin{document}",
            "\\maketitle"
        ]

        if target_mode == 'B':
            combined_latex.append(student_latex)
        elif target_mode == 'S':
            combined_latex.append(ai_payload)
        else: # G
            combined_latex.extend([
                "\\section*{Original Submission}",
                student_latex,
                "\\newpage",
                ai_payload
            ])
            
        combined_latex.append("\\end{document}")
        
        # Save new LaTeX
        tex_path = Path(note['latex_path']) if note.get('latex_path') else Path(NOTES_OUTPUT_DIR) / f"note_{note_id}.tex"
        with open(tex_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(combined_latex))
            
        # Update metadata JSON
        meta['mode'] = target_mode
        meta['ai_payload'] = ai_payload
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2)
            
        # Update DB
        self.update_note_metadata(note_id, {"processing_mode": target_mode})
        
        # Recompile
        from services.compilation import compilation_service
        res = compilation_service.compile_note(note_id)
        if res.get('success'):
            return {"success": True, "mode": target_mode, "pdf_path": res.get('pdf_path')}
        return {"success": False, "error": res.get('error'), "mode": target_mode}

    def extract_master_solution(self, note_id):
        """Extracts the model solution into a brand new note."""
        note = self.get_note(note_id)
        if not note or not note.get('latex_path'):
            return {"success": False, "error": "Note or LaTeX not found."}
            
        tex_path = Path(note['latex_path'])
        with open(tex_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Try to find the solution block
        import re
        match = re.search(r'\\section\*?\{(?:Model Solution|Final Answer|Step-by-Step Solution)\}(.*?)\\end\{document\}', content, re.DOTALL | re.IGNORECASE)
        if not match:
            # Fallback: Just grab everything after the last newpage
            parts = content.split('\\newpage')
            if len(parts) > 1:
                solution_text = parts[-1].replace('\\end{document}', '').strip()
            else:
                return {"success": False, "error": "Could not identify solution block."}
        else:
            solution_text = match.group(1).strip()
            
        new_title = f"Solution: {note['title']}"
        safe_title = self.latex_escape(new_title)
        
        filename_base = self.safe_filename(new_title)
        final_base = filename_base
        counter = 1
        while (NOTES_OUTPUT_DIR / f"{final_base}.tex").exists():
            final_base = f"{filename_base}_{counter}"
            counter += 1
            
        new_tex_path = NOTES_OUTPUT_DIR / f"{final_base}.tex"
        
        new_latex = [
            "\\documentclass{article}",
            "\\usepackage[utf8]{inputenc}",
            "\\usepackage{amsmath,amssymb,amsfonts,amsthm,geometry,xcolor}",
            "\\geometry{margin=1in}",
            "\\newtheorem{theorem}{Theorem}[section]",
            "\\newtheorem{lemma}[theorem]{Lemma}",
            "\\newtheorem{proposition}[theorem]{Proposition}",
            "\\newtheorem{corollary}[theorem]{Corollary}",
            "\\newtheorem{definition}{Definition}[section]",
            "\\newtheorem{remark}[theorem]{Remark}",
            "\\newtheorem{example}[theorem]{Example}",
            "\\newtheorem{exercise}[theorem]{Exercise}",
            "\\title{" + safe_title + "}",
            "\\author{Master Solution}",
            "\\date{\\today}",
            "\\begin{document}",
            "\\maketitle",
            solution_text,
            "\\end{document}"
        ]
        
        with open(new_tex_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(new_latex))
            
        # Compile
        from services.compilation import compilation_service
        new_pdf_path = compilation_service.compile_tex(new_tex_path)
        
        # Add to DB
        new_note_id = self.add_note(
            title=new_title,
            source_type='handwritten',
            latex_path=f"notes_output/{final_base}.tex",
            pdf_path=f"notes_output/{final_base}.pdf" if new_pdf_path else None,
            tags="solution",
            processing_mode="B"
        )
        
        return {"success": True, "new_note_id": new_note_id}

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
                f.write("\\documentclass{article}\n")
                f.write("\\usepackage[utf8]{inputenc}\n")
                f.write("\\usepackage{amsmath,amssymb,amsfonts,amsthm}\n")
                f.write("\\newtheorem{theorem}{Theorem}[section]\n")
                f.write("\\newtheorem{lemma}[theorem]{Lemma}\n")
                f.write("\\newtheorem{proposition}[theorem]{Proposition}\n")
                f.write("\\newtheorem{corollary}[theorem]{Corollary}\n")
                f.write("\\newtheorem{definition}[theorem]{Definition}\n")
                f.write("\\newtheorem{remark}[theorem]{Remark}\n")
                f.write("\\newtheorem{example}[theorem]{Example}\n")
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
                    f.write("\\documentclass{article}\n")
                    f.write("\\usepackage[utf8]{inputenc}\n")
                    f.write("\\usepackage{amsmath,amssymb,amsfonts,amsthm}\n")
                    f.write("\\newtheorem{theorem}{Theorem}[section]\n")
                    f.write("\\newtheorem{lemma}[theorem]{Lemma}\n")
                    f.write("\\newtheorem{proposition}[theorem]{Proposition}\n")
                    f.write("\\newtheorem{corollary}[theorem]{Corollary}\n")
                    f.write("\\newtheorem{definition}[theorem]{Definition}\n")
                    f.write("\\newtheorem{remark}[theorem]{Remark}\n")
                    f.write("\\newtheorem{example}[theorem]{Example}\n")
                    f.write(f"\\title{{{title}}}\n\\begin{{document}}\n\\maketitle\n")
                    f.write(latex_content)
                    f.write("\n\\end{{document}}")
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
        
        return note_id

    # ========================================
    # Full Book Scan — Slow Crawl Engine
    # ========================================

    @staticmethod
    def classify_page(text):
        """Classify a page as 'content' or 'skip' from raw PDF text."""
        text = (text or '').strip()
        
        if len(text) < 100:
            return 'skip'
        
        lower = text.lower()
        first_200 = lower[:200]
        
        # Front matter
        front_markers = ['©', 'isbn', 'all rights reserved', 'library of congress',
                         'printed in', 'table of contents']
        if any(m in first_200 for m in front_markers):
            return 'skip'
        
        # Back matter: page starts with a back-matter heading
        back_markers = ['bibliography', 'references\n', 'index\n', 'index of notation',
                        'list of symbols', 'notation index', 'symbol index']
        if any(first_200.startswith(m) or f'\n{m}' in first_200 for m in back_markers):
            return 'skip'
        
        # TOC-like pages: lots of dots and page numbers
        dot_ratio = text.count('.') / max(len(text), 1)
        digit_ratio = sum(c.isdigit() for c in text) / max(len(text), 1)
        if dot_ratio > 0.1 and digit_ratio > 0.1:
            return 'skip'
        
        return 'content'

    @staticmethod
    def is_term_extractable(latex):
        """Check if converted LaTeX has actual mathematical content worth extracting."""
        if not latex or len(latex) < 150:
            return False
        lower = latex.lower()
        has_math = '$' in latex or '\\begin{' in latex
        is_biblio = lower.count('\\bibitem') > 3 or lower.count('[') > 20
        return has_math and not is_biblio

    def is_cancelled(self, scan_id):
        """Checks if the user has requested cancellation."""
        try:
            with self.db.get_connection() as conn:
                row = conn.execute("SELECT status FROM book_scans WHERE id = ?", (scan_id,)).fetchone()
                return row and row['status'] == 'cancelled'
        except Exception: return False

    def run_book_scan(self, scan_id):
        """Execute a full book scan using the unified 5-pass PipelineService."""
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT book_id FROM book_scans WHERE id = ?", (scan_id,)).fetchone()
            if not row: return
            book_id = row['book_id']

        try:
            # Mark as running
            with self.db.get_connection() as conn:
                conn.execute("UPDATE book_scans SET status = 'scanning', started_at = unixepoch() WHERE id = ?", (scan_id,))
            
            # Pass 0: Boundaries
            if self.is_cancelled(scan_id): return
            logger.info(f"Scan {scan_id}: Starting Pass 0 (Boundaries)")
            pipeline_service.run_pass_0(book_id)

            # Fix progress tracking: get actual pages to process
            with self.db.get_connection() as conn:
                book = conn.execute("SELECT content_start, content_end FROM books WHERE id = ?", (book_id,)).fetchone()
                if book:
                    pages_total = (book['content_end'] or 0) - (book['content_start'] or 0) + 1
                    conn.execute("UPDATE book_scans SET pages_total = ? WHERE id = ?", (max(0, pages_total), scan_id))
            
            # Pass 1: Visual Harvester
            if self.is_cancelled(scan_id): return
            logger.info(f'Scan {scan_id}: Starting Pass 1 (LaTeX Converter)')
            
            def update_progress(done):
                with self.db.get_connection() as conn:
                    conn.execute("UPDATE book_scans SET pages_done = ? WHERE id = ?", (done, scan_id))
            
            stats1 = pipeline_service.run_pass_1(book_id, progress_callback=update_progress)
            
            # Update pages_done after Pass 1
            with self.db.get_connection() as conn:
                conn.execute(
                    "UPDATE book_scans SET pages_done = ?, status = 'extracting' WHERE id = ?", 
                    (stats1.get('ok', 0) + stats1.get('failed', 0), scan_id)
                )

            # Auto-insert into deep_indexed_books
            with self.db.get_connection() as conn:
                conn.execute("INSERT OR REPLACE INTO deep_indexed_books (book_id, indexed_at) VALUES (?, unixepoch())", (book_id,))
            
            # Pass 2: Term Extraction
            if self.is_cancelled(scan_id): return
            logger.info(f'Scan {scan_id}: Starting Pass 2 (Term Extraction)')
            
            def update_term_progress(done, terms):
                with self.db.get_connection() as conn:
                    conn.execute(
                        "UPDATE book_scans SET pages_done = ?, terms_found = ?, status = 'extracting' WHERE id = ?", 
                        (done, terms, scan_id)
                    )
            
            stats2 = pipeline_service.run_pass_2(book_id, progress_callback=update_term_progress)
            
            # Update terms_found and transition to semantic phase
            with self.db.get_connection() as conn:
                conn.execute(
                    "UPDATE book_scans SET terms_found = ?, status = 'embedding' WHERE id = ?", 
                    (stats2.get('saved', 0), scan_id)
                )

            # Pass 3: Incrementally Embed Terms
            if self.is_cancelled(scan_id): return
            logger.info(f"Scan {scan_id}: Starting Pass 3 (Embedding)")
            from scripts.batch_embed_terms import process_batch
            process_batch() # This is already incremental thanks to our earlier patch

            # Pass 4: Anchoring
            if self.is_cancelled(scan_id): return
            logger.info(f"Scan {scan_id}: Starting Pass 4 (Anchoring)")
            with self.db.get_connection() as conn:
                conn.execute("UPDATE book_scans SET status = 'anchoring' WHERE id = ?", (scan_id,))
            from services.anchoring import AnchoringService
            anch_svc = AnchoringService()
            anch_svc.run_clustering()

            # Pass 5: ES Backfill (Terms)
            if self.is_cancelled(scan_id): return
            logger.info(f"Scan {scan_id}: Starting Pass 5 (Synching ES Terms)")
            with self.db.get_connection() as conn:
                conn.execute("UPDATE book_scans SET status = 'syncing' WHERE id = ?", (scan_id,))
            from scripts.backfill_concept_ids import backfill
            backfill()

            # Pass 6: ES Page Indexing (Full-Text)
            if self.is_cancelled(scan_id): return
            logger.info(f"Scan {scan_id}: Starting Pass 6 (Indexing Full-Text Pages)")
            from scripts.index_latex_pages import index_latex_pages
            index_latex_pages(book_id)

            # Update final status
            with self.db.get_connection() as conn:
                conn.execute(
                    'UPDATE book_scans SET status = "completed", completed_at = unixepoch() WHERE id = ?',
                    (scan_id,)
                )
            logger.info(f'Scan {scan_id}: Completed pipeline successfully.')
            
        except Exception as e:
            logger.error(f"Scan {scan_id} failed: {e}")
            with self.db.get_connection() as conn:
                conn.execute("UPDATE book_scans SET status = 'failed', error_log = ? WHERE id = ?", (str(e), scan_id))

    def scan_worker(self):
        """Background daemon: picks queued scans and runs them one at a time."""
        time.sleep(5) # Let the app initialize
        
        # Reset stale "running" scans on startup
        try:
            with self.db.get_connection() as conn:
                conn.execute("""
                    UPDATE book_scans 
                    SET status = 'queued' 
                    WHERE status NOT IN ('completed', 'failed', 'cancelled', 'queued')
                """)
                logger.info("Scan worker: Reset stale scans to 'queued' on startup.")
        except Exception as e:
            logger.error(f"Scan worker startup error: {e}")

        while True:
            try:
                with self.db.get_connection() as conn:
                    scan = conn.execute(
                        "SELECT id FROM book_scans WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1"
                    ).fetchone()
                
                if scan:
                    self.run_book_scan(scan['id'])
                else:
                    time.sleep(30)  # Check every 30 seconds
            except Exception as e:
                logger.error(f"Scan worker error: {e}")
                time.sleep(60)

# Global instance
note_service = NoteService()
sectional_note_service = SectionalNoteService(db)

