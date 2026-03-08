import sqlite3
import re
import sys
import os
import time
import logging
from pathlib import Path

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ai import ai
from core.database import db
from services.note import NoteService

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
COOLDOWN_SECONDS = 5
STOP_FILE = "STOP_REPAIR"

def run_repair():
    logger.info(f"--- Starting Polished Prose Repair via DualStack XML (Batch Size: {BATCH_SIZE}) ---")
    
    # Force text tasks to DeepSeek 
    ai.routing_policy = "dual_stack"
    
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)

    ns = NoteService()
    total_repaired = 0
    batches_run = 0
    
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
                  AND latex_content NOT LIKE '%\\text{{%'
                  AND (attempted_repair_prose IS NULL OR attempted_repair_prose = 0)
                LIMIT {BATCH_SIZE}
            """).fetchall()

        if not terms:
            logger.info("No more wonky terms found.")
            break

        term_map = {t['id']: t['latex_content'] for t in terms}
        
        prompt = (
            "You are a mathematical LaTeX expert. REPAIR these snippets where English prose is mixed with LaTeX.\n"
            "CRITICAL RULES:\n"
            "1. Leave actual mathematics wrapped in $...$ or $$...$$ unchanged.\n"
            "2. Wrap all pure English prose words in \\text{...} OR strip the prose entirely and leave just the math if it's better.\n"
            "3. Do NOT use JSON. DO NOT escape backslashes (use standard \\text, not \\\\text).\n\n"
            "=== OUTPUT FORMAT ===\n"
            "For each snippet, return an XML block like this:\n"
            "<repair>\n"
            "  <id>XX</id>\n"
            "  <latex>... repaired code ...</latex>\n"
            "</repair>\n\n"
            "SNIPPETS:\n"
        )
        
        
        snippets = []
        valid_term_ids = []
        for tid, content in term_map.items():
            lint_errors = ns.lint_latex(content)
            if lint_errors:
                logger.warning(f"ID {tid} failed local structural linting: {lint_errors}. Proceeding anyway to fix prose.")
                
            snippets.append(f"ID {tid}: {content}\n---\n")
            valid_term_ids.append(tid)

        prompt += "".join(snippets)

        # Mark as attempted immediately to prevent infinite loop on failure
        with db.get_connection() as conn:
            conn.execute(f"UPDATE knowledge_terms SET attempted_repair_prose = 1 WHERE id IN ({','.join('?' * len(valid_term_ids))})", valid_term_ids)
            conn.commit()

        logger.info(f"Batch of {len(terms)}... (Total so far: {total_repaired})")
        
        try:
            blocks = ai.generate_xml_blocks(prompt, "repair")
        except Exception as e:
            logger.error(f"AI Call failed: {e}")
            time.sleep(30)
            continue

        if not blocks:
            logger.warning("AI returned empty/invalid XML response. Skipping...")
            time.sleep(20)
            continue

        # Process results
        success_count = 0
        with db.get_connection() as conn:
            cursor = conn.cursor()
            for block in blocks:
                try:
                    id_match = re.search(r'<id>(.*?)</id>', block, re.DOTALL)
                    latex_match = re.search(r'<latex>(.*?)</latex>', block, re.DOTALL)
                    
                    if id_match and latex_match:
                        tid = int(id_match.group(1).strip())
                        repaired_latex = latex_match.group(1).strip()
                        if repaired_latex and tid in term_map:
                            cursor.execute("UPDATE knowledge_terms SET latex_content = ?, updated_at = unixepoch() WHERE id = ?", (repaired_latex, tid))
                            cursor.execute("UPDATE knowledge_terms_fts SET latex_content = ? WHERE rowid = ?", (repaired_latex, tid))
                            success_count += 1
                except Exception as e:
                    logger.error(f"Error parsing block: {e}")
            
            conn.commit()
            
        total_repaired += success_count
        logger.info(f"Updated {success_count}/{len(terms)} in this batch.")

        sys.stdout.flush()
        
        batches_run += 1
        if batches_run >= 5:
            logger.info("Reached 5 batches limit for testing. Pausing and waiting for user instruction.")
            break
            
        time.sleep(COOLDOWN_SECONDS)

    logger.info(f"Done. Total repaired in this run: {total_repaired}")

if __name__ == "__main__":
    run_repair()
