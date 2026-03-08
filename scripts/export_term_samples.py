import sqlite3
import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.database import db

def export():
    samples = {
        "random_20": [],
        "definition_5": [],
        "theorem_5": [],
        "lemma_5": [],
        "exercise_5": []
    }
    
    with db.get_connection() as conn:
        conn.row_factory = sqlite3.Row
        
        # 1. 20 Random Terms Overall
        rows = conn.execute("SELECT id, name, term_type, latex_content, used_terms, book_id, page_start FROM knowledge_terms ORDER BY RANDOM() LIMIT 20").fetchall()
        samples["random_20"] = [dict(r) for r in rows]
        
        # 2. 5 Random of Specific Types
        types = ['definition', 'theorem', 'lemma', 'exercise']
        for t in types:
            rows = conn.execute("SELECT id, name, term_type, latex_content, used_terms, book_id, page_start FROM knowledge_terms WHERE term_type = ? ORDER BY RANDOM() LIMIT 5", (t,)).fetchall()
            samples[f"{t}_5"] = [dict(r) for r in rows]
            
    # Parse used_terms JSON strings
    for category in samples.values():
        for term in category:
            if term['used_terms']:
                try:
                    term['used_terms'] = json.loads(term['used_terms'])
                except:
                    pass

    out_path = "/home/jure/.gemini/antigravity/brain/def9b2c8-9f65-484c-9b4c-84594d9aa09d/term_samples.json"
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(samples, f, indent=4, ensure_ascii=False)
        
    print(f"Exported successfully to {out_path}")

if __name__ == '__main__':
    export()
