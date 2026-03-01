#!/usr/bin/env python3
import sqlite3
import time
import logging
import argparse
import numpy as np
from typing import List, Optional
from google import genai
from google.genai import types

# Import der Projekt-Konfiguration
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
from core.config import DB_FILE
from utils import load_api_key

# --- Konfiguration ---
API_KEY = load_api_key()
MODEL = "models/gemini-embedding-001" # Korrektes Modell für Google AI Lab Keys
BATCH_SIZE = 50 # Reduziert auf 50, um Token-Limits pro Minute (TPM) nicht zu sprengen
MAX_RETRIES = 5
MAX_CHARS_PER_DOC = 9500

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("vectorize_batch.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("vectorizer")

def get_embeddings_with_retry(client: genai.Client, texts: List[str]) -> Optional[List[List[float]]]:
    """Holt Embeddings mit Exponential Backoff bei API-Limits (429) oder Serverfehlern (503)."""
    for attempt in range(MAX_RETRIES):
        try:
            response = client.models.embed_content(
                model=MODEL,
                contents=texts,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    title="Math Book Entry",
                    output_dimensionality=768
                )
            )
            return [embedding.values for embedding in response.embeddings]
        
        except Exception as e:
            error_str = str(e).lower()
            if "429" in error_str or "quota" in error_str or "503" in error_str:
                sleep_time = (2 ** attempt) * 5 # 5s, 10s, 20s, 40s...
                logger.warning(f"API Rate Limit oder Timeout. Warte {sleep_time} Sekunden (Versuch {attempt + 1}/{MAX_RETRIES})...")
                time.sleep(sleep_time)
            else:
                logger.error(f"Kritischer API Fehler: {e}")
                break
    
    logger.error("Maximale Anzahl an Retries erreicht. Batch fehlgeschlagen.")
    return None

def build_semantic_text(book: dict, cursor: sqlite3.Cursor) -> str:
    """Konstruiert den Text-Blob für die Vektorisierung unter Einbezug aller semantischen Merkmale."""
    parts = []
    
    if book['title']: parts.append(f"Title: {book['title']}")
    if book['author']: parts.append(f"Author: {book['author']}")
    if book['msc_class']: parts.append(f"MSC Classification: {book['msc_class']}")
    if book['summary']: parts.append(f"Summary: {book['summary']}")
    
    # Inhaltsverzeichnis (TOC) abrufen
    cursor.execute("SELECT title FROM chapters WHERE book_id = ? ORDER BY page ASC", (book['id'],))
    chapters = [row[0] for row in cursor.fetchall() if row[0]]
    if chapters:
        parts.append("Chapters:")
        # Begrenzung der Kapitelanzahl, um Kontext-Fenster nicht zu überfluten
        parts.extend([f"- {c}" for c in chapters[:50]]) 
        
    # Index-Keywords (auf die ersten Zeichen limitiert, da Indizes sehr lang sein können)
    if book['index_text']:
        parts.append(f"Index Keywords: {book['index_text'][:1000]}")
        
    full_text = "\n".join(parts)
    return full_text[:MAX_CHARS_PER_DOC]

def run_vectorization(revectorize_all: bool = False, limit: int = None):
    """Hauptprozess für die Vektorisierung der Bibliothek."""
    client = genai.Client(api_key=API_KEY)
    
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Zielgruppe definieren
        if revectorize_all:
            logger.info("Modus: FULL RE-VECTORIZATION. Überschreibe alle vorhandenen Embeddings.")
            query = "SELECT id, title, author, summary, msc_class, index_text FROM books"
        else:
            logger.info("Modus: MISSING ONLY. Vektorisiere nur neue Bücher.")
            query = "SELECT id, title, author, summary, msc_class, index_text FROM books WHERE embedding IS NULL"
            
        if limit:
            query += f" LIMIT {limit}"
            
        cursor.execute(query)
        books = cursor.fetchall()
        
        total_books = len(books)
        if total_books == 0:
            logger.info("Keine Bücher zur Vektorisierung gefunden. Beendet.")
            return

        logger.info(f"{total_books} Bücher werden in Batches von {BATCH_SIZE} verarbeitet.")
        
        successful_updates = 0
        
        for i in range(0, total_books, BATCH_SIZE):
            batch = books[i : i + BATCH_SIZE]
            batch_texts = []
            batch_ids = []
            
            for book in batch:
                batch_ids.append(book['id'])
                batch_texts.append(build_semantic_text(book, cursor))
            
            logger.info(f"Sende Batch {i//BATCH_SIZE + 1}/{(total_books + BATCH_SIZE - 1)//BATCH_SIZE} an Gemini API...")
            
            vectors = get_embeddings_with_retry(client, batch_texts)
            
            if vectors and len(vectors) == len(batch):
                for j, vec in enumerate(vectors):
                    vector_blob = np.array(vec, dtype=np.float32).tobytes()
                    cursor.execute(
                        "UPDATE books SET embedding = ? WHERE id = ?", 
                        (vector_blob, batch_ids[j])
                    )
                
                conn.commit()
                successful_updates += len(vectors)
                logger.info(f"-> {len(vectors)} Vektoren erfolgreich in DB gespeichert.")
            else:
                logger.error(f"-> Batch {i//BATCH_SIZE + 1} fehlgeschlagen und übersprungen.")
                
            # Standard-Cooldown zwischen erfolgreichen Batches zur Schonung der Rate Limits
            time.sleep(2.0)
            
    logger.info(f"Job abgeschlossen. {successful_updates}/{total_books} Bücher vektorisiert.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MathStudio Vectorization Batch Script")
    parser.add_argument("--all", action="store_true", help="Erzwingt eine Neuvektorisierung der gesamten Bibliothek")
    parser.add_argument("--limit", type=int, default=None, help="Limitiert die Anzahl der zu verarbeitenden Bücher")
    args = parser.parse_args()
    
    run_vectorization(revectorize_all=args.all, limit=args.limit)
