import sqlite3
import re
import sys

DB_FILE = "library.db"

def calculate_metrics(text):
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

    # Structure Score: Percentage of lines that look like "Term | Page"
    # Or at least end with digits/ranges
    structured_lines = 0
    for line in lines:
        # Check for pipe separator AND digits at the end
        if "|" in line and re.search(r'[\d,\s-]+$', line):
            structured_lines += 1
        # Or just checking for standard index pattern: "Term, 123"
        elif re.search(r',\s*[\divxIVX]+(?:[-–][\divxIVX]+)?$', line):
             structured_lines += 1

    structure_score = structured_lines / line_count

    return char_count, line_count, digit_density, structure_score

def audit_indexes():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    print(f"Scanning {DB_FILE} for index quality...")
    
    # Get all books with non-empty index
    cursor.execute("SELECT id, title, index_text FROM books WHERE index_text IS NOT NULL AND length(index_text) > 0")
    rows = cursor.fetchall()
    
    print(f"Found {len(rows)} indexed books.")
    print("-" * 80)
    print(f"{'ID':<5} | {'Title':<40} | {'Len':<6} | {'Dens.':<5} | {'Struct':<5} | {'Flag'}")
    print("-" * 80)

    bad_candidates = []

    for book_id, title, index_text in rows:
        char_count, line_count, density, struct_score = calculate_metrics(index_text)
        
        flags = []
        if char_count < 200:
            flags.append("SHORT")
        if char_count > 50000:
            flags.append("LONG")
        if density < 0.02: # narrative text usually has < 1-2% digits. Indexes > 5-10%
            flags.append("TXT")
        if struct_score < 0.3:
            flags.append("UNSTRUCT")

        if flags:
            title_short = (title[:37] + '...') if len(title) > 37 else title
            print(f"{book_id:<5} | {title_short:<40} | {char_count:<6} | {density:.2f}  | {struct_score:.2f}  | {','.join(flags)}")
            bad_candidates.append(book_id)

    print("-" * 80)
    print(f"Audit Complete. Found {len(bad_candidates)} potentially bad indexes.")
    
    # Optional: Generate a command to clear them?
    if bad_candidates:
        print("\nSQL to clear these for re-indexing:")
        print(f"UPDATE books SET index_text = NULL, index_version = 0 WHERE id IN ({','.join(map(str, bad_candidates))});")
        print(f"UPDATE books_fts SET index_content = ' ' WHERE rowid IN ({','.join(map(str, bad_candidates))});")

    conn.close()

if __name__ == "__main__":
    audit_indexes()
