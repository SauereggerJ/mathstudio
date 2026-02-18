import os
import sqlite3
import subprocess
import re
from pathlib import Path

DB_FILE = "library.db"
LIBRARY_ROOT = Path("..")
THUMBNAIL_DIR = Path("web/static/thumbnails")

def parse_djvu_outline(djvu_output):
    """
    Parses `djvudump` output for bookmarks.
    The output format is S-Expression like:
    (bookmarks
     ("Title" "#Page" ...children...)
    )
    """
    # Extract just the bookmarks section
    start = djvu_output.find("(bookmarks")
    if start == -1: return []
    
    # Simple S-Expr parser
    # We tokenize by quoting strings and separating parentheses
    tokens = re.findall(r'\(|\)|"[^"]*"', djvu_output[start:])
    
    chapters = []
    stack = [] # Stores (current_list, level)
    
    # We expect structure: ( "Title" "#Page" ... )
    
    def parse_rec(token_iter, level=0):
        items = []
        while True:
            try:
                token = next(token_iter)
            except StopIteration:
                break
                
            if token == '(':
                # Start of a new list (could be bookmarks root or a chapter node)
                sub_items = parse_rec(token_iter, level + 1)
                
                # Analyze sub_items to see if it's a chapter node
                # A chapter node usually starts with two strings: "Title" "#Page"
                if len(sub_items) >= 2 and isinstance(sub_items[0], str) and isinstance(sub_items[1], str) and sub_items[1].startswith("#"):
                    title = sub_items[0]
                    page_str = sub_items[1]
                    try:
                        page = int(page_str.replace("#", ""))
                        chapters.append({'title': title, 'level': level - 2, 'page': page}) # level - 2 because (bookmarks ( is level 0, 1
                    except: pass
                
                items.append(sub_items)
            elif token == ')':
                return items
            else:
                # String literal
                items.append(token.strip('"'))
        return items

    iter_tokens = iter(tokens)
    parse_rec(iter_tokens)
    return chapters

def extract_djvu_content(book_id, file_path):
    if not file_path.exists():
        print(f"[ERROR] File not found: {file_path}")
        return False

    print(f"Processing DJVU: {file_path.name}")
    
    # 1. Generate Thumbnails
    book_thumb_dir = THUMBNAIL_DIR / str(book_id)
    book_thumb_dir.mkdir(parents=True, exist_ok=True)
        
    for i in range(1, 6):
        output_png = book_thumb_dir / f"page_{i}.png"
        output_ppm = book_thumb_dir / f"page_{i}.ppm"
        
        if output_png.exists() and output_png.stat().st_size > 0:
            continue
            
        try:
            # Generate PPM
            cmd_ddjvu = ['ddjvu', '-format=ppm', f'-page={i}', '-scale=100', str(file_path), str(output_ppm)]
            res = subprocess.run(cmd_ddjvu, capture_output=True, text=True)
            
            if output_ppm.exists():
                # Convert to PNG using shell redirection which is often more reliable for pnmtopng in these contexts
                cmd_conv = f"pnmtopng '{str(output_ppm)}' > '{str(output_png)}'"
                res_conv = subprocess.run(cmd_conv, shell=True, stderr=subprocess.PIPE)
                
                if res_conv.returncode != 0:
                     print(f"  [!] pnmtopng failed for page {i}: {res_conv.stderr.decode('utf-8', errors='ignore')}")
                
                # Cleanup PPM only if PNG was created successfully
                if output_png.exists() and output_png.stat().st_size > 0:
                    output_ppm.unlink()
                    print(f"  + Generated thumbnail page {i}")
                else:
                    print(f"  [!] PNG empty or missing for page {i}")
            else:
                if i == 1:
                    print(f"  [!] ddjvu failed to generate PPM for page {i}. Stderr: {res.stderr}")
                
        except Exception as e:
            print(f"  [!] Error page {i}: {e}")

    # 2. Extract Structure
    chapters = []
    try:
        res = subprocess.run(['djvudump', str(file_path)], capture_output=True, text=True, errors='ignore')
        if "(bookmarks" in res.stdout:
            chapters = parse_djvu_outline(res.stdout)
            print(f"  + Found {len(chapters)} chapters")
    except Exception as e:
        print(f"  [!] Error dumping djvu: {e}")

    return chapters

def main():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, path FROM books WHERE path LIKE '%.djvu' OR path LIKE '%.DJVU'")
    djvu_books = cursor.fetchall()
    
    print(f"Found {len(djvu_books)} DJVU books.")
    
    for book_id, rel_path in djvu_books:
        abs_path = LIBRARY_ROOT / rel_path
        chapters = extract_djvu_content(book_id, abs_path)
        
        if chapters:
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
