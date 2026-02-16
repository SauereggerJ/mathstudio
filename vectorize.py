import sqlite3
import time
import numpy as np
import argparse
import sys
from google import genai 
from google.genai import types

# Configuration
from utils import load_api_key

# Configuration
API_KEY = load_api_key()
MODEL = "models/gemini-embedding-001" 
DB_FILE = "library.db"
MAX_REQUESTS = 2000
BATCH_SIZE = 100 

def get_embeddings_batch(client, texts):
    """Fetches embeddings using the NEW google-genai library with optimized dimensions."""
    try:
        response = client.models.embed_content(
            model=MODEL,
            contents=texts,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT",
                title="Math Book Entry",
                output_dimensionality=768  # Optimized for performance/storage
            )
        )
        return [embedding.values for embedding in response.embeddings]
    except Exception as e:
        print(f"    [!] API Error: {e}")
    return None

def reset_embeddings():
    print(f"!!! RESETTING EMBEDDINGS FOR OPTIMIZED DIMENSIONS (768) !!!")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE books SET embedding = NULL")
    conn.commit()
    conn.close()
    print("Database embeddings cleared.")

def vectorize_books(limit=None):
    client = genai.Client(api_key=API_KEY)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    request_count = 0
    
    query = "SELECT id, title, author, description FROM books WHERE embedding IS NULL"
    if limit:
        query += f" LIMIT {limit}"
    
    cursor.execute(query)
    all_books = cursor.fetchall()
    
    if not all_books:
        print("No books found needing vectorization.")
        conn.close()
        return

    print(f"Found {len(all_books)} books to vectorize. Processing in batches of {BATCH_SIZE}...")
    
    for i in range(0, len(all_books), BATCH_SIZE):
        if request_count >= MAX_REQUESTS:
            print(f"!!! SAFETY STOP: Reached MAX_REQUESTS ({MAX_REQUESTS}). Exiting.")
            break
            
        batch = all_books[i : i + BATCH_SIZE]
        print(f"Processing Batch {i//BATCH_SIZE + 1} ({len(batch)} books)...")
        
        batch_texts = []
        batch_ids = []
        
        for book in batch:
            book_id, title, author, description = book
            batch_ids.append(book_id)
            cursor.execute("SELECT title FROM chapters WHERE book_id = ? ORDER BY page ASC", (book_id,))
            chapters = [row[0] for row in cursor.fetchall() if row[0]]
            
            parts = []
            if title: parts.append(f"Title: {title}")
            if author: parts.append(f"Author: {author}")
            if description: parts.append(f"Description: {description}")
            if chapters:
                parts.append("Chapters:")
                parts.extend([f"- {c}" for c in chapters])
            
            full_text = "\n".join(parts)
            batch_texts.append(full_text[:9000])
        
        vectors = get_embeddings_batch(client, batch_texts)
        request_count += 1 
        
        if vectors and len(vectors) == len(batch):
            for j, vec in enumerate(vectors):
                book_id = batch_ids[j]
                vector_blob = np.array(vec, dtype=np.float32).tobytes()
                cursor.execute("UPDATE books SET embedding = ? WHERE id = ?", (vector_blob, book_id))
            
            conn.commit()
            print(f"    -> Saved {len(vectors)} vectors (Dims: {len(vectors[0])}).")
        else:
            print(f"    -> Batch failed or partial result.")
            
        time.sleep(0.5)
        
    print(f"\nJob complete. Total API requests: {request_count}")
    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    
    if args.reset:
        reset_embeddings()
    
    vectorize_books(limit=args.limit)
