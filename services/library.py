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

    def populate_missing_hashes(self, limit=None):
        """Calculates and stores hashes for books where file_hash is missing."""
        with self.db.get_connection() as conn:
            query = "SELECT id, path FROM books WHERE file_hash IS NULL OR file_hash = ''"
            if limit:
                query += f" LIMIT {int(limit)}"
            rows = conn.execute(query).fetchall()
        
        updated = 0
        for row in rows:
            book_id = row['id']
            rel_path = row['path']
            abs_path = LIBRARY_ROOT / rel_path
            
            if not abs_path.exists():
                continue
                
            try:
                # Reuse existing calculate_hash method
                file_hash = self.calculate_hash(str(abs_path))
                with self.db.get_connection() as conn:
                    conn.execute("UPDATE books SET file_hash = ? WHERE id = ?", (file_hash, book_id))
                updated += 1
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Failed to hash book {book_id}: {e}")
                
        return updated

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
            cursor.execute("DELETE FROM books_fts WHERE rowid = ?", (book_id,))
            
            return True, f"Book '{title}' deleted and archived."

    def update_metadata(self, book_id, data):
        """Updates book metadata and synchronizes FTS."""
        fields = [
            'title', 'author', 'publisher', 'year', 'isbn', 'msc_class', 
            'summary', 'tags', 'description', 'level', 'audience'
        ]
        updates = []
        params = []
        for f in fields:
            if f in data:
                updates.append(f"{f} = ?")
                params.append(data[f])
        
        if not updates:
            return False, "No fields to update"
            
        params.append(time.time())
        params.append(book_id)
        
        query = f"UPDATE books SET {', '.join(updates)}, last_modified = ? WHERE id = ?"
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            
            # Sync FTS (preserving 'content' column)
            cursor.execute("SELECT content FROM books_fts WHERE rowid = ?", (book_id,))
            fts_row = cursor.fetchone()
            existing_content = fts_row['content'] if fts_row else ""

            cursor.execute("DELETE FROM books_fts WHERE rowid = ?", (book_id,))
            cursor.execute("""
                INSERT INTO books_fts (rowid, title, author, index_content, content)
                SELECT id, title, author, index_text, ? FROM books WHERE id = ?
            """, (existing_content, book_id))
            
        return True, "Metadata updated successfully"

    def check_sanity(self, fix=False):
        """Checks for broken paths and duplicate entries with ranking logic."""
        results = {"broken": [], "duplicates": []}
        
        def rank_candidate(c):
            score = 0
            if "99_General_and_Diverse/Unsorted" in c['path']:
                score += 1000
            score += len(c['path'])
            return score

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, path, title FROM books")
            for row in cursor.fetchall():
                abs_path = LIBRARY_ROOT / row['path']
                try:
                    exists = abs_path.exists()
                except OSError:
                    exists = False

                if not exists:
                    results["broken"].append(dict(row))
                    if fix:
                        cursor.execute("DELETE FROM books WHERE id = ?", (row['id'],))
                        cursor.execute("DELETE FROM books_fts WHERE rowid = ?", (row['id'],))
            
            # Content Duplicate Check
            cursor.execute("SELECT file_hash, COUNT(*) as count FROM books WHERE file_hash IS NOT NULL AND file_hash != '' GROUP BY file_hash HAVING count > 1")
            hash_dups = cursor.fetchall()
            
            for row in hash_dups:
                file_hash = row['file_hash']
                cursor.execute("SELECT id, path, title FROM books WHERE file_hash = ?", (file_hash,))
                candidates = [dict(r) for r in cursor.fetchall()]
                
                candidates.sort(key=rank_candidate)
                best = candidates[0]
                to_delete = candidates[1:]
                
                results["duplicates"].append({"hash": file_hash, "best": best, "redundant": to_delete})
                
                if fix:
                    for item in to_delete:
                        phys_path = LIBRARY_ROOT / item['path']
                        if phys_path.exists():
                            os.remove(phys_path)
                        cursor.execute("DELETE FROM books WHERE id = ?", (item['id'],))
                        cursor.execute("DELETE FROM books_fts WHERE rowid = ?", (item['id'],))

            # Metadata Duplicate Check (ISBN)
            cursor.execute("SELECT isbn, COUNT(*) as count FROM books WHERE isbn IS NOT NULL AND isbn != '' GROUP BY isbn HAVING count > 1")
            isbn_dups = cursor.fetchall()
            for row in isbn_dups:
                isbn = row['isbn']
                cursor.execute("SELECT id, path, title FROM books WHERE isbn = ?", (isbn,))
                candidates = [dict(r) for r in cursor.fetchall()]
                candidates.sort(key=rank_candidate)
                best = candidates[0]
                to_delete = candidates[1:]
                results["duplicates"].append({"isbn": isbn, "best": best, "redundant": to_delete})
                if fix:
                    for item in to_delete:
                        phys_path = LIBRARY_ROOT / item['path']
                        if phys_path.exists(): os.remove(phys_path)
                        cursor.execute("DELETE FROM books WHERE id = ?", (item['id'],))
                        cursor.execute("DELETE FROM books_fts WHERE rowid = ?", (item['id'],))

            # Metadata Duplicate Check (DOI)
            cursor.execute("SELECT doi, COUNT(*) as count FROM books WHERE doi IS NOT NULL AND doi != '' AND doi != 'Unknown' GROUP BY doi HAVING count > 1")
            doi_dups = cursor.fetchall()
            for row in doi_dups:
                doi = row['doi']
                cursor.execute("SELECT id, path, title FROM books WHERE doi = ?", (doi,))
                candidates = [dict(r) for r in cursor.fetchall()]
                candidates.sort(key=rank_candidate)
                best = candidates[0]
                to_delete = candidates[1:]
                results["duplicates"].append({"doi": doi, "best": best, "redundant": to_delete})
                if fix:
                    for item in to_delete:
                        phys_path = LIBRARY_ROOT / item['path']
                        if phys_path.exists(): os.remove(phys_path)
                        cursor.execute("DELETE FROM books WHERE id = ?", (item['id'],))
                        cursor.execute("DELETE FROM books_fts WHERE rowid = ?", (item['id'],))
                
        return results

    def get_book_by_path(self, rel_path):
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM books WHERE path = ?", (rel_path,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def clear_indexes(self, book_ids):
        """Clears index_text and resets index_version for specified book IDs."""
        if not book_ids:
            return False, "No IDs provided"
            
        placeholders = ','.join(['?'] * len(book_ids))
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE books SET index_text = NULL, index_version = 0 WHERE id IN ({placeholders})", book_ids)
            cursor.execute(f"UPDATE books_fts SET index_content = ' ' WHERE rowid IN ({placeholders})", book_ids)
        
        return True, f"Cleared indexes for {len(book_ids)} books."

    def get_file_for_serving(self, book_id):
        """Resolves book file, converting DjVu to PDF if needed, and returns path."""
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT id, path FROM books WHERE id = ?", (book_id,)).fetchone()
        if not row: return None, "Book not found"
        
        abs_path = (LIBRARY_ROOT / row['path']).resolve()
        if not abs_path.exists(): return None, "Physical file missing"
        
        if abs_path.suffix.lower() == '.pdf':
            return abs_path, None
            
        if abs_path.suffix.lower() == '.djvu':
            # Use current_app context or PROJECT_ROOT for cache
            from core.config import PROJECT_ROOT
            cache_dir = PROJECT_ROOT / "static" / "cache" / "pdf"
            cache_dir.mkdir(parents=True, exist_ok=True)
            
            # Consistent cache key: book_id
            pdf_path = cache_dir / f"{book_id}.pdf"
            if not pdf_path.exists():
                import subprocess
                try:
                    subprocess.run(['ddjvu', '-format=pdf', str(abs_path), str(pdf_path)], check=True, stderr=subprocess.DEVNULL)
                except Exception as e:
                    return None, f"DjVu conversion failed: {e}"
            return pdf_path, None
            
        return None, "Unsupported file type"

    def find_language_mismatches(self, limit=50):
        """Identifies books that likely have a language mismatch (e.g. German content, English title)."""
        german_indicators = ["und", "der", "die", "das", "für", "einleitung", "lehrbuch"]
        english_indicators = ["and", "the", "for", "introduction", "textbook"]
        
        mismatches = []
        with self.db.get_connection() as conn:
            # Look for books where the title is English but the review or summary contains German
            rows = conn.execute("""
                SELECT id, title, author, path, summary, zb_review, language 
                FROM books 
                WHERE title IS NOT NULL AND (zb_review IS NOT NULL OR summary IS NOT NULL)
                AND language IS NULL
            """).fetchall()
            
            for row in rows:
                content = (row['zb_review'] or "") + " " + (row['summary'] or "")
                title = row['title'].lower()
                
                content_is_german = any(word in content.lower().split() for word in german_indicators)
                title_is_english = any(word in title.split() for word in english_indicators)
                
                if content_is_german and title_is_english:
                    mismatches.append(dict(row))
                    if len(mismatches) >= limit: break
                    
        return mismatches

    def fix_language_mismatch(self, book_id, preferred_title=None):
        """Attempts to restore the original German title for a book."""
        with self.db.get_connection() as conn:
            book = conn.execute("SELECT id, title, filename, path FROM books WHERE id = ?", (book_id,)).fetchone()
            if not book: return False
            
            new_title = preferred_title
            if not new_title:
                # Try to extract from filename if it looks descriptive
                # e.g. "Author - German Title.pdf"
                fn = book['filename']
                if ' - ' in fn:
                    parts = fn.split(' - ')
                    potential = parts[1].rsplit('.', 1)[0].strip()
                    if len(potential) > 5:
                        new_title = potential
            
            if new_title and new_title != book['title']:
                self.update_metadata(book_id, {'title': new_title, 'language': 'german'})
                return True
        return False

# Global instance
library_service = LibraryService()
