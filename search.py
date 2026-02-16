import sqlite3
import argparse
import sys
import json
import re
import io
import time
from pathlib import Path
import numpy as np
import requests
from google import genai
from google.genai import types
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache

from utils import load_api_key

# Configuration
DB_FILE = "library.db"
GEMINI_API_KEY = load_api_key()
EMBEDDING_MODEL = "models/gemini-embedding-001"
LLM_MODEL = "gemini-2.0-flash"

client = genai.Client(api_key=GEMINI_API_KEY)

@lru_cache(maxsize=100)
def get_embedding(text):
    """Fetches embedding from Gemini API. Cached."""
    try:
        result = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=[text[:10000]],
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=768
            )
        )
        return tuple(result.embeddings[0].values)
    except Exception as e:
        print(f"Embedding API Error: {e}", file=sys.stderr)
    return None

@lru_cache(maxsize=100)
def expand_query_with_llm(query):
    """Translates and expands the query using LLM. Cached."""
    prompt = f"You are a mathematical search expert. Translate this query to English if it's in another language, and add 3-5 relevant mathematical keywords or synonyms to improve search recall. Return ONLY the expanded query text.\nQuery: {query}"
    try:
        response = client.models.generate_content(model=LLM_MODEL, contents=prompt)
        return response.text.strip()
    except Exception as e:
        print(f"Query Expansion Error: {e}", file=sys.stderr)
        return query

def extract_index_pages(index_text, query):
    if not index_text or not query:
        return None
    
    # Try query as is, then with hyphen/space swap
    queries = [query]
    if '-' in query: queries.append(query.replace('-', ' '))
    if ' ' in query: queries.append(query.replace(' ', '-'))
    
    all_found_pages = []
    seen = set()
    
    for q in queries:
        # Find all occurrences of the term
        for match in re.finditer(re.escape(q), index_text, re.IGNORECASE):
            start_pos = match.end()
            # Look at the next 300 characters for page numbers
            chunk = index_text[start_pos:start_pos + 300]
            
            # Find all number sequences (e.g. 12, 14-16, 20)
            num_matches = re.findall(r'[\s,]*(\d+(?:[\s,–\.-]+\d+)*)', chunk)
            for m in num_matches:
                cleaned = m.strip(' .,-')
                if cleaned and cleaned not in seen:
                    all_found_pages.append(cleaned)
                    seen.add(cleaned)
            
            if all_found_pages: break
                    
    if all_found_pages:
        return ", ".join(all_found_pages)
    return None
    
    # helper to run regex
    def run_regex(q_text):
        # Pattern explanation:
        # 1. Query (escaped)
        # 2. (?:[^0-9]{0,150}) -> Allow up to 150 chars of "noise" (words, punctuation, newlines) 
        #    Increased from 100 to 150 to catch multi-line indented sub-entries.
        # 3. (\d+(?:[\s,–\.-]+\d+)*) -> Capture the sequence of numbers/ranges.
        pattern = re.compile(re.escape(q_text) + r'(?:[^0-9]{0,250})[\s,]*(\d+(?:[\s,–\.-]+\d+)*)', re.IGNORECASE)
        return pattern.findall(index_text)

    # 1. Try exact query
    matches = run_regex(query)
    
    # 2. Try variations (hyphen vs space)
    if not matches:
        if '-' in query:
            matches = run_regex(query.replace('-', ' '))
        elif ' ' in query:
            matches = run_regex(query.replace(' ', '-'))
        
    if matches:
        all_pages = []
        seen = set()
        
        for m in matches:
            # Clean up the match string
            cleaned = m.strip(' .,-')
            # remove newlines from the number string itself just in case
            cleaned = cleaned.replace('\n', '')
            if cleaned and cleaned not in seen:
                all_pages.append(cleaned)
                seen.add(cleaned)
                
        if all_pages:
            return ", ".join(all_pages)
            
    return None

