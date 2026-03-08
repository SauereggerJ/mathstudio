import sys
import os
import time
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.database import db
from core.ai import ai
from services.note import NoteService

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("test_random")

BATCH_SIZES = [1, 3, 5, 10]

def test_random_batches():
    logger.info("--- Testing Gemini with Incremental Batch Sizes ---")
    ai.routing_policy = "gemini"
    ns = NoteService()
    
    for size in BATCH_SIZES:
        logger.info(f"--- Fetching Random Batch of Size {size} ---")
        with db.get_connection() as conn:
            terms = conn.execute(f"""
                SELECT id, name, latex_content 
                FROM knowledge_terms 
                WHERE (latex_content LIKE '% is %' OR latex_content LIKE '% the %' OR latex_content LIKE '% of %') 
                  AND latex_content NOT LIKE '%\\text{{%'
                  AND (attempted_repair_prose IS NULL OR attempted_repair_prose = 0)
                ORDER BY RANDOM()
                LIMIT {size}
            """).fetchall()

        if not terms:
            logger.info("No terms found.")
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
        for tid, content in term_map.items():
            snippets.append(f"ID {tid}: {content}\n---\n")

        prompt += "".join(snippets)

        logger.info(f"Sending batch of {size} (prompt length: {len(prompt)}) to Gemini...")
        start_time = time.time()
        try:
            blocks = ai.generate_xml_blocks(prompt, "repair", retry_count=1)
            logger.info(f"Gemini returned {len(blocks)} XML blocks in {time.time() - start_time:.2f} seconds.")
            for b in blocks:
                logger.info(f"Sample block:\n{b}")
        except BaseException as e:
            logger.error(f"Gemini call failed or hung: {e}")
            logger.error(f"Time elapsed before failure/interrupt: {time.time() - start_time:.2f} seconds")
            
        time.sleep(5)

if __name__ == "__main__":
    test_random_batches()
