import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.append(str(PROJECT_ROOT))

from services.note import note_service
from core.database import db

def repair_term():
    # 1. Get the LaTeX for 232 and 233
    with db.get_connection() as conn:
        p232_row = conn.execute("SELECT latex_path FROM extracted_pages WHERE book_id = 508 AND page_number = 232").fetchone()
        p233_row = conn.execute("SELECT latex_path FROM extracted_pages WHERE book_id = 508 AND page_number = 233").fetchone()
    
    if not p232_row or not p233_row:
        print("Missing pages in DB.")
        return

    latex232 = (PROJECT_ROOT / p232_row['latex_path']).read_text(encoding='utf-8')
    latex233 = (PROJECT_ROOT / p233_row['latex_path']).read_text(encoding='utf-8')
    
    # 2. Extract the snippet manually
    start_tag = "Let $f: X"
    start_idx = latex232.find(start_tag)
    
    end_tag = "\\blacksquare"
    # Find the SECOND blacksquare on page 233 (first one is Proposition 4.11?)
    # Let's check page 233 again.
    # Page 233 starts with "Proof '=>' ...". Ends with "These inclusions imply (1.1)." 
    # Wait, there's no blacksquare for Proposition 1.1? 
    # Ah, the proof of Proposition 1.1 is split.
    
    # Actually, let's just take until the next term starts (Corollary 1.2)
    end_tag = "1.2 Corollary"
    end_idx = latex233.find(end_tag)
    
    if start_idx != -1 and end_idx != -1:
        snippet = latex232[start_idx:] + "\n\n% --- PAGE 233 ---\n\n" + latex233[:end_idx]
        
        # 3. Update the database
        with db.get_connection() as conn:
            conn.execute("UPDATE knowledge_terms SET latex_content = ?, page_start = 232 WHERE id = ?", (snippet, 1975))
        print("Term 1975 successfully repaired!")
        
        # 4. Sync to ES
        from services.knowledge import knowledge_service
        knowledge_service.sync_term_to_federated(1975)
        print("Synced to search engine.")
    else:
        print(f"Extraction failed. start_idx={start_idx}, end_idx={end_idx}")

if __name__ == "__main__":
    repair_term()
