import os
import sys
import sqlite3
import json
import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import db
from services.knowledge import knowledge_service

# No external genai imports needed, using explicit requests instead

DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY')

def get_page_content(conn, book_id, page_number):
    row = conn.execute("SELECT latex_path FROM extracted_pages WHERE book_id = ? AND page_number = ?", (book_id, page_number)).fetchone()
    if row and row['latex_path'] and os.path.exists(row['latex_path']):
        with open(row['latex_path'], 'r') as f:
            return f.read()
    return ""

def repair_orphaned_proofs():
    with db.get_connection() as conn:
        conn.row_factory = sqlite3.Row
        terms = conn.execute("SELECT id, book_id, page_start, name, term_type, latex_content FROM knowledge_terms ORDER BY book_id, page_start").fetchall()

    orphaned_proofs = []
    for term in terms:
        content = term['latex_content'] or ""
        stripped = content.replace('\\noindent', '').replace('\\textbf', '').replace('{', '').replace('}', '').strip()
        if stripped.lower().startswith('proof'):
            if '\\begin{theorem}' not in content.lower() and '\\begin{proposition}' not in content.lower() and '\\begin{lemma}' not in content.lower() and '\\begin{corollary}' not in content.lower():
                orphaned_proofs.append(term)

    print(f"Found {len(orphaned_proofs)} orphaned proofs to repair.")

    if not orphaned_proofs:
        return

    for term in orphaned_proofs:
        print(f"\nRepairing Term ID {term['id']} (Page {term['page_start']})...")
        
        with db.get_connection() as conn:
             prev_page = get_page_content(conn, term['book_id'], term['page_start'] - 1)
             curr_page = get_page_content(conn, term['book_id'], term['page_start'])

        prompt = f"""You are fixing an orphaned mathematical proof. 
The system extracted a proof but missed the Theorem/Proposition statement that belongs before it.

Here is the previous page's content (Page {term['page_start'] - 1}):
---
{prev_page}
---

Here is the current page's content (Page {term['page_start']}):
---
{curr_page}
---

Here is the orphaned proof we extracted:
---
{term['latex_content']}
---

INSTRUCTIONS:
1. Locate the logical Theorem, Proposition, Lemma, or Corollary statement that directly precedes this proof. It is likely at the very end of Page {term['page_start'] - 1} or the beginning of Page {term['page_start']}.
2. Combine that mathematical statement together with the orphaned proof above into a single, complete coherent LaTeX block. Keep the original LaTeX formatting.
3. Give the combined mathematical concept a highly descriptive, semantic name (e.g., instead of "Theorem 4.1", call it "Theorem 4.1: Properties of Continuous Functions on Compact Sets").

Return EXACTLY valid JSON in this format, and NOTHING else:
{{
  "name": "Descriptive Name Here",
  "combined_latex": "\\\\begin{{theorem}}...\\\\end{{theorem}}\\n\\nProof...\\\\qed"
}}
"""
        try:
            url = "https://api.deepseek.com/chat/completions"
            headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
            data = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": "You output only valid, minified JSON without markdown formatting. You are a PhD mathematician."},
                    {"role": "user", "content": prompt}
                ],
                "response_format": {"type": "json_object"}
            }
            
            resp = requests.post(url, headers=headers, json=data, timeout=60).json()
            if 'choices' not in resp:
                print("Failed to get response:")
                print(resp)
                continue
                
            reply = resp['choices'][0]['message']['content'].strip()
            
            # Remove possible markdown fences
            if reply.startswith("```json"): reply = reply[7:]
            if reply.endswith("```"): reply = reply[:-3]
            reply = reply.strip()
            
            result = json.loads(reply)
            
            new_name = result['name']
            new_latex = result['combined_latex']
            
            print(f"  -> Renamed to: {new_name}")
            
            with db.get_connection() as conn:
                conn.execute("UPDATE knowledge_terms SET name = ?, latex_content = ? WHERE id = ?", (new_name, new_latex, term['id']))
            
            knowledge_service.sync_term_to_federated(term['id'])
            print(f"  -> Successfully repaired and synced.")
            
        except Exception as e:
             print(f"Error repairing {term['id']}: {e}")

if __name__ == "__main__":
    repair_orphaned_proofs()
