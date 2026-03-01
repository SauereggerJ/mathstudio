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

    def update_term_status(self, term_id: int, status: str) -> bool:
        """Updates the status of a term (e.g., 'draft' -> 'approved')."""
        if status not in ('draft', 'approved'):
            return False
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                "UPDATE knowledge_terms SET status = ?, updated_at = unixepoch() WHERE id = ?",
                (status, term_id)
            )
            return cursor.rowcount > 0

    def delete_term(self, term_id: int) -> bool:
        """Deletes a term and its FTS index entry."""
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM knowledge_terms WHERE id = ?", (term_id,))
            conn.execute("DELETE FROM knowledge_terms_fts WHERE rowid = ?", (term_id,))
            return True

    # ──────────────────────────────────────────────
    # Search & Browse
    # ──────────────────────────────────────────────

    def search_terms(self, query: str, kind: str = None, status: str = 'approved', limit: int = 50) -> List[Dict]:
        """FTS search over knowledge terms."""
        with self.db.get_connection() as conn:
            sql = """
                SELECT t.id, t.name, t.term_type, t.page_start, t.used_terms, t.status,
                       b.title as book_title, b.author as book_author
                FROM knowledge_terms_fts f
                JOIN knowledge_terms t ON f.rowid = t.id
                JOIN books b ON t.book_id = b.id
                WHERE knowledge_terms_fts MATCH ?
            """
            params = [query]
            if status:
                sql += " AND t.status = ?"
                params.append(status)
            if kind:
                sql += " AND t.term_type = ?"
                params.append(kind)
            
            sql += " ORDER BY rank LIMIT ?"
            params.append(limit)
            
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def browse_terms(self, letter: str = None, sort: str = 'alpha',
                     kind: str = None, status: str = 'approved', 
                     limit: int = 100, offset: int = 0) -> Dict[str, Any]:
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
