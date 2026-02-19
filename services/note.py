import datetime
import json
import os
import shutil
import io
import subprocess
from pathlib import Path
from PIL import Image
import numpy as np
from core.database import db
from core.ai import ai
from core.config import LIBRARY_ROOT, CONVERTED_NOTES_DIR, OBSIDIAN_INBOX, NOTES_OUTPUT_DIR, EMBEDDING_MODEL

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
        import base64
        optimized_data = self.optimize_image(image_data)
        encoded_image = base64.b64encode(optimized_data).decode('utf-8')
        
        prompt = (
            "You are a mathematical transcription expert. Convert this handwritten note into two formats:\n"
            "1. High-quality, clean LaTeX code for PDF generation.\n"
            "2. Obsidian-flavored Markdown for digital notes.\n\n"
            "Return a JSON object with keys: 'latex_source', 'markdown_source', 'title', 'tags'."
        )
        
        try:
            from google.genai import types
            response = self.ai.client.models.generate_content(
                model=self.ai.model_name,
                contents=[
                    prompt,
                    types.Part.from_bytes(data=optimized_data, mime_type="image/jpeg")
                ],
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            return json.loads(response.text)
        except Exception as e:
            print(f"[NoteService] Transcription failed: {e}")
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

    def get_cached_page(self, book_id, page_number):
        """Checks if a page has already been extracted and returns its content."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT latex_path, markdown_path FROM extracted_pages WHERE book_id = ? AND page_number = ?",
                (book_id, page_number)
            )
            row = cursor.fetchone()
            
        if row:
            latex_path = Path(row['latex_path'])
            markdown_path = Path(row['markdown_path'])
            
            if latex_path.exists() and markdown_path.exists():
                with open(latex_path, 'r', encoding='utf-8') as f:
                    latex = f.read()
                with open(markdown_path, 'r', encoding='utf-8') as f:
                    markdown = f.read()
                return {'latex': latex, 'markdown': markdown}
        return None

    def save_page_to_cache(self, book_id, page_number, latex, markdown):
        """Saves extracted page content to the structured repository and database."""
        book_dir = CONVERTED_NOTES_DIR / str(book_id)
        book_dir.mkdir(parents=True, exist_ok=True)
        
        latex_path = book_dir / f"page_{page_number}.tex"
        markdown_path = book_dir / f"page_{page_number}.md"
        
        with open(latex_path, 'w', encoding='utf-8') as f:
            f.write(latex)
        with open(markdown_path, 'w', encoding='utf-8') as f:
            f.write(markdown)
            
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO extracted_pages (book_id, page_number, latex_path, markdown_path)
                VALUES (?, ?, ?, ?)
            """, (book_id, page_number, str(latex_path), str(markdown_path)))

    def create_note_from_pdf(self, book_id, pages):
        """Converts PDF pages to structured notes, utilizing the cache."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT path, title, author FROM books WHERE id = ?", (book_id,))
            res = cursor.fetchone()
            
        if not res: return None, "Book not found"
        
        rel_path, title, author = res['path'], res['title'], res['author']
        abs_path = (LIBRARY_ROOT / rel_path).resolve()
        
        import converter
        combined_markdown = ""
        combined_latex = ""
        
        for page_num in pages:
            # 1. Check Cache
            cached = self.get_cached_page(book_id, page_num)
            
            if cached:
                page_markdown = cached['markdown']
                page_latex = cached['latex']
            else:
                # 2. Extract via AI
                result_data, error = converter.convert_page(str(abs_path), page_num)
                if error:
                    combined_markdown += f"\n\n> [Error extracting Page {page_num}: {error}]\n\n"
                    continue
                
                page_markdown = result_data.get('markdown', '')
                page_latex = result_data.get('latex', '')
                
                # 3. Save to Cache
                self.save_page_to_cache(book_id, page_num, page_latex, page_markdown)

            combined_markdown += f"\n\n## Page {page_num}\n\n" + page_markdown
            combined_latex += f"\n% --- Page {page_num} ---\n" + page_latex

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        page_ref = f"p. {pages[0]}" if len(pages) == 1 else f"pp. {pages[0]}-{pages[-1]}"
        header = f"---\ntitle: Note from {title} ({page_ref})\nauthor: {author}\ndate: {timestamp}\ntags: [auto-note, {title}]\n---\n\n"
        full_markdown = header + combined_markdown
        
        # Save aggregate note (keep existing behavior for Obsidian sync)
        safe_title = "".join(x for x in title if x.isalnum() or x in " -_")[:50]
        filename_base = f"{safe_title}_p{pages[0]}"
        if len(pages) > 1: filename_base += f"-{pages[-1]}"
        
        md_path = CONVERTED_NOTES_DIR / f"{filename_base}.md"
        with open(md_path, 'w', encoding='utf-8') as f: f.write(full_markdown)
            
        if OBSIDIAN_INBOX.exists():
            shutil.copy2(md_path, OBSIDIAN_INBOX / f"{filename_base}.md")
            
        return {'filename': f"{filename_base}.md", 'content': full_markdown, 'path': str(md_path)}, None

    def list_notes(self):
        """Returns a sorted list of all notes."""
        notes = []
        for d in [NOTES_OUTPUT_DIR, CONVERTED_NOTES_DIR]:
            if not d.exists(): continue
            for f in d.glob("*.tex"):
                meta = self.get_note_metadata(f.stem, d)
                notes.append({
                    'filename': f.name,
                    'base_name': f.stem,
                    'title': meta.get('title', f.stem),
                    'created': meta.get('created', ''),
                    'modified': f.stat().st_mtime,
                    'directory': str(d.name)
                })
        notes.sort(key=lambda x: x['modified'], reverse=True)
        return notes

    def get_note_metadata(self, base_name, directory):
        json_path = directory / f"{base_name}.json"
        if json_path.exists():
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else {}
            except: pass
        return {}

    def delete_note(self, base_name):
        deleted = False
        extensions = ['.tex', '.pdf', '.json', '.md']
        for d in [NOTES_OUTPUT_DIR, CONVERTED_NOTES_DIR]:
            for ext in extensions:
                f = d / (base_name + ext)
                if f.exists():
                    os.remove(f)
                    deleted = True
        return deleted

    def rename_note(self, old_base, new_base):
        renamed = False
        extensions = ['.tex', '.pdf', '.json', '.md']
        for d in [NOTES_OUTPUT_DIR, CONVERTED_NOTES_DIR]:
            for ext in extensions:
                old_f = d / (old_base + ext)
                new_f = d / (new_base + ext)
                if old_f.exists():
                    os.rename(old_f, new_f)
                    renamed = True
        return renamed

# Global instance
note_service = NoteService()
