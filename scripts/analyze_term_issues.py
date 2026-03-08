import os
import sys
import sqlite3
import difflib
import re
from collections import defaultdict

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import db

def analyze_terms():
    print("--- MathStudio Term Extraction Diagnostic ---\n")
    
    with db.get_connection() as conn:
        conn.row_factory = sqlite3.Row
        terms = conn.execute("SELECT id, book_id, page_start, name, term_type, latex_content FROM knowledge_terms ORDER BY book_id, page_start").fetchall()

    if not terms:
        print("No terms found in the database. Has Stage 2 finished on any books?")
        return

    # 1. Catching the Leaks ([LaTeX Body], etc.)
    leaks = []
    # 2. Catching "Proof-Only" Terms
    orphaned_proofs = []
    
    for term in terms:
        content = term['latex_content'] or ""
        
        # Check for [LaTeX Body] or similar leaks
        if '[LaTeX Body]' in content or '[LaTeX body]' in content or 'LaTeX Body:' in content:
            leaks.append(term)
            
        # Check for orphaned proofs (starts with Proof, \textbf{Proof}, \noindent\textbf{Proof})
        stripped_content = content.replace('\\noindent', '').replace('\\textbf', '').replace('{', '').replace('}', '').strip()
        if stripped_content.lower().startswith('proof'):
            # Double check it doesn't also contain a theorem env
            if '\\begin{theorem}' not in content.lower() and '\\begin{proposition}' not in content.lower() and '\\begin{lemma}' not in content.lower() and '\\begin{corollary}' not in content.lower():
                orphaned_proofs.append(term)

    print(f"1. FORMATTING LEAKS ([LaTeX Body]): Found {len(leaks)}")
    for t in leaks:
        print(f"  - ID: {t['id']}, Book: {t['book_id']}, Page: {t['page_start']}, Name: {t['name']}")

    print(f"\n2. ORPHANED PROOFS (Missing Theorem): Found {len(orphaned_proofs)}")
    for t in orphaned_proofs:
        print(f"  - ID: {t['id']}, Book: {t['book_id']}, Page: {t['page_start']}, Name: {t['name']}")

    # 3. Catching Semantic Duplicates
    print(f"\n3. SEMANTIC DUPLICATES (>85% Similarity within same book)")
    
    # Group by book
    books = defaultdict(list)
    for term in terms:
        books[term['book_id']].append(term)
        
    duplicate_pairs = []
    
    for book_id, book_terms in books.items():
        # Compare each term with subsequent terms in the same book (up to a few pages ahead)
        for i in range(len(book_terms)):
            for j in range(i + 1, len(book_terms)):
                t1 = book_terms[i]
                t2 = book_terms[j]
                
                # Only compare if they are within 5 pages of each other
                if abs(t2['page_start'] - t1['page_start']) <= 5:
                    c1 = t1['latex_content'] or ""
                    c2 = t2['latex_content'] or ""
                    
                    if not c1 or not c2: continue
                    
                    # Quick length check to avoid expensive diff on wildly different strings
                    if abs(len(c1) - len(c2)) / max(len(c1), len(c2)) > 0.3:
                        continue
                        
                    similarity = difflib.SequenceMatcher(None, c1, c2).ratio()
                    if similarity > 0.85:
                        duplicate_pairs.append((t1, t2, similarity))

    print(f"Found {len(duplicate_pairs)} likely duplicate pairs.")
    for t1, t2, sim in duplicate_pairs:
         print(f"  - {sim*100:.1f}% Match:")
         print(f"      Term A: ID {t1['id']}, Page {t1['page_start']}, Name: '{t1['name']}'")
         print(f"      Term B: ID {t2['id']}, Page {t2['page_start']}, Name: '{t2['name']}'")

    print("\n--- Diagnostic Complete ---")

if __name__ == "__main__":
    analyze_terms()
