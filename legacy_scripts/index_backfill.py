import sqlite3
import fitz  # PyMuPDF
import re
import json
import time
import sys
import signal
from pathlib import Path
from google import genai
from google.genai import types

print("DEBUG: Imports done.")

# --- Configuration ---
DB_FILE = "library.db"
LIBRARY_ROOT = Path("..").resolve()
GEMINI_MODEL = "gemini-2.5-flash-lite-preview-09-2025"
SCAN_PAGES = 50  # Number of pages to scan from the end

# Load API Key
try:
    with open("credentials.json", "r") as f:
        creds = json.load(f)
        GEMINI_API_KEY = creds.get("GEMINI_API_KEY")
except FileNotFoundError:
    print("Error: credentials.json not found.")
    sys.exit(1)

print("DEBUG: Credentials loaded.")

client = genai.Client(api_key=GEMINI_API_KEY)
print("DEBUG: Client initialized.")

def handler(signum, frame):
    raise TimeoutError("API Timeout")

def get_candidates():
    """Finds books with missing or empty index_text."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Check for NULL or empty string, and ensure file exists
    cursor.execute("SELECT id, path, title FROM books WHERE (index_text IS NULL OR index_text = '') AND path LIKE '%.pdf'")
    rows = cursor.fetchall()
    conn.close()
    return rows

def evaluate_page_heuristic(text):
    """
    Returns a score (0-100) indicating satisfied heuristics for an index page.
    """
    score = 0
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines: return 0

    # 1. Header Detection (Top lines)
    header_text = " ".join(lines[:3]).lower()
    if "index" in header_text:
        score += 50
    if "subject index" in header_text or "author index" in header_text:
        score += 70

    # 2. Digit Density at line ends
    lines_with_digits = 0
    total_lines = len(lines)
    for line in lines:
        if re.search(r'\d+$', line):
            lines_with_digits += 1
    
    density = lines_with_digits / max(1, total_lines)
    if density > 0.15: score += 20
    if density > 0.30: score += 20
    
    # Penalty for "Bibliography" or "References"
    if "bibliography" in header_text or "references" in header_text:
        score -= 100

    return max(0, score)

def extract_candidate_pages(doc):
    """
    Scans the last SCAN_PAGES of the PDF document.
    Returns: (concatenated_text, page_count)
    """
    num_pages = len(doc)
    start_page = max(0, num_pages - SCAN_PAGES)
    
    candidate_text = []
    detected_pages = []
    
    for i in range(start_page, num_pages):
        try:
            page = doc[i]
            text = page.get_text()
            score = evaluate_page_heuristic(text)
            
            # Threshold: 40 (Enough to catch "Index" header OR very high density)
            if score >= 40:
                detected_pages.append((i, text))
        except Exception:
            pass
            
    if not detected_pages:
        return None, 0
        
    detected_pages.sort(key=lambda x: x[0])
    full_text = "\n".join([p[1] for p in detected_pages])
    return full_text, len(detected_pages)

def clean_index_with_gemini(raw_text, title):
    """
    Sends raw text to Gemini to clean and structure.
    """
    prompt = f"""
    You are a professional librarian. I have extracted raw text from the back of the math book "{title}".
    It is supposed to be the Index.

    Your Task:
    1. Analyze: Search for an Index section in the text. It might be mixed with ads or bibliography.
    2. Extract & Clean: 
       - Ignore non-index content.
       - Remove headers/footers.
       - Correct OCR errors.
       - Merge lines.
    3. Format: Return the content as a clean, line-separated text list.
       - Format: Term | Page Numbers
       - Example:
         Abelian Group | 5, 12-14
    
    If you result is empty or you are 100% sure there is NO index, return "NOT_INDEX".
    Otherwise, do your best to extract the index.
    
    RAW TEXT START:
    {raw_text[:25000]} 
    RAW TEXT END
    """
    
    signal.signal(signal.SIGALRM, handler)
    signal.alarm(45) # 45 seconds timeout
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt
        )
        signal.alarm(0)
        return response.text.strip()
    except Exception as e:
        signal.alarm(0)
        print(f"  [AI Error] {e}")
        return None

def validate_content(text):
    """
    Strict validation for index content.
    Returns: (bool, reason)
    """
    # Digit density check (Index pages are number-heavy)
    clean_chars = "".join(text.split())
    if not clean_chars:
         return False, "Empty content"

    digit_count = sum(c.isdigit() for c in clean_chars)
    density = digit_count / max(1, len(clean_chars))
    
    if density < 0.05:
        return False, f"Low digit density ({density:.2f})"

    # Structure check (Lines should look like "Term | Page")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    structured_lines = 0
    for line in lines:
        # Check for pipe separator AND digits at the end
        if "|" in line and re.search(r'[\d,\s-]+$', line):
            structured_lines += 1
    
    structure_score = structured_lines / max(1, len(lines))
    if structure_score < 0.2:
        return False, f"Poor structure ({structure_score:.2f})"

    return True, "OK"

def update_db(book_id, clean_text):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE books SET index_version = index_version + 1, last_modified = ?, index_text = ? WHERE id = ?", (time.time(), clean_text, book_id))
        # Update FTS Table
        # Note: FTS5 uses 'rowid' to refer to the contents if mapped
        cursor.execute("UPDATE books_fts SET index_content = ? WHERE rowid = ?", (clean_text, book_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"  [DB Error] {e}")
        return False
    finally:
        conn.close()

def main():
    start_time = time.time()
    candidates = get_candidates()
    print(f"Found {len(candidates)} books missing indexes.")
    
    # Process all remaining books (approx 240 left)
    BATCH_LIMIT = 500 
    processed_count = 0
    success_count = 0
    
    for book_id, rel_path, title in candidates[:BATCH_LIMIT]:
        # Skip Book 6 (Analysis einer Veränderlichen) if it causes hangs
        if book_id == 6:
            print(f"Skipping [6] {title[:20]}... (Excluded)")
            continue

        abs_path = LIBRARY_ROOT / rel_path
        if not abs_path.exists():
            print(f"Skipping missing file: {rel_path}")
            continue

        print(f"\nProcessing [{book_id}] {title[:50]}...")
        
        try:
            doc = fitz.open(abs_path)
            raw_text, page_count = extract_candidate_pages(doc)
            doc.close()
            
            if not raw_text:
                print("  -> No index pages detected (Heuristic).")
                continue
                
            print(f"  -> Detected {page_count} potential index pages inside {len(raw_text)} chars.")
            print("  -> Sending to Gemini...")
            
            clean_text = clean_index_with_gemini(raw_text, title)
            
            if clean_text == "NOT_INDEX":
                print("  -> AI rejected text (Not an index).")
                continue
            
            if not clean_text:
                 print("  -> AI returned empty/error.")
                 continue

            if clean_text:
                # Validation
                is_valid, reason = validate_content(clean_text)
                if is_valid:
                    if update_db(book_id, clean_text):
                        print(f"  -> Success! Indexed updated ({len(clean_text)} chars).")
                        success_count += 1
                else:
                    print(f"  -> Validation Failed: {reason}")
            
            time.sleep(1)
            processed_count += 1
            
        except Exception as e:
            print(f"  -> Error: {e}")

    print(f"\nBatch Complete.")
    print(f"Processed: {processed_count}")
    print(f"Successfully Indexed: {success_count}")
    print(f"Time: {time.time() - start_time:.2f}s")

if __name__ == "__main__":
    main()
