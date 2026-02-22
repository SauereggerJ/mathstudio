import sqlite3
import fitz # PyMuPDF
from pathlib import Path
import os
import re

DB_FILE = "library.db"
LIBRARY_ROOT = Path("..")
THUMBNAIL_DIR = Path("web/static/thumbnails")

def extract_pdf_data(book_id, file_path):
    if not file_path.exists() or file_path.suffix.lower() != '.pdf':
        return None, []

    try:
        doc = fitz.open(file_path)
        num_pages = len(doc)
        
        # --- 1. Extract Chapters (ToC) ---
        chapters = []
        toc = doc.get_toc() # Returns [level, title, page, ...]
        if toc:
            for level, title, page in toc:
                chapters.append({
                    'title': title,
                    'level': level - 1, # fitz uses 1-based levels
                    'page': page
                })
        else:
            # Fallback: Scan first 20 pages for text-based ToC
            print(f"  No logical ToC for {file_path.name}, scanning text...")
            toc_limit = min(num_pages, 20)
            for i in range(toc_limit):
                text = doc[i].get_text()
                lines = text.splitlines()
                for line in lines:
                    line = line.strip()
                    if len(line) < 5 or len(line) > 120: continue
                    # Match "Chapter 1 ... 5" or "1. Introduction ... 1"
                    match = re.search(r'^((?:Chapter|Section|Part|Appendix)?\s*[\d\.]+\s+.*?)\s+[\.\s]*(\d+)$', line)
                    if match:
                        chapters.append({
                            'title': match.group(1).strip(),
                            'level': 0,
                            'page': int(match.group(2))
                        })
                if len(chapters) > 10: break

        # --- 2. Extract Index Text ---
        index_text = ""
        start_check = max(0, num_pages - 20)
        index_pages = []
        for i in range(num_pages - 1, start_check - 1, -1):
            page_text = doc[i].get_text()
            if "index" in page_text.lower()[:1000]:
                index_pages.append(page_text)
            elif index_pages:
                # Density check for continuing index
                lines = page_text.splitlines()
                if len([l for l in lines if any(c.isdigit() for c in l)]) > len(lines) * 0.3:
                    index_pages.append(page_text)
                else: break
        index_text = "\n".join(reversed(index_pages))

        # --- 3. Generate Thumbnails (First 5 pages) ---
        book_thumb_dir = THUMBNAIL_DIR / str(book_id)
        if not book_thumb_dir.exists():
            book_thumb_dir.mkdir(parents=True)
            for i in range(min(num_pages, 5)):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(0.5, 0.5)) # Scale down
                pix.save(book_thumb_dir / f"page_{i+1}.png")

        doc.close()
        return index_text, chapters

    except Exception as e:
        print(f"  Error processing {file_path.name}: {e}")
        return None, []

def main():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, path FROM books WHERE path LIKE '%.pdf'")
    books = cursor.fetchall()
    
    print(f"Processing {len(books)} books with PyMuPDF...")
    
    for book_id, rel_path in books:
        # For efficiency in this turn, skip if we already have thumbnails 
        # as a proxy for "processed by this new version"
        book_thumb_dir = THUMBNAIL_DIR / str(book_id)
        if (book_thumb_dir / "page_1.png").exists():
            continue

        abs_path = LIBRARY_ROOT / rel_path
        print(f"Analyzing: {abs_path.name}")
        
        index_text, chapters = extract_pdf_data(book_id, abs_path)
        
        if index_text is not None:
            cursor.execute("UPDATE books SET index_text = ? WHERE id = ?", (index_text, book_id))
            
        # Clear old chapters and re-insert (better quality now)
        cursor.execute("DELETE FROM chapters WHERE book_id = ?", (book_id,))
        for chap in chapters:
            cursor.execute('''
                INSERT INTO chapters (book_id, title, level, page)
                VALUES (?, ?, ?, ?)
            ''', (book_id, chap['title'], chap['level'], chap['page']))
            
        conn.commit()

    conn.close()

if __name__ == "__main__":
    main()