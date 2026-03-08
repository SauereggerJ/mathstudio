import sys
import os
import time
import argparse
import logging
import numpy as np
import sqlite3

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import db
from core.ai import ai
from core.config import EMBEDDING_MODEL

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("batch_embed_kb")

BATCH_SIZE = 50
DELAY_SECONDS = 3

def generate_embeddings_for_batch(texts):
    try:
        results = ai.client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=texts
        )
        # results.embeddings is a list of embeddings
        return [np.array(e.values, dtype=np.float32).tobytes() for e in results.embeddings]
    except Exception as e:
        logger.error(f"Embedding API Error: {e}")
        return None

def embed_canonical_concepts():
    logger.info("--- Embedding Canonical Concepts ---")
    with db.get_connection() as conn:
        concepts = conn.execute("SELECT id, name, subject_area, summary FROM mathematical_concepts WHERE embedding IS NULL").fetchall()
    
    if not concepts:
        logger.info("All canonical concepts are already embedded.")
        return

    logger.info(f"Generating embeddings for {len(concepts)} canonical concepts...")
    
    for i in range(0, len(concepts), BATCH_SIZE):
        batch = concepts[i:i + BATCH_SIZE]
        texts = []
        for c in batch:
            text = f"[Name] {c['name']} [Subject] {c['subject_area']} [Summary] {c['summary']}"
            texts.append(text)
        
        embeddings = generate_embeddings_for_batch(texts)
        if embeddings and len(embeddings) == len(batch):
            with db.get_connection() as conn:
                for c, emb in zip(batch, embeddings):
                    conn.execute("UPDATE mathematical_concepts SET embedding = ? WHERE id = ?", (emb, c['id']))
            logger.info(f"Processed concept batch {i // BATCH_SIZE + 1} ({len(batch)} concepts)")
        else:
            logger.error(f"Failed to generate embeddings for batch {i // BATCH_SIZE + 1}. Skipping.")
        
        time.sleep(DELAY_SECONDS)

def embed_knowledge_terms():
    logger.info("--- Embedding Knowledge Terms ---")
    
    # First ensure the column exists
    with db.get_connection() as conn:
        try:
            conn.execute("ALTER TABLE knowledge_terms ADD COLUMN embedding BLOB")
            logger.info("Added embedding column to knowledge_terms.")
        except sqlite3.OperationalError:
            pass # Already exists

    with db.get_connection() as conn:
        terms = conn.execute("""
            SELECT kt.id, kt.name, kt.latex_content, b.msc_class 
            FROM knowledge_terms kt 
            LEFT JOIN books b ON kt.book_id = b.id
            WHERE kt.embedding IS NULL
        """).fetchall()

    if not terms:
        logger.info("All knowledge terms are already embedded.")
        return

    logger.info(f"Generating embeddings for {len(terms)} knowledge terms...")
    
    for i in range(0, len(terms), BATCH_SIZE):
        batch = terms[i:i + BATCH_SIZE]
        texts = []
        for t in batch:
            msc = t['msc_class'] if t['msc_class'] else "Unknown"
            text = f"[Term] {t['name']} [Book Subject] {msc} [LaTeX Context] {t['latex_content']}"
            texts.append(text)
        
        embeddings = generate_embeddings_for_batch(texts)
        if embeddings and len(embeddings) == len(batch):
            with db.get_connection() as conn:
                for t, emb in zip(batch, embeddings):
                    conn.execute("UPDATE knowledge_terms SET embedding = ? WHERE id = ?", (emb, t['id']))
            logger.info(f"Processed term batch {i // BATCH_SIZE + 1} ({len(batch)} terms)")
        else:
            logger.error(f"Failed to generate embeddings for batch {i // BATCH_SIZE + 1}. Skipping.")
        
        time.sleep(DELAY_SECONDS)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch generate embeddings for concepts and terms")
    parser.add_argument("--concepts-only", action="store_true", help="Only embed mathematical concepts")
    parser.add_argument("--terms-only", action="store_true", help="Only embed knowledge terms")
    args = parser.parse_args()

    if args.concepts_only:
        embed_canonical_concepts()
    elif args.terms_only:
        embed_knowledge_terms()
    else:
        embed_canonical_concepts()
        embed_knowledge_terms()
