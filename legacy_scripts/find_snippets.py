import sqlite3
import re

DB_FILE = "library.db"

def get_snippets(book_id, query):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        # Get Path for verification
        cursor.execute("SELECT path FROM books WHERE id = ?", (book_id,))
        res = cursor.fetchone()
        if not res: return None, []
        path = res[0]
        
        cursor.execute("""
            SELECT highlight(books_fts, 2, '<b>', '</b>') 
            FROM books_fts 
            WHERE rowid = ? AND books_fts MATCH ?
        """, (book_id, query))
        
        row = cursor.fetchone()
        if not row: return path, []
        
        highlighted = row[0]
        results = []
        page_pattern = re.compile(r'\[\[PAGE_(\d+)\]\]')
        
        start_tag = "<b>"
        end_tag = "</b>"
        current_pos = 0
        
        while len(results) < 5: # Get top 5 matches per book
            idx = highlighted.find(start_tag, current_pos)
            if idx == -1: break
            
            # Find page number (search backwards)
            search_back_limit = max(0, idx - 15000)
            preceding = highlighted[search_back_limit:idx]
            page_matches = list(page_pattern.finditer(preceding))
            page = page_matches[-1].group(1) if page_matches else "?"
            
            # Extract snippet
            end_idx = highlighted.find(end_tag, idx)
            snippet_start = max(0, idx - 100)
            snippet_end = min(len(highlighted), end_idx + 150)
            
            # Clean snippet
            snippet_raw = highlighted[snippet_start:snippet_end]
            snippet = snippet_raw.replace('\n', ' ').replace('\r', '')
            
            results.append({'page': page, 'snippet': snippet})
            current_pos = end_idx + len(end_tag)
            
        return path, results
    finally:
        conn.close()

target_ids = [883, 855, 869, 858, 955]
query = '"minimal polynomial"'

for bid in target_ids:
    print(f"--- Book ID {bid} ---")
    path, snippets = get_snippets(bid, query)
    if path:
        print(f"Path: {path}")
        for s in snippets:
            print(f"Page {s['page']}: ...{s['snippet']}...")