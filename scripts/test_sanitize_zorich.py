import sqlite3
import json
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ai import ai
from core.database import db

def test_sanitize_batch():
    print("--- Fetching Test Batch (Zorich Wonky Terms) ---")
    
    with db.get_connection() as conn:
        # Heuristic: contains ' is ' and ' the ', lacks '\text{'
        terms = conn.execute("""
            SELECT id, name, latex_content 
            FROM knowledge_terms 
            WHERE (book_id IN (554, 510))
              AND (latex_content LIKE '% is %' OR latex_content LIKE '% the %') 
              AND latex_content NOT LIKE '%\text{%'
            LIMIT 25
        """).fetchall()

    if not terms:
        print("No wonky terms found in Zorich books.")
        return

    term_map = {t['id']: t['latex_content'] for t in terms}
    
    header = (
        "You are a mathematical LaTeX expert. Your task is to REPAIR mathematical snippets where English prose is mixed with LaTeX without proper formatting.\n\n"
        "RULES:\n"
        "1. Wrap all English prose (sentences, words, punctuation) in \\text{...}.\n"
        "2. Ensure all mathematical expressions are properly enclosed in $...$ (inline) or $$...$$ (display).\n"
        "3. Preserve the original meaning and technical content exactly.\n"
        "4. DO NOT change the LaTeX commands (e.g., \\mathbb{R}^n stays as is).\n"
        "5. Output ONLY a JSON object where keys are the IDs provided and values are the REPAIRED LaTeX strings.\n\n"
        "SNIPPETS TO REPAIR:\n"
    )
    
    snippets = []
    for tid, content in term_map.items():
        snippets.append(f"ID {tid}: {content}\n---\n")
    
    prompt = header + "".join(snippets)

    print(f"Sending batch of {len(terms)} terms to Gemini...")
    repaired_map = ai.generate_json(prompt)

    if not repaired_map:
        print("AI failed to return JSON.")
        return

    print("\n--- TEST RESULTS (BEFORE vs AFTER) ---")
    for term in terms:
        tid = term['id']
        original = term['latex_content']
        # Try both string and int keys just in case
        repaired = repaired_map.get(str(tid)) or repaired_map.get(tid)
        
        print(f"\n[ID {tid}] {term['name'][:50]}...")
        print(f"  BEFORE: {original[:150].replace('\n', ' ')}...")
        if repaired:
            print(f"  AFTER:  {repaired[:150].replace('\n', ' ')}...")
        else:
            print(f"  AFTER:  [MISSING IN RESPONSE]")
        
    print("\nTotal terms processed: ", len(repaired_map))

if __name__ == "__main__":
    test_sanitize_batch()
