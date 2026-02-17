import os
import shutil
import hashlib
import time
import json
from pathlib import Path
from core.database import db
from core.ai import ai
from core.config import LIBRARY_ROOT, DUPLICATES_DIR, GEMINI_MODEL

class LibraryService:
    def __init__(self):
        self.db = db
        self.ai = ai

    def calculate_hash(self, file_path):
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def check_duplicate(self, file_hash, title=None, author=None):
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. Hash match
            cursor.execute("SELECT id, path FROM books WHERE file_hash = ?", (file_hash,))
            match = cursor.fetchone()
            if match:
                return "HASH", dict(match)
            
            # 2. Semantic match (simplified)
            if title:
                clean_title = title.lower().replace(":", "").split()[0]
                if len(clean_title) > 4:
                    cursor.execute(
                        "SELECT id, path, title FROM books WHERE title LIKE ? AND author LIKE ?", 
                        (f"%{clean_title}%", f"%{author}%" if author else "%")
                    )
                    match = cursor.fetchone()
                    if match:
                        return "SEMANTIC", dict(match)
        return None, None

    def delete_book(self, book_id):
        """Archives the file and removes DB entries."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT path, title FROM books WHERE id = ?", (book_id,))
            row = cursor.fetchone()
            if not row:
                return False, "Book not found"
            
            rel_path, title = row['path'], row['title']
            abs_path = (LIBRARY_ROOT / rel_path).resolve()
            
            # Archive
            archive_dir = LIBRARY_ROOT / "_Admin" / "Archive" / "Deleted"
            archive_dir.mkdir(parents=True, exist_ok=True)
            
            if abs_path.exists():
                dest_path = archive_dir / f"{book_id}_{abs_path.name}"
                shutil.move(str(abs_path), str(dest_path))
            
            # DB Cleanup
            cursor.execute("DELETE FROM books WHERE id = ?", (book_id,))
            # FTS and Bookmarks should be handled by ON DELETE CASCADE if possible, 
            # but books_fts is virtual and doesn't support FKs.
            cursor.execute("DELETE FROM books_fts WHERE rowid = ?", (book_id,))
            
            return True, f"Book '{title}' deleted and archived."

    def check_sanity(self, fix=False):
        """Checks for broken paths and duplicate entries."""
        results = {"broken": [], "duplicates": []}
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, path, title FROM books")
            for row in cursor.fetchall():
                abs_path = LIBRARY_ROOT / row['path']
                if not abs_path.exists():
                    results["broken"].append(dict(row))
                    if fix:
                        cursor.execute("DELETE FROM books WHERE id = ?", (row['id'],))
                        cursor.execute("DELETE FROM books_fts WHERE rowid = ?", (row['id'],))
            
            # Duplicate hash check
            cursor.execute("SELECT file_hash, COUNT(*) FROM books GROUP BY file_hash HAVING COUNT(*) > 1")
            for row in cursor.fetchall():
                results["duplicates"].append(row['file_hash'])
                
        return results

    def get_book_by_path(self, rel_path):
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM books WHERE path = ?", (rel_path,))
            row = cursor.fetchone()
            return dict(row) if row else None

# Global instance
library_service = LibraryService()
