
import sqlite3
import re
import statistics
from collections import Counter

DB_PATH = "library.db"

def get_potential_page_number(text):
    if not text: return []
    start_snippet = text[:100]
    start_matches = re.findall(r'(?:^|[\s\.])(\d{1,4})(?:$|[\s\.])', start_snippet)
    end_snippet = text[-100:]
    end_matches = re.findall(r'(?:^|[\s\.])(\d{1,4})(?:$|[\s\.])', end_snippet)
    return list(set(start_matches + end_matches))

def align_library():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    books = cursor.execute("SELECT id, title FROM books").fetchall()
    print(f"Starting alignment for {len(books)} books...")

    stats = {"aligned": 0, "skipped": 0, "failed": 0}

    for book in books:
        book_id = book['id']
        title = book['title']
        
        pages = cursor.execute("""
            SELECT page_number, content FROM pages_fts 
            WHERE book_id = ? 
            ORDER BY page_number ASC
        """, (book_id,)).fetchall()
        
        if not pages:
            stats["skipped"] += 1
            continue

        offsets = []
        sample_size = min(len(pages), 20)
        mid = len(pages) // 2
        start_idx = max(0, mid - sample_size // 2)
        sample = pages[start_idx : start_idx + sample_size]

        for p in sample:
            pdf_page = p['page_number']
            candidates = get_potential_page_number(p['content'])
            for c in candidates:
                printed_page = int(c)
                if 0 < printed_page < 2000:
                    offsets.append(pdf_page - printed_page)

        if not offsets:
            stats["failed"] += 1
            continue

        count = Counter(offsets)
        common_offset, occurrences = count.most_common(1)[0]

        if occurrences >= 4:
            print(f"  [MATCH] {title[:40]:40} | Offset: {common_offset:3} ({occurrences} pages agree)")
            cursor.execute("UPDATE books SET page_offset = ? WHERE id = ?", (common_offset, book_id))
            chapters = cursor.execute("SELECT id, page FROM chapters WHERE book_id = ?", (book_id,)).fetchall()
            for ch in chapters:
                curr_p = ch['page']
                if curr_p < 1000: 
                    new_p = curr_p + common_offset
                    cursor.execute("UPDATE chapters SET page = ? WHERE id = ?", (new_p, ch['id']))
            stats["aligned"] += 1
        else:
            stats["failed"] += 1

    conn.commit()
    conn.close()
    print("\nAlignment Complete!")
    print(f"  Aligned: {stats['aligned']}")
    print(f"  Failed:  {stats['failed']}")
    print(f"  Skipped: {stats['skipped']} (No FTS data)")

if __name__ == "__main__":
    align_library()