def search_books_semantic(query, query_vec=None):
    """
    Performs semantic search using vector embeddings. 
    Optimized for performance: 
    1. Fetches ONLY ID and Embedding first.
    2. Calculates scores.
    3. Fetches details ONLY for top matches.
    """
    if query_vec is None:
        # Convert tuple back to list if needed, or get_embedding handles it
        vec_tuple = get_embedding(query)
        query_vec = list(vec_tuple) if vec_tuple else None
        
    if not query_vec:
        return [], "Failed to generate query embedding."
        
    query_vec = np.array(query_vec, dtype=np.float32)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        # Step 1: Lightweight fetch (ID + Embedding only)
        cursor.execute("SELECT id, embedding FROM books WHERE embedding IS NOT NULL")
        rows = cursor.fetchall()
        
        if not rows: return [], "No vectorized books found."
        
        ids = []
        vectors = []
        
        for r in rows:
            if not r[1]: continue
            vec = np.frombuffer(r[1], dtype=np.float32)
            if len(vec) != len(query_vec): continue
            
            ids.append(r[0])
            vectors.append(vec)
            
        if not vectors: return [], "No compatible vector embeddings found."

        # Step 2: Vector Math
        matrix = np.array(vectors)
        norm_q = np.linalg.norm(query_vec)
        norm_m = np.linalg.norm(matrix, axis=1)
        
        # Avoid division by zero
        norm_m[norm_m == 0] = 1e-10
        if norm_q == 0: norm_q = 1e-10
        
        scores = np.dot(matrix, query_vec) / (norm_m * norm_q)
        
        # Step 3: Select Top Candidates (Top 50 is enough for re-ranking later)
        # We process more than the final limit to allow for filtering downstream
        top_k = 50
        if len(scores) < top_k:
            top_indices = np.argsort(scores)[::-1]
        else:
             # argpartition is faster for getting top k elements
            top_indices = np.argpartition(scores, -top_k)[-top_k:]
            # sort the top k
            top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]
            
        top_ids = [ids[i] for i in top_indices]
        id_score_map = {ids[i]: float(scores[i]) for i in top_indices}
        
        if not top_ids:
            return [], None

        # Step 4: Fetch details for top candidates
        placeholders = ','.join(['?'] * len(top_ids))
        sql = f"""
            SELECT id, title, author, path, isbn, publisher, year, summary, index_text 
            FROM books 
            WHERE id IN ({placeholders})
        """
        cursor.execute(sql, top_ids)
        detail_rows = cursor.fetchall()
        
        results = []
        for r in detail_rows:
            bid = r[0]
            if bid in id_score_map:
                results.append({
                    'type': 'book', 
                    'id': bid, 
                    'title': r[1], 
                    'author': r[2],
                    'path': r[3], 
                    'isbn': r[4], 
                    'publisher': r[5],
                    'year': r[6], 
                    'score': id_score_map[bid], 
                    'summary': r[7],
                    'index_text': r[8]
                })
        
        # Ensure results are sorted by score (SQL order is undefined)
        results.sort(key=lambda x: x['score'], reverse=True)
        
        return results, None
        
    except Exception as e:
        print(f"Semantic Search Error: {e}", file=sys.stderr)
        return [], str(e)
    finally:
        conn.close()

