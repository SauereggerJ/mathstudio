import re
import numpy as np
import sys
import json
import requests
import subprocess
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
from core.database import db
from core.ai import ai
from core.config import EMBEDDING_MODEL, ELASTICSEARCH_URL, MWS_URL
from core.search_engine import es_client

class SearchService:
    def __init__(self):
        self.db = db
        self.ai = ai
        self.es = es_client

    @lru_cache(maxsize=100)
    def get_embedding(self, text):
        """Fetches embedding from Gemini API. Cached."""
        try:
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

    def convert_to_mathml(self, latex_str):
        """Converts LaTeX to Content MathML for MWS."""
        try:
            result = subprocess.run(
                ["latexmlmath", "--cmml=-", "-"],
                input=latex_str,
                capture_output=True,
                text=True,
                check=True,
                timeout=10
            )
            return result.stdout.strip()
        except:
            return None

    def search_mws(self, latex_query):
        """Queries MathWebSearch for mathematical structures with support for variables (?a, ?b, etc.)."""
        from bs4 import BeautifulSoup
        
        # 1. Map ?a, ?b... to markers that latexmlmath treats as atomic <ci> tokens
        placeholders = re.findall(r'\?([a-z])', latex_query)
        processed_latex = latex_query
        for p in placeholders:
            # \mathrm keeps the string together as a single token in Content MathML
            processed_latex = processed_latex.replace(f"?{p}", f"\\mathrm{{MWSVAR{p}}}")

        mathml_raw = self.convert_to_mathml(processed_latex)
        if not mathml_raw:
            return []
            
        soup = BeautifulSoup(mathml_raw, "xml")
        
        # 2. Sanitize and Inject Variables
        for tag in soup.find_all(True):
            is_placeholder = False
            if tag.name == 'ci' and 'MWSVAR' in tag.text:
                var_name = tag.text.strip().replace('MWSVAR', '')
                tag.name = 'mws:qvar'
                tag.string = ''
                tag.attrs = {'name': var_name}
                is_placeholder = True
            
            if not is_placeholder:
                # Strip all attributes from non-placeholder tags
                tag.attrs = {}
        
        math_tag = soup.find('math')
        if not math_tag:
            return []
        
        # MWS expects the CONTENT of the math tag directly inside mws:expr
        inner_mathml = "".join([str(c) for c in math_tag.contents]).strip()
            
        payload = f"""<?xml version="1.0" encoding="UTF-8"?>
<mws:query xmlns:mws="http://www.mathweb.org/mws/ns">
    <mws:expr xmlns="http://www.w3.org/1998/Math/MathML">
        {inner_mathml}
    </mws:expr>
</mws:query>"""
        
        try:
            r = requests.post(
                f"{MWS_URL}/search", 
                data=payload.encode('utf-8'), 
                headers={'Content-Type': 'application/xml'}, 
                timeout=5
            )
            if r.status_code == 200:
                # Extract term IDs from MWS answer set
                # Format could be <mws:answ uri="term_123">
                ids = re.findall(r'uri="term_(\d+)"', r.text)
                return [int(tid) for tid in ids]
        except Exception as e:
            print(f"[SearchService] MWS Search Error: {e}", file=sys.stderr)
        return []

    def search_books_hybrid(self, query_text, query_vec=None, mws_term_ids=None, limit=50, field='all'):
        """Performs a hybrid Elasticsearch query combining vectors and text."""
        
        # 1. Text multi_match with boosts
        # title^4, index_text^3, toc^2, zb_review^1
        text_fields = ["title^4", "index_text^3", "toc^2", "summary", "description", "zb_review"]
        if field == 'title': text_fields = ["title"]
        elif field == 'author': text_fields = ["author"]
        elif field == 'index': text_fields = ["index_text"]

        must_clauses = []
        if query_text:
            must_clauses.append({
                "multi_match": {
                    "query": query_text,
                    "fields": text_fields,
                    "type": "best_fields"
                }
            })

        # 2. Vector kNN (if vector available)
        knn = None
        if query_vec:
            knn = {
                "field": "embedding",
                "query_vector": list(query_vec),
                "k": limit,
                "num_candidates": 100,
                "boost": 0.6 # Adjust vector influence
            }

        # 3. MWS Filtering / Boosting
        # If MWS returned terms, we can boost books containing these terms
        if mws_term_ids:
            # Note: mathstudio_books does not directly store term IDs, 
            # but we could search mathstudio_terms and aggregate book_ids.
            # For simplicity, we'll focus on the core metadata search here.
            pass

        body = {
            "query": {
                "bool": {
                    "must": must_clauses
                }
            },
            "size": limit
        }
        
        if knn:
            body["knn"] = knn

        try:
            res = self.es.search(index="mathstudio_books", body=body)
            results = []
            for hit in res['hits']['hits']:
                source = hit['_source']
                results.append({
                    'type': 'book',
                    'id': source['id'],
                    'title': source['title'],
                    'author': source['author'],
                    'path': f"{source.get('msc_class', '00')}/{source['title']}.pdf", # Placeholder path reconstruction
                    'score': hit['_score'],
                    'summary': source.get('summary', ''),
                    'index_text': source.get('index_text', ''),
                    'found_by': 'hybrid'
                })
            
            # Enrich with real paths from SQLite
            if results:
                book_ids = [r['id'] for r in results]
                placeholders = ','.join(['?'] * len(book_ids))
                with self.db.get_connection() as conn:
                    rows = conn.execute(f"SELECT id, path, year, publisher, isbn FROM books WHERE id IN ({placeholders})", book_ids).fetchall()
                    path_map = {row['id']: dict(row) for row in rows}
                    for r in results:
                        if r['id'] in path_map:
                            meta = path_map[r['id']]
                            r['path'] = meta['path']
                            r['year'] = meta['year']
                            r['publisher'] = meta['publisher']
                            r['isbn'] = meta['isbn']
            return results
        except Exception as e:
            print(f"[SearchService] ES Hybrid Search Error: {e}", file=sys.stderr)
            return []

    def get_similar_books(self, book_id, limit=5):
        """Finds books with similar embeddings and returns 4-tuples for template unpacking."""
        try:
            # 1. Fetch the source book's embedding from ES
            res = self.es.get(index="mathstudio_books", id=str(book_id))
            source_vec = res['_source'].get('embedding')
            if not source_vec:
                return []

            # 2. Perform kNN search
            knn_query = {
                "knn": {
                    "field": "embedding",
                    "query_vector": source_vec,
                    "k": limit + 1,
                    "num_candidates": 50
                },
                "_source": ["id", "title", "author"]
            }
            res = self.es.search(index="mathstudio_books", body=knn_query)
            
            candidate_ids = []
            for hit in res['hits']['hits']:
                if int(hit['_id']) == book_id: continue
                candidate_ids.append(int(hit['_id']))
            
            if not candidate_ids:
                return []

            # 3. Enrich with paths from SQLite and return as tuples
            placeholders = ','.join(['?'] * len(candidate_ids))
            with self.db.get_connection() as conn:
                rows = conn.execute(
                    f"SELECT id, title, author, path FROM books WHERE id IN ({placeholders})", 
                    candidate_ids
                ).fetchall()
                
                # Order by original similarity (ES hits order)
                row_map = {row['id']: (row['id'], row['title'], row['author'], row['path']) for row in rows}
                return [row_map[bid] for bid in candidate_ids if bid in row_map][:limit]

        except Exception as e:
            print(f"[SearchService] Similar Books Error: {e}", file=sys.stderr)
            return []

    def get_book_matches(self, book_id, query, limit=20):
        """Legacy helper for granular matches within a book, now using ES pages."""
        results, _ = self.search_within_book(book_id, query, limit=limit)
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
            if c.get('summary'): text += f" | Summary: {c['summary'][:200]}"
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
        
        picked_ids = {r['id'] for r in reranked}
        for c in candidates:
            if c['id'] not in picked_ids:
                reranked.append(c)
        
        return reranked[:limit]

    def get_chapters(self, book_id):
        """Returns structured Table of Contents from SQLite."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT title, level, page, msc_code, topics FROM chapters WHERE book_id = ? ORDER BY id ASC", (book_id,))
            return [tuple(r) for r in cursor.fetchall()]

    def search_within_book(self, book_id, query, limit=50):
        """Searches for a query within a specific book using Elasticsearch."""
        body = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"book_id": book_id}},
                        {"match": {"content": query}}
                    ]
                }
            },
            "highlight": {
                "fields": {
                    "content": {}
                },
                "pre_tags": ["<b>"],
                "post_tags": ["</b>"]
            },
            "size": limit
        }
        try:
            res = self.es.search(index="mathstudio_pages", body=body)
            rows = []
            for hit in res['hits']['hits']:
                snippet = hit.get('highlight', {}).get('content', [""])[0]
                rows.append({
                    'page': hit['_source']['page_number'],
                    'snippet': snippet
                })
            return rows, True
        except Exception as e:
            print(f"[SearchService] Search Within Book Error: {e}", file=sys.stderr)
            return [], False

    def search(self, query, limit=20, offset=0, use_fts=True, use_vector=True, use_translate=False, use_rerank=False, field='all'):
        """Main search orchestration using Federated Search (ES + MWS)."""
        search_query = query
        expanded_query = None
        query_vec = None
        mws_term_ids = []
        
        # 1. Pre-processing & Math Pass
        with ThreadPoolExecutor(max_workers=3) as executor:
            exp_future = executor.submit(self.expand_query, query) if use_translate else None
            
            # Detect LaTeX ($...$ or \(...\))
            if "$" in query or "\\(" in query:
                mws_future = executor.submit(self.search_mws, query)
            else:
                mws_future = None

            if use_vector:
                emb_future = executor.submit(self.get_embedding, query)
            else:
                emb_future = None

            if exp_future:
                expanded_query = exp_future.result()
                search_query = expanded_query
            
            if mws_future:
                mws_term_ids = mws_future.result()
                
            if emb_future:
                query_vec = emb_future.result()

        # 2. Hybrid Search Pass (ES)
        results = self.search_books_hybrid(
            query_text=search_query, 
            query_vec=query_vec, 
            mws_term_ids=mws_term_ids, 
            limit=100, 
            field=field
        )

        # 3. Index Lookup & Scoring
        for c in results:
            if c.get('index_text'):
                idx_match = self.extract_index_pages(c['index_text'], query)
                if idx_match:
                    c['index_matches'] = idx_match
                    c['score'] += 0.5

        # 4. Finalize results
        final_list = sorted(results, key=lambda x: x['score'], reverse=True)
        total_count = len(final_list)
        paged_results = final_list[offset : offset + limit]

        # 5. AI Reranking
        if use_rerank and paged_results:
            paged_results = self.rerank_results(query, paged_results, limit=limit)

        return {
            'results': paged_results,
            'total_count': total_count,
            'expanded_query': expanded_query if expanded_query != query else None,
            'mws_hits': len(mws_term_ids) if mws_term_ids else 0
        }

# Global instance
search_service = SearchService()
