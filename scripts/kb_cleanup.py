#!/usr/bin/env python3
import sqlite3
import re
import sys
import os
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.database import db
from core.search_engine import es_client

# 1. Structural Noise Blacklist (Aggressive)
STRUCTURAL_KEYWORDS = [
    'Contents', 'Table of Contents', 'Index', 'Bibliography', 'Preface', 
    'Notation', 'Dedication', 'Acknowledgements', 'Copyright', 
    'Series List', 'Title Page', 'Foreword', 'Introduction',
    'Exercises', 'References', 'Epilogue', 'Appendix', 'Cover',
    'Oxford Graduate Texts'
]

STRICT_BLACKLIST_NAMES = [
    '•', '*', '.', '-', 'Page', 'Introduction to Modern Analysis', 'Introduction'
]

# 2. Aggressive Garbage Detection
def is_garbage(term: dict) -> bool:
    name = (term['name'] or "").strip()
    latex = (term['latex_content'] or "").strip()
    
    # Check 1: Strict name matching
    if name in STRICT_BLACKLIST_NAMES:
        return True
        
    # Check 2: Substring-based structural noise
    for kw in STRUCTURAL_KEYWORDS:
        if kw.lower() in name.lower():
            return True
            
    # Check 3: Technical Fragments (Page numbers, just numbers, etc.)
    if re.match(r'^Page \d+$', name):
        return True
    if len(name) < 3 and not re.match(r'^[a-zA-Z]$', name):
        return True
        
    # Check 4: Marker-only bodies (The "Theorem 10.4" problem)
    if "% Term:" in latex or "marker:" in latex.lower():
        # These are AI-generated placeholders or fragments
        return True

    # Check 5: Self-referential or extremely short bodies
    clean_latex = re.sub(r'\\begin\{[^}]+\}|\\end\{[^}]+\}|\\textbf|\\textit|%|Term:|marker:', '', latex).strip()
    if len(clean_latex) < 100:
        # If it's short AND doesn't look like a real definition
        if not re.search(r'[\$\\]', clean_latex) or clean_latex.lower() == name.lower():
            return True
        # If the only content is the name itself
        if clean_latex.lower().replace('.', '').strip() == name.lower().replace('.', '').strip():
            return True
            
    # Check 6: Bibliography/Citation Noise (The "hallucinated corollary" problem)
    # If the body contains many citations/textit entries and lacks substantial math
    citation_count = len(re.findall(r'\\textit|\\cite|\(\d{4}\)', latex))
    formula_count = len(re.findall(r'[\$]|\\\[', latex))
    
    if citation_count > 15: # Highly likely to be a list
        if formula_count < (citation_count * 4): # Lists often have many $ for symbols but not real dense math
            return True

    return False

# 3. Content Sanitization (Per-Book Footers)
# Key: book_id, Value: regex pattern to remove
FOOTER_PATTERNS = {
    238: r'Introduction to Modern Analysis\s*•\s*Shmuel Kantorovitz and Ami Viselter\s*•\s*Page\s*\d+',
    # Add other books here as discovered
}

def clean_latex(latex: str, book_id: int) -> str:
    if book_id in FOOTER_PATTERNS:
        pattern = FOOTER_PATTERNS[book_id]
        latex = re.sub(pattern, '', latex, flags=re.IGNORECASE | re.DOTALL)
    
    # Common artifacts
    latex = re.sub(r'% --- PAGE \d+ ---', '', latex)
    return latex.strip()

def run_cleanup():
    print("═══ Knowledge Base Cleanup Initialized ═══")
    
    with db.get_connection() as conn:
        conn.row_factory = sqlite3.Row
        all_terms = conn.execute("SELECT id, name, book_id, latex_content FROM knowledge_terms").fetchall()
    
    deleted_ids = []
    updated_terms = []
    
    for term in all_terms:
        # Check Stage 1: Deletion
        if is_garbage(term):
            deleted_ids.append(term['id'])
            continue
            
        # Check Stage 2: Sanitization
        cleaned = clean_latex(term['latex_content'] or "", term['book_id'])
        if cleaned != (term['latex_content'] or "").strip():
            updated_terms.append((cleaned, term['id']))

    # Execute Deletions
    if deleted_ids:
        print(f"Purging {len(deleted_ids)} structural noise terms...")
        with db.get_connection() as conn:
            query = f"DELETE FROM knowledge_terms WHERE id IN ({','.join(['?']*len(deleted_ids))})"
            conn.execute(query, deleted_ids)
            # Re-sync FTS
            conn.execute(f"DELETE FROM knowledge_terms_fts WHERE rowid IN ({','.join(['?']*len(deleted_ids))})", deleted_ids)
        
        # ES Deletion
        for tid in deleted_ids:
            try:
                es_client.delete(index="mathstudio_terms", id=str(tid), ignore=[404])
            except Exception: pass

    # Execute Updates
    if updated_terms:
        print(f"Sanitizing content for {len(updated_terms)} terms...")
        with db.get_connection() as conn:
            conn.executemany("UPDATE knowledge_terms SET latex_content = ? WHERE id = ?", updated_terms)
            # FTS Update (simplified)
            for latex, tid in updated_terms:
                conn.execute("UPDATE knowledge_terms_fts SET latex_content = ? WHERE rowid = ?", (latex, tid))
        
        # ES Update
        from elasticsearch.helpers import bulk
        actions = []
        for latex, tid in updated_terms:
            actions.append({
                "_op_type": "update",
                "_index": "mathstudio_terms",
                "_id": str(tid),
                "doc": {"latex_content": latex}
            })
            if len(actions) >= 100:
                bulk(es_client, actions)
                actions = []
        if actions: bulk(es_client, actions)

    print(f"\nCleanup Complete!")
    print(f"- Terms deleted: {len(deleted_ids)}")
    print(f"- Terms sanitized: {len(updated_terms)}")

if __name__ == "__main__":
    run_cleanup()