def search_books_fts(query, limit=50, field='all'):
    """Performs a Full Text Search using the books_fts table."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    clean_query = query.replace('"', '""')
    
    snippet_col = 3 if field == 'index' else -1
    
    fts_query = f'"{clean_query}"'
    if field == 'title': fts_query = f'title : "{clean_query}"'
    elif field == 'author': fts_query = f'author : "{clean_query}"'
    elif field == 'index': fts_query = f'index_content : "{clean_query}"'

    sql = f"""
        SELECT b.id, b.title, b.author, b.path, 
               snippet(books_fts, {snippet_col}, '<b>', '</b>', '...', 15) as snippet,
               b.year, b.publisher, rank, b.summary, b.index_text
        FROM books_fts f 
        JOIN books b ON f.rowid = b.id 
        WHERE books_fts MATCH ? 
        ORDER BY rank 
        LIMIT ?
    """
    try:
        cursor.execute(sql, (fts_query, limit))
        return cursor.fetchall()
    except sqlite3.Error as e:
        print(f"FTS Error: {e}", file=sys.stderr)
        return []
    finally: conn.close()

def rerank_with_llm(query, candidates, limit=10):
    """Uses LLM to rerank the top candidates with reasoning."""
    if not candidates: return []
    
    prompt = f"You are a strict mathematics librarian. Rank the following book candidates for the search query: '{query}'.\n"
    prompt += "Exclude irrelevant books. Focus on mathematical depth and relevance.\n\nCandidates:\n"
    for c in candidates:
        text = f"Title: {c['title']} | Author: {c['author']}"
        if c.get('snippet'): text += f" | Snippet: {c['snippet']}"
        elif c.get('summary'): text += f" | Summary: {c['summary'][:200]}"
        prompt += f"[ID {c['id']}] {text}\n"
    
    prompt += '\nReturn ONLY a JSON list of objects for the top 10 results, e.g. [{"id": 15, "reason": "Detailed treatment of topic X"}, {"id": 2, "reason": "Standard reference for Y"}].'

    try:
        response = client.models.generate_content(model=LLM_MODEL, contents=prompt)
        text = response.text.strip()
        match = re.search(r'[[\]s*\{[^}]*\}\s*[]', text, re.DOTALL)
        if match:
            new_order = json.loads(match.group(0))
            id_map = {c['id']: c for c in candidates}
            reranked = []
            for entry in new_order:
                bid = entry.get('id')
                if bid in id_map:
                    item = id_map[bid].copy()
                    item['ai_rank'] = len(reranked) + 1
                    item['ai_reason'] = entry.get('reason', '')
                    reranked.append(item)
            for c in candidates:
                if c['id'] not in [r['id'] for r in reranked]:
                    reranked.append(c)
            return reranked[:limit]
    except Exception as e:
        print(f"LLM Rerank Error: {e}", file=sys.stderr)
    
    return candidates[:limit]

def search(query, limit=20, offset=0, use_fts=True, use_vector=True, use_translate=False, use_rerank=False, field='all'):
    """Modular Smart Search Pipeline with Pagination. Parallelized."""
    
    search_query = query
    expanded_query = None
    query_vec = None
    
    # Parallel execution for API calls
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {}
        
        # 1. Translation / Expansion
        if use_translate:
            futures['expand'] = executor.submit(expand_query_with_llm, query)
            
        # 2. Vector Embedding
        # If translate is OFF, we can start embedding immediately.
        # If translate is ON, we ideally wait, but we can also speculatively embed original query.
        # For simplicity and correctness with translation, we wait if translation is on.
        
        if not use_translate and use_vector:
             futures['embed'] = executor.submit(get_embedding, query)
             
        # Wait for expansion if needed
        if 'expand' in futures:
            try:
                expanded_query = futures['expand'].result(timeout=5)
                search_query = expanded_query
                # Now trigger embedding on the expanded query
                if use_vector:
                     futures['embed'] = executor.submit(get_embedding, search_query)
            except Exception as e:
                print(f"Expansion timed out or failed: {e}")
                
        # Get embedding result
        if 'embed' in futures:
            try:
                # tuple -> list/np.array
                vec_tuple = futures['embed'].result(timeout=5)
                if vec_tuple:
                    query_vec = list(vec_tuple)
            except Exception as e:
                print(f"Embedding timed out or failed: {e}")

    candidates = {}

    # 2. Retrieval (Vector)
    if use_vector and query_vec:
        # Books
        
        vec_results, error = search_books_semantic(search_query, query_vec=query_vec)
        if not error:
            for res in vec_results:
                if res['score'] < 0.25: continue
                key = f"B_{res['id']}"
                candidates[key] = res
                candidates[key]['found_by'] = 'vector'



    # Retrieval (FTS)
    if use_fts :
        # FTS still needs a limit, but we make it generous for paging
        fts_results = search_books_fts(search_query, limit=1000, field=field)
        for i, row in enumerate(fts_results):
            bid = row[0]
            key = f"B_{bid}"
            # FTS Rank is BM25 usually, normalized here roughly
            fts_score = 1.0 - (i / 1000.0) 
            
            if key in candidates:
                candidates[key]['score'] = (candidates[key]['score'] * 0.6) + (fts_score * 0.4)
                candidates[key]['found_by'] = 'both'
                candidates[key]['snippet'] = row[4]
            else:
                candidates[key] = {
                    'type': 'book',
                    'id': row[0], 'title': row[1], 'author': row[2], 'path': row[3],
                    'snippet': row[4], 'year': row[5], 'publisher': row[6],
                    'score': fts_score, 'summary': row[8], 'found_by': 'text',
                    'index_text': row[9]
                }

    # 3. Check Index Matches (Using original query for register lookups) - Only for books
    for key in candidates:
        if candidates[key]['type'] == 'book' and candidates[key].get('index_text'):
            idx_match = extract_index_pages(candidates[key]['index_text'], query)
            if idx_match:
                candidates[key]['index_matches'] = idx_match
                # Boost score heavily if found in index
                candidates[key]['score'] += 0.5

    # 4. Flatten & Sort
    final_list = list(candidates.values())
    final_list.sort(key=lambda x: x['score'], reverse=True)
    
    total_count = len(final_list)

    # 5. Slicing (Pagination)
    paged_results = final_list[offset : offset + limit]

    # 6. Reranking (Only applied to the current page slice)
    if use_rerank and len(paged_results) > 0:
        paged_results = rerank_with_llm(query, paged_results, limit=limit)

    return {
        'results': paged_results,
        'total_count': total_count,
        'expanded_query': expanded_query if expanded_query and expanded_query != query else None
    }

# --- Compatibility & Utility Functions ---

def get_book_details(book_id, query=None):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT title, author, path, isbn, publisher, year, summary, level, exercises, solutions, reference_url, msc_code, tags, index_text FROM books WHERE id = ?", (book_id,))
        row = cursor.fetchone()
        if not row: return None
        data = list(row)
        index_text = data[-1]
        index_matches = None
        if query and index_text:
            index_matches = extract_index_pages(index_text, query)
        data.append(index_matches)
        return data
    finally: conn.close()

def get_book_matches(book_id, query):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    clean_query = query.replace('"', '""')
    try:
        # Request highlights for BOTH Content (col 2) and Index (col 3)
        cursor.execute("SELECT highlight(books_fts, 2, '<b>', '</b>'), highlight(books_fts, 3, '<b>', '</b>') FROM books_fts WHERE rowid = ? AND books_fts MATCH ?", (book_id, clean_query))
        row = cursor.fetchone()
        if not row: return []
        
        hl_content = row[0] or ""
        hl_index = row[1] or ""
        
        results = []
        page_pattern = re.compile(r'\[\[PAGE_(\d+)\]\]')
        
        # 1. Process Content Matches
        if "<b>" in hl_content:
            current_pos = 0
            while True:
                idx = hl_content.find("<b>", current_pos)
                if idx == -1: break
                
                # Find preceding page marker
                preceding = hl_content[max(0, idx - 10000):idx]
                page_num = 1
                pm = list(page_pattern.finditer(preceding))
                if pm: page_num = int(pm[-1].group(1))
                
                close_idx = hl_content.find("</b>", idx)
                match_end = close_idx + 4 if close_idx != -1 else idx + 3
                
                # Extract snippet
                fragment = hl_content[max(0, idx - 100):min(len(hl_content), match_end + 100)]
                clean_fragment = re.sub(r'\[\[PAGE_\d+\]\]', '', fragment)
                
                results.append({'snippet': clean_fragment, 'page': page_num})
                current_pos = match_end
                if len(results) > 50: break

        # 2. Process Index Matches (if few content matches)
        if len(results) < 5 and "<b>" in hl_index:
            current_pos = 0
            while True:
                idx = hl_index.find("<b>", current_pos)
                if idx == -1: break
                
                close_idx = hl_index.find("</b>", idx)
                match_end = close_idx + 4 if close_idx != -1 else idx + 3
                
                # Extract snippet for index
                fragment = hl_index[max(0, idx - 60):min(len(hl_index), match_end + 60)]
                
                results.append({'snippet': fragment, 'page': 'Index'})
                current_pos = match_end
                if len(results) > 50: break
                
        return results
    except Exception as e: 
        print(f"Match processing error: {e}")
        return []
    finally: conn.close()

def get_chapters(book_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        # 1. Try to get JSON ToC from books table (New System)
        cursor.execute("SELECT toc_json FROM books WHERE id = ?", (book_id,))
        row = cursor.fetchone()
        
        if row and row[0]:
            try:
                toc_data = json.loads(row[0])
                if toc_data:
                    formatted_chapters = []
                    for item in toc_data:
                        # Handle AI List of Strings ["Title 1", "Title 2"]
                        if isinstance(item, str):
                            # (Title, Level=0, Page=None, MSC=None, Topics=None)
                            formatted_chapters.append((item, 0, None, None, None))
                            
                        # Handle PyMuPDF [[lvl, title, page], ...]
                        elif isinstance(item, list) and len(item) >= 2:
                            lvl = item[0] - 1 if isinstance(item[0], int) else 0
                            title = item[1]
                            page = item[2] if len(item) > 2 else None
                            formatted_chapters.append((title, lvl, page, None, None))
                            
                        # Handle Dictionary (Smart ToC)
                        elif isinstance(item, dict):
                             # Prefer calculated PDF page (physical) over printed page
                             page_num = item.get('pdf_page') or item.get('page')
                             
                             formatted_chapters.append((
                                 item.get('title', 'Untitled'),
                                 item.get('level', 0),
                                 page_num,
                                 item.get('msc'),
                                 item.get('topics')
                             ))
                    
                    if formatted_chapters:
                        return formatted_chapters
            except json.JSONDecodeError:
                pass # Fallback to old table

        # 2. Fallback to chapters table (Old System)
        cursor.execute("SELECT title, level, page, msc_code, topics FROM chapters WHERE book_id = ? ORDER BY id ASC", (book_id,))
        return cursor.fetchall()
    finally: conn.close()

def get_similar_books(book_id, limit=5):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT embedding FROM books WHERE id = ?", (book_id,))
        res = cursor.fetchone()
        if res and res[0]:
            target_vec = np.frombuffer(res[0], dtype=np.float32)
            cursor.execute("SELECT id, title, author, path, embedding FROM books WHERE id != ? AND embedding IS NOT NULL", (book_id,))
            rows = cursor.fetchall()
            if rows:
                ids, titles, authors, paths, vectors = [], [], [], [], []
                for r in rows:
                    ids.append(r[0]); titles.append(r[1]); authors.append(r[2]); paths.append(r[3])
                    vectors.append(np.frombuffer(r[4], dtype=np.float32))
                matrix = np.array(vectors)
                if matrix.shape[1] == len(target_vec):
                    norm_t = np.linalg.norm(target_vec); norm_m = np.linalg.norm(matrix, axis=1)
                    scores = np.dot(matrix, target_vec) / (norm_m * norm_t)
                    top_indices = np.argsort(scores)[::-1][:limit]
                    return [(ids[idx], titles[idx], authors[idx], paths[idx]) for idx in top_indices]
        return []
    finally: conn.close()

def search_books(query, limit=20, offset=0, field='all'):
    """Legacy simple search."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    keywords = query.split()
    sql_query = "SELECT id, title, author, path, isbn, publisher, year FROM books WHERE 1=1"
    params = []
    for word in keywords:
        lp = f"%{word}%"
        if field == 'title': sql_query += " AND title LIKE ?"; params.append(lp)
        elif field == 'author': sql_query += " AND author LIKE ?"; params.append(lp)
        elif field == 'index': sql_query += " AND index_text LIKE ?"; params.append(lp)
        else:
            sql_query += " AND (title LIKE ? OR author LIKE ? OR filename LIKE ? OR index_text LIKE ?)"
            params.extend([lp, lp, lp, lp])
    sql_query += " ORDER BY title LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    try:
        cursor.execute(sql_query, params)
        return cursor.fetchall()
    except sqlite3.Error: return []
    finally: conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="+")
    args = parser.parse_args()
    data = search(" ".join(args.query))
    for r in data['results']: print(f"#{r.get('ai_rank', '?')} {r['title']}")
