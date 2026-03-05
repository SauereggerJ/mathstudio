import sqlite3
import json
import sys
import os
import time
import re
import logging
from pathlib import Path

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ai import ai
from core.database import db

# Configure local logging for this script
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("prose_repair_debug.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("prose_repair")

BATCH_SIZE = 15 
COOLDOWN_SECONDS = 12
STOP_FILE = "STOP_REPAIR"

def run_repair():
    logger.info(f"--- Starting Polished Prose Repair (Batch Size: {BATCH_SIZE}) ---")
    
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)

    total_repaired = 0
    
    while True:
        if os.path.exists(STOP_FILE):
            logger.info("Stop signal detected. Exiting...")
            break

        # Fetch terms that definitely need prose wrapping
        with db.get_connection() as conn:
            terms = conn.execute(f"""
                SELECT id, name, latex_content 
                FROM knowledge_terms 
                WHERE (latex_content LIKE '% is %' OR latex_content LIKE '% the %' OR latex_content LIKE '% of %') 
                  AND latex_content NOT LIKE '%\text{{%'
                LIMIT {BATCH_SIZE}
            """).fetchall()

        if not terms:
            logger.info("No more wonky terms found.")
            break

        term_map = {t['id']: t['latex_content'] for t in terms}
        
        header = (
            "You are a mathematical LaTeX expert. REPAIR these snippets where prose is mixed with LaTeX.\n"
            "CRITICAL RULES:\n"
            "1. Wrap all English prose in \\text{...}.\n"
            "2. Ensure all math is in $...$ or $$...$$.\n"
            "3. Return ONLY a JSON object where keys are the NUMERIC IDs and values are the REPAIRED LaTeX.\n"
            "4. IMPORTANT: In your JSON output, you MUST escape backslashes correctly (e.g., use \\\\text instead of \\text).\n\n"
            "SNIPPETS:\n"
        )
        
        snippets = [f"ID {tid}: {content}\n---\n" for tid, content in term_map.items()]
        prompt = header + "".join(snippets)

        logger.info(f"Batch of {len(terms)}... (Total so far: {total_repaired})")
        
        try:
            repaired_map = ai.generate_json(prompt)
        except Exception as e:
            logger.error(f"AI Call failed: {e}")
            time.sleep(30)
            continue

        if not repaired_map:
            logger.warning("AI returned empty/invalid response. Skipping...")
            time.sleep(20)
            continue

        # Process results
        with db.get_connection() as conn:
            cursor = conn.cursor()
            success_count = 0
            for tid_raw, repaired_latex in repaired_map.items():
                try:
                    tid_match = re.search(r'(\d+)', str(tid_raw))
                    if not tid_match: continue
                    tid = int(tid_match.group(1))
                    
                    if repaired_latex and tid in term_map:
                        cursor.execute("UPDATE knowledge_terms SET latex_content = ? WHERE id = ?", (repaired_latex, tid))
                        cursor.execute("UPDATE knowledge_terms_fts SET latex_content = ? WHERE rowid = ?", (repaired_latex, tid))
                        success_count += 1
                except Exception as e:
                    logger.error(f"Error updating ID {tid_raw}: {e}")
            
            conn.commit()
            total_repaired += success_count
            logger.info(f"Updated {success_count}/{len(terms)} in this batch.")

        sys.stdout.flush() # Force log output
        time.sleep(COOLDOWN_SECONDS)

    logger.info(f"Done. Total repaired: {total_repaired}")

if __name__ == "__main__":
    run_repair()
