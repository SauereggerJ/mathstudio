import re
import numpy as np
import sys
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
from core.database import db
from core.ai import ai
from core.config import EMBEDDING_MODEL

class SearchService:
    def __init__(self):
        self.db = db
        self.ai = ai

    @lru_cache(maxsize=100)
    def get_embedding(self, text):
        """Fetches embedding from Gemini API. Cached."""
        try:
            # Note: Using the new SDK via core.ai client
            result = self.ai.client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=[text[:10000]],
                config={"task_type": "RETRIEVAL_QUERY", "output_dimensionality": 768}
            )
            return tuple(result.embeddings[0].values)
        except Exception as e:
            print(f"[SearchService] Embedding API Error: {e}", file=sys.stderr)
            return None

    @lru_cache(maxsize=100)
    def expand_query(self, query):
        """Translates and expands the query using LLM. Cached."""
        prompt = (
            "You are a mathematical search expert. Translate this query to English if it's in another language, "
            "and add 3-5 relevant mathematical keywords or synonyms to improve search recall. "
            "Return ONLY the expanded query text.\n"
            f"Query: {query}"
        )
        return self.ai.generate_text(prompt) or query

    def search_books_fts(self, query, limit=50, field='all'):
        """Performs a Full Text Search using the books_fts table."""
        clean_query = query.replace('"', '""')
        fts_query = f'"{clean_query}"'
        
        if field == 'title': fts_query = f'title : "{clean_query}"'
        elif field == 'author': fts_query = f'author : "{clean_query}"'
        elif field == 'index': fts_query = f'index_content : "{clean_query}"'

        snippet_col = 3 if field == 'index' else -1

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
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (fts_query, limit))
            return [dict(row) for row in cursor.fetchall()]

    def search_books_semantic(self, query_vec, top_k=50):
        """Performs semantic search using vector embeddings."""
        if not query_vec:
            return []
            
        query_vec = np.array(query_vec, dtype=np.float32)
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, embedding FROM books WHERE embedding IS NOT NULL")
            rows = cursor.fetchall()
            
            if not rows: return []
            
            ids, vectors = [], []
            for r in rows:
                if not r['embedding']: continue
                vec = np.frombuffer(r['embedding'], dtype=np.float32)
                if len(vec) != len(query_vec): continue
                ids.append(r['id'])
                vectors.append(vec)
                
            if not vectors: return []

            matrix = np.array(vectors)
            norm_q = np.linalg.norm(query_vec)
            norm_m = np.linalg.norm(matrix, axis=1)
            norm_m[norm_m == 0] = 1e-10
            if norm_q == 0: norm_q = 1e-10
            
            scores = np.dot(matrix, query_vec) / (norm_m * norm_q)
            
            if len(scores) < top_k:
                top_indices = np.argsort(scores)[::-1]
            else:
                top_indices = np.argpartition(scores, -top_k)[-top_k:]
                top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]
                
            top_ids = [ids[i] for i in top_indices]
            id_score_map = {ids[i]: float(scores[i]) for i in top_indices}
            
            if not top_ids: return []

            placeholders = ','.join(['?'] * len(top_ids))
            sql = f"""
                SELECT id, title, author, path, isbn, publisher, year, summary, index_text 
                FROM books WHERE id IN ({placeholders})
            """
            cursor.execute(sql, top_ids)
            results = []
            for r in cursor.fetchall():
                bid = r['id']
                results.append({
                    'type': 'book', 
                    'id': bid, 
                    'title': r['title'], 
                    'author': r['author'],
                    'path': r['path'], 
                    'isbn': r['isbn'], 
                    'publisher': r['publisher'],
                    'year': r['year'], 
                    'score': id_score_map[bid], 
                    'summary': r['summary'],
                    'index_text': r['index_text']
                })
            
            results.sort(key=lambda x: x['score'], reverse=True)
            return results

    def extract_index_pages(self, index_text, query):
        if not index_text or not query: return None
        queries = [query]
        if '-' in query: queries.append(query.replace('-', ' '))
        if ' ' in query: queries.append(query.replace(' ', '-'))
        
        all_found_pages, seen = [], set()
        for q in queries:
            for match in re.finditer(re.escape(q), index_text, re.IGNORECASE):
                start_pos = match.end()
                chunk = index_text[start_pos:start_pos + 300]
                num_matches = re.findall(r'[\s,]*(\d+(?:[\s,–\.-]+\d+)*)', chunk)
                for m in num_matches:
                    cleaned = m.strip(' .,-')
                    if cleaned and cleaned not in seen:
                        all_found_pages.append(cleaned)
                        seen.add(cleaned)
                if all_found_pages: break
        return ", ".join(all_found_pages) if all_found_pages else None

    def rerank_results(self, query, candidates, limit=10):
        if not candidates: return []
        
        prompt = (
            f"You are a strict mathematics librarian. Rank the following book candidates for the search query: '{query}'.\n"
            "Exclude irrelevant books. Focus on mathematical depth and relevance.\n\n"
            "Candidates:\n"
        )
        for c in candidates:
            text = f"Title: {c['title']} | Author: {c['author']}"
            if c.get('snippet'): text += f" | Snippet: {c['snippet']}"
            elif c.get('summary'): text += f" | Summary: {c['summary'][:200]}"
            prompt += f"[ID {c['id']}] {text}\n"
        
        prompt += "\nReturn ONLY a JSON list of objects for the top 10 results, e.g. [{\"id\": 15, \"reason\": \"Detailed treatment of topic X\"}, {\"id\": 2, \"reason\": \"Standard reference for Y\"}]."

        reranked_data = self.ai.generate_json(prompt)
        if not reranked_data: return candidates[:limit]

        id_map = {c['id']: c for c in candidates}
        reranked = []
        for entry in reranked_data:
            bid = entry.get('id')
            if bid in id_map:
                item = id_map[bid].copy()
                item['ai_rank'] = len(reranked) + 1
                item['ai_reason'] = entry.get('reason', '')
                reranked.append(item)
        
        # Add remaining candidates that weren't picked by AI
        picked_ids = {r['id'] for r in reranked}
        for c in candidates:
            if c['id'] not in picked_ids:
                reranked.append(c)
        
        return reranked[:limit]

    def search(self, query, limit=20, offset=0, use_fts=True, use_vector=True, use_translate=False, use_rerank=False, field='all'):
        """Main search orchestration."""
        search_query = query
        expanded_query = None
        query_vec = None
        
        # 1. Pre-processing (Expansion & Embedding)
        with ThreadPoolExecutor(max_workers=2) as executor:
            exp_future = executor.submit(self.expand_query, query) if use_translate else None
            
            if use_vector and not use_translate:
                emb_future = executor.submit(self.get_embedding, query)
            else:
                emb_future = None

            if exp_future:
                expanded_query = exp_future.result()
                search_query = expanded_query
                if use_vector:
                    query_vec = self.get_embedding(search_query)
            elif emb_future:
                query_vec = emb_future.result()

        candidates = {}

        # 2. Vector Search
        if use_vector and query_vec:
            vec_results = self.search_books_semantic(query_vec)
            for res in vec_results:
                if res['score'] < 0.25: continue
                key = f"B_{res['id']}"
                candidates[key] = res
                candidates[key]['found_by'] = 'vector'

        # 3. FTS Search
        if use_fts:
            fts_results = self.search_books_fts(search_query, limit=100, field=field)
            for i, row in enumerate(fts_results):
                bid = row['id']
                key = f"B_{bid}"
                fts_score = 1.0 - (i / 100.0)
                
                if key in candidates:
                    candidates[key]['score'] = (candidates[key]['score'] * 0.6) + (fts_score * 0.4)
                    candidates[key]['found_by'] = 'both'
                    candidates[key]['snippet'] = row['snippet']
                else:
                    candidates[key] = {
                        **row,
                        'type': 'book',
                        'score': fts_score,
                        'found_by': 'text'
                    }

        # 4. Index Lookup & Scoring
        for key, c in candidates.items():
            if c.get('index_text'):
                idx_match = self.extract_index_pages(c['index_text'], query)
                if idx_match:
                    c['index_matches'] = idx_match
                    c['score'] += 0.5

        # 5. Finalize results
        final_list = sorted(candidates.values(), key=lambda x: x['score'], reverse=True)
        total_count = len(final_list)
        paged_results = final_list[offset : offset + limit]

        # 6. AI Reranking
        if use_rerank and paged_results:
            paged_results = self.rerank_results(query, paged_results, limit=limit)

        return {
            'results': paged_results,
            'total_count': total_count,
            'expanded_query': expanded_query if expanded_query != query else None
        }

# Global instance
search_service = SearchService()
