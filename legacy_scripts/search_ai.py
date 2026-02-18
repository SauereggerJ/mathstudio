import sqlite3
import numpy as np
import requests
import argparse
import sys
import os

# Configuration
API_KEY = "AIzaSyCZ_z9Jdhzhi3m_kK_zozgxE-f7JCtokSk"
MODEL = "gemini-embedding-001"
DB_FILE = "library.db"

def get_embedding(text):
    """Fetches embedding from Gemini API."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:embedContent?key={API_KEY}"
    payload = {
        "model": f"models/{MODEL}",
        "content": {
            "parts": [{"text": text}]
        }
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            return response.json()['embedding']['values']
        else:
            print(f"API Error: {response.text}")
    except Exception as e:
        print(f"Connection Error: {e}")
    return None

def cosine_similarity(v1, matrix):
    """Computes cosine similarity between vector v1 and matrix of vectors."""
    # v1: (D,)
    # matrix: (N, D)
    
    # Normalize v1
    norm_v1 = np.linalg.norm(v1)
    if norm_v1 == 0: return np.zeros(matrix.shape[0])
    v1_u = v1 / norm_v1
    
    # Normalize matrix rows
    norm_matrix = np.linalg.norm(matrix, axis=1, keepdims=True)
    # Avoid division by zero
    norm_matrix[norm_matrix == 0] = 1 
    matrix_u = matrix / norm_matrix
    
    # Dot product
    return np.dot(matrix_u, v1_u)

def search_library(query, limit=5):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # 1. Load all vectors from DB
    # We fetch ID and Embedding BLOB
    cursor.execute("SELECT id, title, author, embedding FROM books WHERE embedding IS NOT NULL")
    rows = cursor.fetchall()
    
    if not rows:
        print("No vectorized books found in database. Please run 'vectorize.py' first.")
        return

    ids = []
    titles = []
    authors = []
    vectors = []
    
    # Pre-allocate numpy array for speed (if we knew size), but list append is fine for 1k items
    for r in rows:
        bid, title, author, blob = r
        if blob:
            ids.append(bid)
            titles.append(title)
            authors.append(author)
            # Convert binary blob back to float32 array
            vectors.append(np.frombuffer(blob, dtype=np.float32))
            
    if not vectors:
        print("No valid embeddings found.")
        return

    matrix = np.array(vectors)
    
    # 2. Vectorize Query
    print(f"Vectorizing query: '{query}'...")
    query_vec = get_embedding(query)
    if not query_vec:
        return
        
    query_vec = np.array(query_vec, dtype=np.float32)
    
    # 3. Search
    scores = cosine_similarity(query_vec, matrix)
    
    # 4. Rank
    # Get indices of top k scores (sorted descending)
    top_indices = np.argsort(scores)[::-1][:limit]
    
    print(f"\nTop {limit} Matches for '{query}':\n")
    for idx in top_indices:
        score = scores[idx]
        print(f"[{score:.4f}] {titles[idx]}")
        if authors[idx]:
            print(f"         by {authors[idx]}")
        print("-" * 40)
        
    conn.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 search_ai.py 'your search query'")
    else:
        # Join all arguments to allow unquoted queries like: python search_ai.py linear algebra
        query = " ".join(sys.argv[1:])
        search_library(query)
