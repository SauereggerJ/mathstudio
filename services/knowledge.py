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
                    "page_start": term['page_start'],
                    "name": term['name'],
                    "term_type": term['term_type'],
                    "latex_content": term['latex_content'],
                    "used_terms": term['used_terms'],
                    "status": term['status']
                }
                index_term(es_doc)

                # 2. Append to MWS Harvest File
                if term['latex_content']:
                    result = subprocess.run(
                        ["latexmlmath", "--cmml=-", "-"],
                        input=term['latex_content'],
                        capture_output=True, text=True, check=True, timeout=10
                    )
                    soup = BeautifulSoup(result.stdout, "lxml-xml")
                    math_tag = soup.find('math')
                    if math_tag:
                        math_tag.attrs = {"xmlns": "http://www.w3.org/1998/Math/MathML"}
                        harvest_entry = f'    <mws:expr url="term_{term_id}">\n        {str(math_tag)}\n    </mws:expr>\n'
                        harvest_path = "/library/mathstudio/mathstudio.harvest"
                        if os.path.exists(harvest_path):
                            with open(harvest_path, "r+") as f:
                                content = f.read()
                                if "</mws:harvest>" in content:
                                    new_content = content.replace("</mws:harvest>", harvest_entry + "</mws:harvest>")
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
                     book_id: int = None, msc: str = None, year: int = None) -> List[Dict]:
        """Federated search over knowledge terms using ES and MWS with advanced filtering and pagination."""
        from services.search import search_service
        from core.search_engine import es_client

        mws_ids = []
        # 1. Math Pass
        if "$" in query or "\\(" in query or "?" in query:
            mws_query = query.replace("$", "").replace("\\(", "").replace("\\)", "")
            mws_ids = search_service.search_mws(mws_query)

        # 2. Elasticsearch Pass
        body = {
            "query": {
                "bool": {
                    "must": [
                        {"multi_match": {"query": query, "fields": ["name^3", "latex_content", "used_terms"]}}
                    ],
                    "filter": []
                }
            },
            "from": offset,
            "size": limit
        }

        # Sorting logic in ES
        if sort == 'alpha':
            body["sort"] = [{"name.keyword": "asc"}]
        elif sort == 'newest':
            body["sort"] = [{"id": "desc"}]
        elif sort == 'type':
            body["sort"] = [{"term_type.keyword": "asc"}]
        # Default is score (relevance)
        if status:
            body["query"]["bool"]["filter"].append({"term": {"status": status}})
        if kind:
            body["query"]["bool"]["filter"].append({"term": {"term_type": kind}})
        if book_id:
            body["query"]["bool"]["filter"].append({"term": {"book_id": book_id}})

        # Metadata filters (require joining/indexing metadata into terms or using a nested filter)
        # Note: We currently store term metadata primarily in ES. If year/msc aren't in ES, 
        # we filter them during the enrichment phase below.
        # Boost MWS results if any
        if mws_ids:
            body["query"]["bool"]["should"] = [
                {"ids": {"values": [str(i) for i in mws_ids], "boost": 10.0}}
            ]

        try:
            res = es_client.search(index="mathstudio_terms", body=body)
            hits = res['hits']['hits']
            
            # 3. Finalize and Enrich with Book Info from SQLite
            results = []
            for hit in hits:
                term = hit['_source']
                # Join with Book Metadata for filtering/display
                with self.db.get_connection() as conn:
                    book = conn.execute("SELECT title, author, year, msc_class FROM books WHERE id = ?", (term['book_id'],)).fetchone()
                
                if not book: continue
                
                # Apply post-ES filters
                if msc and msc not in (book['msc_class'] or ""): continue
                if year and book['year'] != year: continue

                results.append({
                    "id": term['id'],
                    "name": term['name'],
                    "term_type": term['term_type'],
                    "page_start": term['page_start'],
                    "used_terms": term['used_terms'],
                    "status": term['status'],
                    "score": hit['_score'],
                    "book_id": term['book_id'],
                    "book_title": book['title'],
                    "book_author": book['author'],
                    "book_year": book['year']
                })
            
            if results:
                book_ids = list(set(r['book_id'] for r in results))
                placeholders = ','.join(['?'] * len(book_ids))
                with self.db.get_connection() as conn:
                    books = conn.execute(f"SELECT id, title, author FROM books WHERE id IN ({placeholders})", book_ids).fetchall()
                    book_map = {b['id']: b for b in books}
                    for r in results:
                        b_info = book_map.get(r['book_id'])
                        if b_info:
                            r['book_title'] = b_info['title']
                            r['book_author'] = b_info['author']
            
            return results
        except Exception as e:
            logger.error(f"KB Federated Search Error: {e}")
            return []

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
                       b.title as book_title, b.author as book_author
                FROM knowledge_terms t
                JOIN books b ON t.book_id = b.id
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

knowledge_service = KnowledgeService()
