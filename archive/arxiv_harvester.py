import argparse
import arxiv
import sqlite3
import sys
import time
import numpy as np
from datetime import datetime
from pathlib import Path

# Reuse existing modules
# Note: This assumes search.py initializes 'client' at module level, which it does.
from search import get_embedding 
from utils import load_api_key

DB_FILE = "library.db"

def setup_db_check():
    """Ensures the DB has the required table and settings."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Enable WAL mode for better concurrency
    cursor.execute("PRAGMA journal_mode=WAL;")
    
    # Ensure papers table exists (Schema V2)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS papers (
            arxiv_id TEXT PRIMARY KEY,
            title TEXT,
            authors TEXT,
            published DATE,
            summary TEXT,
            category TEXT,
            pdf_url TEXT,
            embedding BLOB
        )
    ''')
    conn.commit()
    conn.close()

def harvest_papers(query, limit=10):
    """Fetches papers from ArXiv and indexes them. Returns stats dict."""
    
    # Initialize ArXiv Client
    # delay_seconds=3.0 to be nice to the API
    client = arxiv.Client(page_size=limit, delay_seconds=3.0, num_retries=3)
    
    search_query = arxiv.Search(
        query=query,
        max_results=limit,
        sort_by=arxiv.SortCriterion.SubmittedDate
    )

    print(f"🚀 Starting Harvest: '{query}' (Limit: {limit})")
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    count_new = 0
    count_skipped = 0
    errors = []
    
    # We iterate over results. arxiv.Client handles pagination automatically.
    try:
        results_iter = client.results(search_query)
        for result in results_iter:
            arxiv_id = result.get_short_id()
            
            # Check if already exists
            cursor.execute("SELECT 1 FROM papers WHERE arxiv_id = ?", (arxiv_id,))
            if cursor.fetchone():
                print(f"  ⏭️  [SKIP] {arxiv_id} already exists.")
                count_skipped += 1
                continue
                
            print(f"  📥 [NEW] {arxiv_id}: {result.title[:60]}...")
            
            # Generate Embedding (using Gemini via search.py)
            embedding = get_embedding(result.summary)
            
            if not embedding:
                print(f"     ⚠️ Failed to embed {arxiv_id}. Skipping.")
                errors.append(f"Failed to embed {arxiv_id}")
                continue
                
            # Serialize embedding
            emb_blob = np.array(embedding, dtype=np.float32).tobytes()
            
            # Format Data
            pub_date = result.published.strftime("%Y-%m-%d")
            authors = ", ".join([a.name for a in result.authors])
            
            # Insert
            try:
                cursor.execute('''
                    INSERT INTO papers (arxiv_id, title, authors, published, summary, category, pdf_url, embedding)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (arxiv_id, result.title, authors, pub_date, result.summary, result.primary_category, result.pdf_url, emb_blob))
                conn.commit()
                count_new += 1
            except Exception as e:
                print(f"     ❌ DB Error: {e}")
                errors.append(f"DB Error {arxiv_id}: {e}")
    except arxiv.HTTPError as e:
        if e.status == 429:
            print(f"  ⚠️ ArXiv Rate Limit (429). Try again later.")
            errors.append("ArXiv Rate Limit (429). Please wait a few minutes.")
        else:
            print(f"  ❌ ArXiv HTTP Error: {e}")
            errors.append(f"ArXiv HTTP Error: {e}")
    except Exception as e:
        print(f"Critical Harvest Error: {e}")
        errors.append(f"Critical Error: {e}")
    finally:
        conn.close()

    return {
        'added': count_new,
        'skipped': count_skipped,
        'errors': errors
    }

def search_papers(query_vec):
    """Searches local ArXiv Papers using a pre-calculated vector. Returns all matches sorted by score."""
    if query_vec is None: return []

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    results = []
    try:
        cursor.execute("SELECT arxiv_id, title, authors, published, embedding, pdf_url, summary, category FROM papers WHERE embedding IS NOT NULL")
        rows = cursor.fetchall()
        
        query_norm = np.linalg.norm(query_vec)
        if query_norm == 0: query_norm = 1e-10

        for r in rows:
            if not r[4]: continue
            vec = np.frombuffer(r[4], dtype=np.float32)
            
            vec_norm = np.linalg.norm(vec)
            if vec_norm == 0: vec_norm = 1e-10
            
            score = np.dot(vec, query_vec) / (vec_norm * query_norm)
            
            results.append({
                'type': 'paper',
                'id': r[0], # arxiv_id
                'title': r[1],
                'author': r[2],
                'year': r[3],
                'score': float(score),
                'pdf_url': r[5],
                'summary': r[6],
                'category': r[7],
                'found_by': 'vector'
            })
    except Exception as e:
        print(f"⚠️ Error searching papers: {e}")
    finally:
        conn.close()
    
    # Sort locally by score descending
    results.sort(key=lambda x: x['score'], reverse=True)
    return results

def search_hybrid(query):
    """Searches across local Books and cached ArXiv Papers."""
    
    print(f"🔍 Hybrid Search: '{query}'")
    
    # 1. Generate Query Embedding
    query_vec = get_embedding(query)
    if not query_vec:
        print("❌ Error: Could not embed query.")
        return []

    query_vec = np.array(query_vec, dtype=np.float32)
    
    # 2. Search Papers
    papers = search_papers(query_vec)
    
    # 3. Search Books (Re-implementing simplified version here or assuming search.py handles it if imported)
    # Ideally, search.py should call search_papers. 
    # But for CLI usage here, we can keep it simple or delegate back to search.py logic if circular import wasn't an issue.
    # To avoid circular imports, we just searched papers above.
    
    return papers

if __name__ == "__main__":
    setup_db_check()
    
    parser = argparse.ArgumentParser(description="MathStudio ArXiv Harvester")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # Harvest Command
    p_harvest = subparsers.add_parser("harvest", help="Fetch and index papers from ArXiv")
    p_harvest.add_argument("query", help="ArXiv query string (e.g. 'cat:math.DG AND au:Tao')")
    p_harvest.add_argument("--limit", type=int, default=10, help="Max results to fetch")
    
    # Search Command
    p_search = subparsers.add_parser("search", help="Semantic search across Books and Papers")
    p_search.add_argument("query", help="Semantic search query")
    
    args = parser.parse_args()
    
    if args.command == "harvest":
        stats = harvest_papers(args.query, args.limit)
        print(f"\n✅ Harvest Complete.\n   Added: {stats['added']}\n   Skipped: {stats['skipped']}")
    elif args.command == "search":
        results = search_hybrid(args.query)
        print("\n--- 🏆 Top Results ---")
        for res in results:
             print(f"📄 [PAPER] {res['title']}")
             print(f"   {res['author']} ({res['year']}) | Score: {res['score']:.4f}")
             print("-" * 40)
