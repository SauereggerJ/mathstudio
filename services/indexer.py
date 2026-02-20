import subprocess
import sqlite3
import re
import os
import json
import time
import fitz
from pathlib import Path
from pypdf import PdfReader
from core.database import db
from core.config import LIBRARY_ROOT, IGNORED_FOLDERS
from core.ai import ai
from core.utils import PDFHandler
from .bibliography import bibliography_service

class IndexerService:
    def __init__(self):
        self.db = db
        self.ai = ai

    def extract_full_text(self, file_path):
        """Extracts full text from a PDF/DjVu file with page markers."""
        text_content = []
        
        if file_path.suffix.lower() == '.pdf':
            try:
                reader = PdfReader(file_path)
                for i, page in enumerate(reader.pages):
                    text = page.extract_text()
                    if text:
                        cleaned = " ".join(text.split())
                        text_content.append(f" [[PAGE_{i+1}]] {cleaned}")
            except Exception as e:
                print(f"[Indexer] PDF Error {file_path.name}: {e}")
                
        elif file_path.suffix.lower() == '.djvu':
            import shutil
            if shutil.which('djvutxt'):
                try:
                    result = subprocess.run(['djvutxt', str(file_path)], capture_output=True, text=True, check=True)
                    pages = result.stdout.split('\f')
                    for i, page_text in enumerate(pages):
                        if page_text.strip():
                            cleaned = " ".join(page_text.split())
                            text_content.append(f" [[PAGE_{i+1}]] {cleaned}")
                except Exception as e:
                    print(f"[Indexer] DjVu Error {file_path.name}: {e}")
        
        return " ".join(text_content)

    def deep_index_book(self, book_id):
        """Performs page-level indexing for a specific book."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT path, filename FROM books WHERE id = ?", (book_id,))
            row = cursor.fetchone()
            if not row:
                return False, "Book not found"
            
            rel_path, filename = row['path'], row['filename']
            abs_path = LIBRARY_ROOT / rel_path
            
            if not abs_path.exists():
                return False, f"File not found: {rel_path}"
            
            print(f"Deep indexing: {filename} (ID: {book_id})")
            
            pages_data = []
            if abs_path.suffix.lower() == '.pdf':
                try:
                    reader = PdfReader(abs_path)
                    for i, page in enumerate(reader.pages):
                        text = page.extract_text()
                        if text:
                            cleaned = " ".join(text.split())
                            pages_data.append((book_id, i + 1, cleaned))
                except Exception as e:
                    return False, f"PDF Error: {e}"
                    
            elif abs_path.suffix.lower() == '.djvu':
                import shutil
                if shutil.which('djvutxt'):
                    try:
                        result = subprocess.run(['djvutxt', str(abs_path)], capture_output=True, text=True, check=True)
                        pages = result.stdout.split('\f')
                        for i, page_text in enumerate(pages):
                            if page_text.strip():
                                cleaned = " ".join(page_text.split())
                                pages_data.append((book_id, i + 1, cleaned))
                    except Exception as e:
                        return False, f"DjVu Error: {e}"
                else:
                    return False, "djvutxt tool not found"
            
            if not pages_data:
                return False, "No text extracted"

            cursor.execute("DELETE FROM pages_fts WHERE book_id = ?", (book_id,))
            cursor.executemany(
                "INSERT INTO pages_fts (book_id, page_number, content) VALUES (?, ?, ?)",
                pages_data
            )
            
            # Register as deep indexed
            cursor.execute("INSERT OR REPLACE INTO deep_indexed_books (book_id) VALUES (?)", (book_id,))
            
        return True, f"Deep indexed {len(pages_data)} pages"
    def scan_library(self, force=False):
        """Scans the library directory and updates the database."""
        count_new = 0
        count_updated = 0
        
        # We need the metadata service for resolution
        from .metadata import metadata_service
        
        print(f"Scanning library in: {LIBRARY_ROOT.resolve()}")
        
        # Walk library root
        for root, dirs, files in os.walk(LIBRARY_ROOT):
            # Skip ignored folders
            dirs[:] = [d for d in dirs if d not in IGNORED_FOLDERS and not d.startswith('.')]
            
            for file in files:
                file_path = Path(root) / file
                if file_path.suffix.lower() not in {'.pdf', '.djvu', '.epub'}:
                    continue
                    
                try:
                    rel_path = str(file_path.relative_to(LIBRARY_ROOT))
                    mtime = file_path.stat().st_mtime
                    size = file_path.stat().st_size
                    
                    with self.db.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute("SELECT id, last_modified, index_version FROM books WHERE path = ?", (rel_path,))
                        existing = cursor.fetchone()
                        
                        if not existing:
                            print(f"Processing new file: {file}")
                            # Simplified resolution for now, using stem
                            meta = {'title': file_path.stem, 'author': 'Unknown'}
                            # Try to be smarter if it looks like "Author - Title"
                            parts = file_path.stem.split(' - ')
                            if len(parts) >= 2:
                                meta['author'] = parts[0].strip()
                                meta['title'] = " - ".join(parts[1:]).strip()

                            cursor.execute('''
                                INSERT INTO books (filename, path, directory, author, title, size_bytes, last_modified, index_version)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            ''', (file, rel_path, str(file_path.parent.relative_to(LIBRARY_ROOT)), 
                                  meta['author'], meta['title'], size, mtime, 1))
                            
                            book_id = cursor.lastrowid
                            full_text = self.extract_full_text(file_path)
                            cursor.execute('INSERT INTO books_fts (rowid, title, author, content) VALUES (?, ?, ?, ?)', 
                                           (book_id, meta['title'], meta['author'], full_text))
                            
                            # Start Bibliography Extraction (Phase 2)
                            try:
                                bibliography_service.process_book_bibliography(book_id)
                            except Exception as e:
                                print(f"  [BIB] Failed to process bibliography for {file}: {e}")

                            count_new += 1
                        else:
                            book_id, db_mtime, db_version = existing['id'], existing['last_modified'], existing['index_version']
                            needs_update = force or (db_mtime is None or abs(mtime - db_mtime) > 1.0) or (db_version is None or db_version < 1)

                            if needs_update:
                                 print(f"Updating indexed file: {file}")
                                 full_text = self.extract_full_text(file_path)
                                 
                                 cursor.execute('''
                                    UPDATE books SET size_bytes=?, last_modified=?, index_version=? WHERE id=?
                                 ''', (size, mtime, 1, book_id))
                                 
                                 cursor.execute("DELETE FROM books_fts WHERE rowid = ?", (book_id,))
                                 # We fetch current title/author from DB to preserve metadata
                                 cursor.execute("SELECT title, author FROM books WHERE id = ?", (book_id,))
                                 row = cursor.fetchone()
                                 cursor.execute('INSERT INTO books_fts (rowid, title, author, content) VALUES (?, ?, ?, ?)', 
                                                (book_id, row['title'], row['author'], full_text))
                                 
                                 # Start Bibliography Extraction (Phase 2)
                                 try:
                                     bibliography_service.process_book_bibliography(book_id)
                                 except Exception as e:
                                     print(f"  [BIB] Failed to process bibliography for {file}: {e}")

                                 count_updated += 1

                except Exception as e:
                    print(f"Error processing {file}: {e}")
        
        return count_new, count_updated

    def evaluate_page_heuristic(self, text):
        score = 0
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if not lines: return 0
        header_text = " ".join(lines[:3]).lower()
        if "index" in header_text: score += 50
        if "subject index" in header_text or "author index" in header_text: score += 70
        lines_with_digits = sum(1 for l in lines if re.search(r'\d+$', l))
        density = lines_with_digits / max(1, len(lines))
        if density > 0.15: score += 20
        if density > 0.30: score += 20
        if "bibliography" in header_text or "references" in header_text: score -= 100
        return max(0, score)

    def extract_index_candidates(self, file_path):
        handler = PDFHandler(file_path)
        # Use total page count from djvused/pypdf if available
        if file_path.suffix.lower() == '.djvu':
            import subprocess
            res = subprocess.run(['djvused', '-e', 'n', str(file_path)], capture_output=True, text=True)
            num_pages = int(res.stdout.strip()) if res.returncode == 0 else 100
        else:
            doc_tmp = fitz.open(file_path)
            num_pages = len(doc_tmp)
            doc_tmp.close()

        start_page = max(0, num_pages - 50)
        sample_indices = list(range(start_page, num_pages))
        
        # Open source with sample indices (handles DjVu conversion automatically)
        doc, t_path = handler._open_source(page_indices=sample_indices)
        detected = []
        try:
            for i in range(len(doc)):
                text = doc[i].get_text()
                if self.evaluate_page_heuristic(text) >= 40:
                    detected.append(text)
        finally:
            doc.close()
            if t_path and t_path.exists(): t_path.unlink()
            
        return "\n".join(detected) if detected else None

    def reconstruct_index(self, book_id):
        """AI-driven back-of-book index reconstruction."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT path, title FROM books WHERE id = ?", (book_id,))
            row = cursor.fetchone()
            if not row: return False, "Book not found"
            
            abs_path = LIBRARY_ROOT / row['path']
            if not abs_path.exists(): return False, "File missing"
            
            raw_text = self.extract_index_candidates(abs_path)
            if not raw_text: return False, "No index pages detected"
            
            prompt = (
                f"You are a professional librarian. I have extracted raw text from the back of '{row['title']}'.\n"
                "Extract and clean the Index. Format: Term | Page Numbers. Return 'NOT_INDEX' if none found.\n\n"
                f"Text:\n{raw_text[:25000]}"
            )
            
            clean_text = self.ai.generate_text(prompt)
            if not clean_text or clean_text == "NOT_INDEX": return False, "AI failed or rejected index"
            
            # Simplified validation
            digit_count = sum(c.isdigit() for c in clean_text)
            if digit_count / max(1, len(clean_text)) < 0.05: return False, "Poor index quality (density)"
            
            cursor.execute("UPDATE books SET index_text = ?, last_modified = ? WHERE id = ?", (clean_text, time.time(), book_id))
            cursor.execute("UPDATE books_fts SET index_content = ? WHERE rowid = ?", (clean_text, book_id))
            
        return True, f"Index updated ({len(clean_text)} chars)"

    def calculate_toc_metrics(self, toc_data, page_count):
        """Analyzes TOC structure and returns quality metrics."""
        if not toc_data or not isinstance(toc_data, list):
            return 0, 0, 0, []

        count = len(toc_data)
        max_level = 0
        max_page = 0
        out_of_order = 0
        last_p = -1
        
        for item in toc_data:
            p = 0
            lvl = 0
            if isinstance(item, dict):
                p = item.get('pdf_page') or item.get('page') or 0
                lvl = item.get('level', 0)
            elif isinstance(item, list) and len(item) >= 2:
                lvl = item[0]
                p = item[2] if len(item) > 2 else 0
            
            if lvl > max_level: max_level = lvl
            if p > max_page: max_page = p
            if p < last_p and p > 0: out_of_order += 1
            if p > 0: last_p = p

        flags = []
        if count < 5: flags.append("SHORT")
        if max_level == 0 and count > 10: flags.append("FLAT")
        if page_count and max_page < (page_count * 0.7): flags.append("INCOMPLETE")
        if out_of_order > 0: flags.append("DISORDERED")

        return count, max_level, max_page, flags

    def audit_tocs(self):
        """Scans the database for low-quality Tables of Contents."""
        results = []
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, title, toc_json, page_count FROM books")
            for row in cursor.fetchall():
                toc_data = []
                if row['toc_json']:
                    try: toc_data = json.loads(row['toc_json'])
                    except: continue
                
                count, depth, max_p, flags = self.calculate_toc_metrics(toc_data, row['page_count'])
                
                if not toc_data: flags.append("MISSING")
                
                if flags:
                    results.append({
                        "id": row['id'],
                        "title": row['title'],
                        "count": count,
                        "depth": depth,
                        "coverage": f"{max_p}/{row['page_count'] or '?'}",
                        "flags": flags
                    })
        return results

    def repair_missing_tocs(self):
        """Attempts to extract native PDF bookmarks for books with missing TOCs."""
        repaired = 0
        import fitz
        
        # We need IngestorService for sync_chapters
        from .ingestor import ingestor_service
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, path, title FROM books WHERE toc_json IS NULL OR toc_json = '[]' OR toc_json = ''")
            candidates = cursor.fetchall()
            
        print(f"Attempting to repair {len(candidates)} books with missing TOCs...")
        
        for row in candidates:
            book_id = row['id']
            abs_path = LIBRARY_ROOT / row['path']
            
            if not abs_path.exists() or abs_path.suffix.lower() != '.pdf':
                continue
                
            try:
                doc = fitz.open(abs_path)
                toc = doc.get_toc()
                doc.close()
                
                if toc:
                    print(f"  [FIX] Found {len(toc)} bookmarks for '{row['title']}'")
                    ingestor_service.sync_chapters(book_id, toc)
                    repaired += 1
            except Exception as e:
                print(f"  [ERR] Failed to read bookmarks for {row['title']}: {e}")
                
        return repaired

    def calculate_index_metrics(self, text):
        if not text:
            return 0, 0, 0, 0

        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if not lines:
            return 0, 0, 0, 0

        char_count = len(text)
        line_count = len(lines)
        
        # Digit density: Count digits / total chars (ignoring whitespace)
        clean_text = "".join(text.split())
        digit_count = sum(c.isdigit() for c in clean_text)
        digit_density = digit_count / max(1, len(clean_text))

        # Structure Score: Percentage of lines that look like "Term | Page" or "Term, 123"
        structured_lines = 0
        for line in lines:
            if "|" in line and re.search(r'[\d,\s-]+$', line):
                structured_lines += 1
            elif re.search(r',\s*[\divxIVX]+(?:[-–][\divxIVX]+)?$', line):
                 structured_lines += 1

        structure_score = structured_lines / line_count
        return char_count, line_count, digit_density, structure_score

    def audit_indexes(self):
        """Scans the database for low-quality indexes."""
        results = []
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, title, index_text FROM books WHERE index_text IS NOT NULL AND length(index_text) > 0")
            for row in cursor.fetchall():
                char_count, line_count, density, struct_score = self.calculate_index_metrics(row['index_text'])
                
                flags = []
                if char_count < 200: flags.append("SHORT")
                if char_count > 50000: flags.append("LONG")
                if density < 0.02: flags.append("TXT")
                if struct_score < 0.3: flags.append("UNSTRUCT")

                if flags:
                    results.append({
                        "id": row['id'], 
                        "title": row['title'], 
                        "len": char_count, 
                        "density": density, 
                        "struct": struct_score, 
                        "flags": flags
                    })
        return results

# Global instance
indexer_service = IndexerService()
