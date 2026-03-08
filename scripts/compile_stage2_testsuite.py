import sqlite3
import re
import os
import shutil
from pathlib import Path

# Paths
DB_PATH = "/library/mathstudio/library.db"
CONVERTED_NOTES_DIR = Path("/library/mathstudio/converted_notes")
TESTSUITE_DIR = Path("/library/mathstudio/tests/stage2_dataset")

# Recreate the test suite directory
if TESTSUITE_DIR.exists():
    shutil.rmtree(TESTSUITE_DIR)
TESTSUITE_DIR.mkdir(parents=True, exist_ok=True)

def find_test_cases():
    test_cases = []
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        
        # We look specifically at the books we have already converted pages for
        # Book 554 is completed, Book 287 might have some
        pages = conn.execute("""
            SELECT book_id, page_number, latex_path 
            FROM extracted_pages 
            WHERE status = 'ok'
            ORDER BY book_id, page_number
        """).fetchall()

    print(f"Loaded {len(pages)} pages to analyze.")
    
    # Store page texts in memory for linear scanning
    page_texts = {}
    for p in pages:
        p_path = Path("/library/mathstudio") / p['latex_path']
        if p_path.exists():
            try:
                page_texts[(p['book_id'], p['page_number'])] = p_path.read_text(encoding='utf-8')
            except Exception as e:
                print(f"Error reading {p_path}: {e}")

    # --- Case 1: Theorem on page N, Proof on page N+1 ---
    case1_found = 0
    for (bid, pnum), text in page_texts.items():
        if case1_found >= 5: break
        if "\\begin{theorem}" in text or "\\begin{lemma}" in text or "\\begin{proposition}" in text:
            # Check if there's no proof on this page, but there is on the next
            if "\\begin{proof}" not in text:
                next_text = page_texts.get((bid, pnum + 1), "")
                if "\\begin{proof}" in next_text:
                    test_cases.append({
                        "name": f"case1_spanning_proof_{bid}_p{pnum}",
                        "description": "Theorem starts on Page N, Proof starts on Page N+1.",
                        "pages": [(bid, pnum), (bid, pnum+1), (bid, pnum+2)]
                    })
                    case1_found += 1

    # --- Case 2: Heavily embedded inline definitions (e.g. bolded text mid-paragraph) ---
    case2_found = 0
    for (bid, pnum), text in page_texts.items():
        if case2_found >= 5: break
        # Look for pages that have lots of \textbf or \emph but NO explicit \begin{definition}
        if "\\begin{definition}" not in text and "\\textbf{" in text and "we define" in text.lower():
            test_cases.append({
                "name": f"case2_embedded_def_{bid}_p{pnum}",
                "description": "Embedded text definition without explicit theorem environment.",
                "pages": [(bid, pnum), (bid, pnum+1), (bid, pnum+2)]
            })
            case2_found += 1

    # --- Case 3: Very short theorem, immediate proof, multiple on same page ---
    case3_found = 0
    for (bid, pnum), text in page_texts.items():
        if case3_found >= 5: break
        theorem_count = sum(1 for tag in ["\\begin{theorem}", "\\begin{lemma}", "\\begin{corollary}"] if tag in text)
        proof_count = text.count("\\begin{proof}")
        if theorem_count >= 2 and proof_count >= 2:
            test_cases.append({
                "name": f"case3_dense_page_{bid}_p{pnum}",
                "description": "Multiple theorems and proofs packed into a single page.",
                "pages": [(bid, pnum), (bid, pnum+1), (bid, pnum+2)]
            })
            case3_found += 1
            
    # --- Case 4: Postponed / Disconnected proofs ---
    case4_found = 0
    for (bid, pnum), text in page_texts.items():
        if case4_found >= 5: break
        # Proof of theorem 1.2 ...
        if re.search(r"\\begin\{proof\}\[Proof of Theorem", text, re.IGNORECASE):
            test_cases.append({
                "name": f"case4_postponed_proof_{bid}_p{pnum}",
                "description": "Explicit postponed proof referencing a previous theorem.",
                "pages": [(bid, pnum-1), (bid, pnum), (bid, pnum+1)]
            })
            case4_found += 1

    # --- Case 5: Extremely long proof spanning 2+ pages ---
    case5_found = 0
    for (bid, pnum), text in page_texts.items():
        if case5_found >= 5: break
        if "\\begin{proof}" in text and "\\end{proof}" not in text:
            next_text = page_texts.get((bid, pnum+1), "")
            if "\\end{proof}" not in next_text:
                test_cases.append({
                    "name": f"case5_long_proof_{bid}_p{pnum}",
                    "description": "Proof spans across more than 2 pages.",
                    "pages": [(bid, pnum), (bid, pnum+1), (bid, pnum+2)]
                })
                case5_found += 1

    # --- Case 6: Random samples ---
    import random
    
    all_pages = list(page_texts.keys())
    used_pages = set()
    for tc in test_cases:
        for b, p in tc["pages"]:
            used_pages.add((b, p))
            
    available_pages = [p for p in all_pages if p not in used_pages and len(page_texts.get(p, "").strip()) > 100]
    random.seed(42) # For consistent results
    
    random_samples = random.sample(available_pages, min(15, len(available_pages)))
    for idx, (bid, pnum) in enumerate(random_samples):
        test_cases.append({
            "name": f"case6_random_{bid}_p{pnum}_{idx}",
            "description": "Randomly selected page for general quality testing.",
            "pages": [(bid, pnum), (bid, pnum+1), (bid, pnum+2)]
        })

    # Save cases to disk
    import json
    metadata = []
    print(f"Found {len(test_cases)} edge cases and random samples.")
    
    for tc in test_cases:
        case_dir = TESTSUITE_DIR / tc["name"]
        case_dir.mkdir(exist_ok=True)
        
        # Save contexts
        context_files = []
        for i, (b, p) in enumerate(tc["pages"]):
            content = page_texts.get((b, p), "")
            if content:
                file_name = f"page_{p}.tex"
                (case_dir / file_name).write_text(content, encoding='utf-8')
                context_files.append({"book_id": b, "page_number": p, "file": file_name})
                
        metadata.append({
            "name": tc["name"],
            "description": tc["description"],
            "context_files": context_files
        })
        
    (TESTSUITE_DIR / "manifest.json").write_text(json.dumps(metadata, indent=2))
    print(f"Successfully wrote test suite to {TESTSUITE_DIR}")

if __name__ == "__main__":
    find_test_cases()
