import datetime
import json
import os
import shutil
from pathlib import Path
from core.database import db
from core.ai import ai
from core.config import LIBRARY_ROOT, CONVERTED_NOTES_DIR, OBSIDIAN_INBOX

class NoteService:
    def __init__(self):
        self.db = db
        self.ai = ai

    def create_note_from_pdf(self, book_id, pages):
        """High-level orchestration for converting PDF pages to structured notes."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT path, title, author FROM books WHERE id = ?", (book_id,))
            res = cursor.fetchone()
            
        if not res: return None, "Book not found"
        
        rel_path, title, author = res['path'], res['title'], res['author']
        abs_path = (LIBRARY_ROOT / rel_path).resolve()
        
        # This still relies on the 'converter' module for now, 
        # which we might refactor later or keep as a utility.
        import converter
        
        combined_markdown = ""
        combined_latex = ""
        
        for page_num in pages:
            result_data, error = converter.convert_page(str(abs_path), page_num)
            if error:
                combined_markdown += f"\n\n> [Error extracting Page {page_num}: {error}]\n\n"
                continue
            combined_markdown += f"\n\n## Page {page_num}\n\n" + result_data.get('markdown', '')
            combined_latex += f"\n% --- Page {page_num} ---\n" + result_data.get('latex', '')

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        page_ref = f"p. {pages[0]}" if len(pages) == 1 else f"pp. {pages[0]}-{pages[-1]}"
        header = f"---\ntitle: Note from {title} ({page_ref})\nauthor: {author}\ndate: {timestamp}\ntags: [auto-note, {title}]\n---\n\n"
        full_markdown = header + combined_markdown
        
        # Save files
        safe_title = "".join(x for x in title if x.isalnum() or x in " -_")[:50]
        filename_base = f"{safe_title}_p{pages[0]}"
        if len(pages) > 1: filename_base += f"-{pages[-1]}"
        
        md_path = CONVERTED_NOTES_DIR / f"{filename_base}.md"
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(full_markdown)
            
        # Obsidian Sync
        if OBSIDIAN_INBOX.exists():
            shutil.copy2(md_path, OBSIDIAN_INBOX / f"{filename_base}.md")
            
        return {
            'filename': f"{filename_base}.md",
            'content': full_markdown,
            'path': str(md_path)
        }, None

# Global instance
note_service = NoteService()
