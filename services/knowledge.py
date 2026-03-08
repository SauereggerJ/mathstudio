"""
Knowledge Base Service — Flat Term Index

A simplified KB where each extracted term (theorem/definition/lemma/etc.) is an 
independent entity tied to its specific book and page.

Features:
- Flat Term Storage (book_id + page + latex + keywords)
- FTS search over terms
- Alphabetical browsing with sort options
- Status management (draft/approved)
"""

import json
import logging
import time
from typing import List, Dict, Any, Optional

from core.database import db

logger = logging.getLogger(__name__)

VALID_KINDS = {'definition', 'theorem', 'lemma', 'proposition',
               'corollary', 'example', 'exercise', 'axiom', 'notation'}


class KnowledgeService:
    def __init__(self):
        self.db = db

    # ──────────────────────────────────────────────
    # Term Management
    # ──────────────────────────────────────────────

    def get_term(self, term_id: int) -> Optional[Dict[str, Any]]:
        """Returns full term details with book info."""
        with self.db.get_connection() as conn:
            row = conn.execute("""
                SELECT t.*, b.title as book_title, b.author as book_author, b.path as book_path
                FROM knowledge_terms t
                JOIN books b ON t.book_id = b.id
                WHERE t.id = ?
            """, (term_id,)).fetchone()
        return dict(row) if row else None

    def sync_term_to_federated(self, term_id: int) -> bool:
        """Pushes a term to Elasticsearch and MathWebSearch."""
        try:
            from core.search_engine import index_term
            import subprocess
            from bs4 import BeautifulSoup
            import os

            with self.db.get_connection() as conn:
                term = conn.execute("SELECT * FROM knowledge_terms WHERE id = ?", (term_id,)).fetchone()
                if not term:
                    return False
                
                # 1. Sync to ES
                es_doc = {
                    "id": term['id'],
                    "book_id": term['book_id'],
                    "concept_id": term['concept_id'],
                    "page_start": term['page_start'],
                    "name": term['name'],
                    "term_type": term['term_type'],
                    "latex_content": term['latex_content'],
                    "used_terms": term['used_terms'],
                    "status": term['status']
                }
                index_term(es_doc)

                # 2. Append to MWS Harvest File
                import re
                if term['latex_content']:
                    math_blocks = []
                    # Extract display math blocks
                    math_blocks.extend(re.findall(r'\\\[(.*?)\\\]', term['latex_content'], re.DOTALL))
                    math_blocks.extend(re.findall(r'\$\$(.*?)\$\$', term['latex_content'], re.DOTALL))
                    for env in ['equation', 'align', 'gather', 'eqnarray', 'multline']:
                        math_blocks.extend(re.findall(f'\\\\begin\\{{{env}\\}}(.*?)\\\\end\\{{{env}\\}}', term['latex_content'], re.DOTALL))
                    
                    harvest_elements = []
                    for idx, math_src in enumerate(math_blocks):
                        if not math_src.strip(): continue
                        try:
                            result = subprocess.run(
                                ["latexmlmath", "--cmml=-", "-"],
                                input=math_src.strip(),
                                capture_output=True, text=True, timeout=5
                            )
                            if result.returncode == 0:
                                soup = BeautifulSoup(result.stdout, "lxml-xml")
                                math_tag = soup.find('math')
                                if math_tag:
                                    math_tag.attrs = {"xmlns": "http://www.w3.org/1998/Math/MathML"}
                                    harvest_elements.append(f'    <mws:expr url="term_{term_id}_{idx}">\n        {str(math_tag)}\n    </mws:expr>\n')
                        except Exception as e:
                            logger.error(f"[KnowledgeService] MathML conversion failed for snippet on term {term_id}: {e}")
                    
                    if harvest_elements:
                        harvest_path = "/library/mathstudio/mathstudio.harvest"
                        if os.path.exists(harvest_path):
                            with open(harvest_path, "r+") as f:
                                content = f.read()
                                if "</mws:harvest>" in content:
                                    new_content = content.replace("</mws:harvest>", "".join(harvest_elements) + "</mws:harvest>")
                                    f.seek(0)
                                    f.write(new_content)
                                    f.truncate()
            return True
        except Exception as e:
            logger.error(f"[KnowledgeService] Sync Error for term {term_id}: {e}")
            return False

    def update_term_status(self, term_id: int, status: str) -> bool:
        """Updates the status of a term and syncs to search engines if approved."""
        if status not in ('draft', 'approved'):
            return False
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                "UPDATE knowledge_terms SET status = ?, updated_at = unixepoch() WHERE id = ?",
                (status, term_id)
            )
            success = cursor.rowcount > 0
            
        if success and status == 'approved':
            self.sync_term_to_federated(term_id)

        return success

    def delete_term(self, term_id: int) -> bool:
        """Deletes a term and its FTS index entry."""
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM knowledge_terms WHERE id = ?", (term_id,))
            conn.execute("DELETE FROM knowledge_terms_fts WHERE rowid = ?", (term_id,))
            return True

    # ──────────────────────────────────────────────
    # Search & Browse
    # ──────────────────────────────────────────────

    def search_terms(self, query: str, kind: str = None, status: str = 'approved', 
                     limit: int = 250, offset: int = 0, sort: str = 'score',
                     book_id: int = None, msc: str = None, year: int = None,
                     concept_id: int = None) -> List[Dict]:
        """3-Pass Hybrid Semantic Search over knowledge terms.
        
        Architecture:
          1. Zero-Text Detection: bypass vectorization for pure-LaTeX queries.
          2. Parallel Pre-fetch: Concept Harvesting (kNN on concepts) + MWS formula pass.
          3. Hybrid Retrieval with manual Reciprocal Rank Fusion (RRF):
             - BM25 text match on terms
             - kNN vector match on terms
             - Concept membership boost + MWS structural boost
        """
        import re
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from services.search import search_service
        from core.search_engine import es_client
        from core.config import EMBEDDING_MODEL
        from core.ai import ai

        RRF_K = 60  # Standard RRF constant
        CONCEPT_BONUS = 0.15  # Additive RRF bonus for concept membership
        MWS_BONUS = 0.20  # Additive RRF bonus for MWS structural match

        # ── Step 0: Detect pure-LaTeX queries ──
        stripped = query.strip()
        is_pure_latex = bool(
            re.match(r'^[\$\\]', stripped) and 
            not re.search(r'[a-zA-Z]{4,}', re.sub(r'\\[a-zA-Z]+', '', stripped))
        )

        # ── Step 1: Parallel Pre-fetch ──
        query_vec = None
        concept_ids = []
        mws_ids = []

        def _vectorize_and_harvest():
            """Vectorize query and harvest top concepts via kNN."""
            nonlocal query_vec, concept_ids
            try:
                result = ai.client.models.embed_content(
                    model=EMBEDDING_MODEL,
                    contents=[query[:10000]],
                    config={"task_type": "RETRIEVAL_QUERY", "output_dimensionality": 768}
                )
                query_vec = result.embeddings[0].values
                
                # kNN against concepts index
                concept_res = es_client.search(
                    index="mathstudio_concepts",
                    body={
                        "knn": {
                            "field": "embedding",
                            "query_vector": list(query_vec),
                            "k": 3,
                            "num_candidates": 20
                        },
                        "_source": ["id", "name"],
                        "size": 3
                    }
                )
                concept_ids = [int(hit['_id']) for hit in concept_res['hits']['hits']]
                logger.info(f"[SemanticSearch] Harvested concepts: {[hit['_source']['name'] for hit in concept_res['hits']['hits']]}")
            except Exception as e:
                logger.error(f"[SemanticSearch] Vectorize/Harvest Error: {e}")

        def _mws_pass():
            """Structural formula search via MathWebSearch."""
            nonlocal mws_ids
            if "$" in query or "\\(" in query or "?" in query:
                mws_query = query.replace("$", "").replace("\\(", "").replace("\\)", "")
                mws_ids = search_service.search_mws(mws_query)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = []
            if not is_pure_latex:
                futures.append(executor.submit(_vectorize_and_harvest))
            futures.append(executor.submit(_mws_pass))
            for f in as_completed(futures):
                f.result()  # propagate exceptions

        # ── Step 2: Build ES filters ──
        filters = []
        if status:
            filters.append({"term": {"status": status}})
        if kind:
            filters.append({"term": {"term_type": kind}})
        if book_id:
            filters.append({"term": {"book_id": book_id}})
        if concept_id:
            filters.append({"term": {"concept_id": concept_id}})

        # ── Step 3a: BM25 Text Search ──
        bm25_body = {
            "query": {
                "bool": {
                    "must": [
                        {"multi_match": {"query": query, "fields": ["name^3", "latex_content", "used_terms"]}}
                    ],
                    "filter": filters
                }
            },
            "size": min(limit * 3, 250),  # Fetch wider pool for fusion
            "_source": ["id", "book_id", "concept_id", "page_start", "name", "term_type", "used_terms", "status"]
        }
        # Boost MWS results in BM25 pass
        if mws_ids:
            bm25_body["query"]["bool"]["should"] = [
                {"ids": {"values": [str(i) for i in mws_ids], "boost": 10.0}}
            ]

        bm25_hits = []
        try:
            res = es_client.search(index="mathstudio_terms", body=bm25_body)
            bm25_hits = res['hits']['hits']
        except Exception as e:
            logger.error(f"[SemanticSearch] BM25 Error: {e}")

        # ── Step 3b: kNN Vector Search (if we have a vector) ──
        knn_hits = []
        if query_vec is not None:
            knn_body = {
                "knn": {
                    "field": "embedding",
                    "query_vector": list(query_vec),
                    "k": min(limit * 3, 250),
                    "num_candidates": 300
                },
                "size": min(limit * 3, 250),
                "_source": ["id", "book_id", "concept_id", "page_start", "name", "term_type", "used_terms", "status"]
            }
            # Apply same filters to kNN
            if filters:
                knn_body["knn"]["filter"] = {"bool": {"filter": filters}}
            try:
                res = es_client.search(index="mathstudio_terms", body=knn_body)
                knn_hits = res['hits']['hits']
            except Exception as e:
                logger.error(f"[SemanticSearch] kNN Error: {e}")

        # ── Step 4: Reciprocal Rank Fusion ──
        rrf_scores = {}  # doc_id -> cumulative RRF score
        doc_sources = {}  # doc_id -> hit source data

        # Score from BM25 ranking
        for rank, hit in enumerate(bm25_hits):
            doc_id = int(hit['_id'])
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + 1.0 / (RRF_K + rank + 1)
            doc_sources[doc_id] = hit['_source']

        # Score from kNN ranking
        for rank, hit in enumerate(knn_hits):
            doc_id = int(hit['_id'])
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + 1.0 / (RRF_K + rank + 1)
            if doc_id not in doc_sources:
                doc_sources[doc_id] = hit['_source']

        # Concept membership bonus
        if concept_ids:
            mws_id_set = set(mws_ids)
            for doc_id, source in doc_sources.items():
                cid = source.get('concept_id')
                if cid and cid in concept_ids:
                    rrf_scores[doc_id] += CONCEPT_BONUS
                # MWS structural bonus
                if doc_id in mws_id_set:
                    rrf_scores[doc_id] += MWS_BONUS

        # Sort by fused score
        if sort == 'alpha':
            ranked_ids = sorted(rrf_scores.keys(), key=lambda did: doc_sources[did].get('name', ''))
        elif sort == 'newest':
            ranked_ids = sorted(rrf_scores.keys(), key=lambda did: doc_sources[did].get('id', 0), reverse=True)
        elif sort == 'type':
            ranked_ids = sorted(rrf_scores.keys(), key=lambda did: doc_sources[did].get('term_type', ''))
        else:
            ranked_ids = sorted(rrf_scores.keys(), key=lambda did: rrf_scores[did], reverse=True)

        paged_ids = ranked_ids[offset:offset + limit]

        # ── Step 5: Enrich with Book & Concept Metadata from SQLite ──
        if not paged_ids:
            return []

        all_book_ids = list(set(doc_sources[did].get('book_id') for did in paged_ids if doc_sources[did].get('book_id')))
        all_concept_ids = list(set(doc_sources[did].get('concept_id') for did in paged_ids if doc_sources[did].get('concept_id')))
        
        book_map = {}
        concept_map = {}
        
        with self.db.get_connection() as conn:
            if all_book_ids:
                placeholders = ','.join(['?'] * len(all_book_ids))
                books = conn.execute(
                    f"SELECT id, title, author, year, msc_class FROM books WHERE id IN ({placeholders})", 
                    all_book_ids
                ).fetchall()
                book_map = {b['id']: dict(b) for b in books}
            
            if all_concept_ids:
                placeholders = ','.join(['?'] * len(all_concept_ids))
                concepts = conn.execute(
                    f"SELECT id, name FROM mathematical_concepts WHERE id IN ({placeholders})",
                    all_concept_ids
                ).fetchall()
                concept_map = {c['id']: c['name'] for c in concepts}

        results = []
        for did in paged_ids:
            source = doc_sources[did]
            book = book_map.get(source.get('book_id'), {})

            # Post-ES metadata filters
            if msc and msc not in (book.get('msc_class') or ''):
                continue
            if year and book.get('year') != year:
                continue

            results.append({
                "id": source['id'],
                "name": source['name'],
                "term_type": source.get('term_type'),
                "page_start": source.get('page_start'),
                "used_terms": source.get('used_terms'),
                "status": source.get('status'),
                "score": round(rrf_scores[did], 6),
                "book_id": source.get('book_id'),
                "book_title": book.get('title', ''),
                "book_author": book.get('author', ''),
                "book_year": book.get('year'),
                "concept_id": source.get('concept_id'),
                "concept_name": concept_map.get(source.get('concept_id'))
            })

        return results

    def browse_terms(self, letter: str = None, sort: str = 'alpha',
                     kind: str = None, status: str = 'approved', 
                     limit: int = 500, offset: int = 0) -> Dict[str, Any]:
        """Browse terms by letter with sorting."""
        with self.db.get_connection() as conn:
            where_clauses = []
            params = []

            if status:
                where_clauses.append("t.status = ?")
                params.append(status)

            if letter and len(letter) == 1 and letter.isalpha():
                where_clauses.append("UPPER(SUBSTR(t.name, 1, 1)) = ?")
                params.append(letter.upper())

            if kind and kind in VALID_KINDS:
                where_clauses.append("t.term_type = ?")
                params.append(kind)

            where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

            if sort == 'newest':
                order_sql = "ORDER BY t.created_at DESC"
            else:  # alpha (default)
                order_sql = "ORDER BY t.name ASC"

            # Total count
            count_row = conn.execute(f"SELECT COUNT(*) as total FROM knowledge_terms t {where_sql}", params).fetchone()
            total = count_row['total']

            # Fetch page
            results = conn.execute(f"""
                SELECT t.id, t.name, t.term_type, t.page_start, t.used_terms, t.status, t.created_at, t.latex_content,
                       b.title as book_title, b.author as book_author, c.name as concept_name, t.concept_id
                FROM knowledge_terms t
                JOIN books b ON t.book_id = b.id
                LEFT JOIN mathematical_concepts c ON t.concept_id = c.id
                {where_sql}
                {order_sql}
                LIMIT ? OFFSET ?
            """, params + [limit, offset]).fetchall()

            # Letter counts for the alphabet bar
            letter_counts = conn.execute(f"""
                SELECT UPPER(SUBSTR(name, 1, 1)) as letter, COUNT(*) as cnt
                FROM knowledge_terms t
                {where_sql}
                GROUP BY letter
                ORDER BY letter
            """, params).fetchall()

            return {
                "terms": [dict(r) for r in results],
                "total": total,
                "letter_counts": {r['letter']: r['cnt'] for r in letter_counts}
            }

    def get_term_count(self, status: str = 'draft') -> int:
        """Returns count of terms with specific status."""
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM knowledge_terms WHERE status = ?", (status,)).fetchone()
        return row['cnt'] if row else 0

    def search_concepts(self, query: str, limit: int = 20) -> List[Dict]:
        """Search for canonical concepts in the database."""
        from core.search_engine import es_client
        body = {
            "query": {
                "bool": {
                    "should": [
                        {"match": {"name": {"query": query, "boost": 2.0}}},
                        {"match": {"description": query}}
                    ]
                }
            },
            "size": limit
        }
        try:
            res = es_client.search(index="mathstudio_concepts", body=body)
            hits = res['hits']['hits']
            return [{"id": int(hit['_id']), "name": hit['_source']['name'], "description": hit['_source'].get('description', '')} for hit in hits]
        except Exception as e:
            logger.error(f"[KnowledgeService] Concept Search Error: {e}")
            # Fallback to SQLite
            with self.db.get_connection() as conn:
                rows = conn.execute(
                    "SELECT id, name, description FROM mathematical_concepts WHERE name LIKE ? OR description LIKE ? LIMIT ?", 
                    (f"%{query}%", f"%{query}%", limit)
                ).fetchall()
                return [dict(r) for r in rows]

knowledge_service = KnowledgeService()
