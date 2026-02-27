"""
Knowledge Base Service — Theorem/Definition Location Index

A simplified KB where each concept (theorem/definition/lemma/etc.) maps to
N locations in the library. Each location is a book + page backed by cached LaTeX.

Features:
- Concept CRUD (name, kind, domain, aliases)
- Location entries (book_id + page → linked to extracted_pages cache)
- FTS search over concepts
- Alphabet browsing with sort options
- Proposal management (auto-discovered items from LaTeX conversion)
"""

import json
import logging
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from core.database import db
from core.config import LIBRARY_ROOT, PROJECT_ROOT

logger = logging.getLogger(__name__)

VALID_KINDS = {'definition', 'theorem', 'lemma', 'proposition',
               'corollary', 'example', 'axiom', 'notation'}


class KnowledgeService:
    def __init__(self):
        self.db = db

    # ──────────────────────────────────────────────
    # Concept CRUD
    # ──────────────────────────────────────────────

    def add_concept(self, name: str, kind: str, domain: str = None,
                    aliases: list = None) -> Dict[str, Any]:
        """Creates a new concept. Returns the new concept dict."""
        if kind not in VALID_KINDS:
            return {"success": False, "error": f"Invalid kind. Must be one of: {sorted(VALID_KINDS)}"}

        with self.db.get_connection() as conn:
            existing = conn.execute(
                "SELECT id, name FROM concepts WHERE LOWER(name) = ?", (name.lower(),)
            ).fetchone()
            if existing:
                return {"success": False, "error": f"Concept '{existing['name']}' already exists (ID {existing['id']})"}

            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO concepts (name, kind, domain, aliases)
                VALUES (?, ?, ?, ?)
            """, (name, kind, domain, json.dumps(aliases or [])))
            new_id = cursor.lastrowid
            self._sync_concept_fts(conn, new_id)

        return {"success": True, "id": new_id}

    def update_concept(self, concept_id: int, **kwargs) -> Dict[str, Any]:
        """Updates concept fields (name, kind, domain, aliases)."""
        allowed = {'name', 'kind', 'domain', 'aliases'}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return {"success": False, "error": "No valid fields to update"}

        if 'aliases' in updates:
            updates['aliases'] = json.dumps(updates['aliases'])

        updates['updated_at'] = int(time.time())

        query = "UPDATE concepts SET " + ", ".join(f"{k} = ?" for k in updates.keys())
        query += " WHERE id = ?"

        with self.db.get_connection() as conn:
            cursor = conn.execute(query, list(updates.values()) + [concept_id])
            if cursor.rowcount == 0:
                return {"success": False, "error": "Concept not found"}
            if 'name' in updates or 'aliases' in updates:
                self._sync_concept_fts(conn, concept_id)

        return {"success": True}

    def delete_concept(self, concept_id: int) -> Dict[str, Any]:
        """Deletes a concept and all its entries."""
        with self.db.get_connection() as conn:
            cursor = conn.execute("DELETE FROM concepts WHERE id = ?", (concept_id,))
            if cursor.rowcount == 0:
                return {"success": False, "error": "Concept not found"}
            conn.execute("DELETE FROM entries WHERE concept_id = ?", (concept_id,))
            conn.execute("DELETE FROM concept_fts WHERE rowid = ?", (concept_id,))
        return {"success": True}

    def get_concept(self, concept_id: int) -> Optional[Dict[str, Any]]:
        """Returns concept with all location entries and their cached LaTeX."""
        with self.db.get_connection() as conn:
            concept = conn.execute(
                "SELECT * FROM concepts WHERE id = ?", (concept_id,)
            ).fetchone()
            if not concept:
                return None

            entries = conn.execute("""
                SELECT e.id, e.book_id, e.page_start, e.page_end, e.statement, e.notes,
                       e.confidence, e.is_canonical, e.created_at,
                       b.title as book_title, b.author as book_author, b.path as book_path
                FROM entries e
                LEFT JOIN books b ON e.book_id = b.id
                WHERE e.concept_id = ?
                ORDER BY e.is_canonical DESC, e.created_at ASC
            """, (concept_id,)).fetchall()

            # Load cached LaTeX for each entry's page
            enriched_entries = []
            for e in entries:
                entry = dict(e)
                if entry['book_id'] and entry['page_start']:
                    cached = conn.execute("""
                        SELECT latex_path, markdown_path, quality_score 
                        FROM extracted_pages 
                        WHERE book_id = ? AND page_number = ?
                    """, (entry['book_id'], entry['page_start'])).fetchone()
                    if cached:
                        entry['has_latex'] = True
                        entry['quality_score'] = cached['quality_score']
                        # Load actual LaTeX content
                        latex_path = PROJECT_ROOT / cached['latex_path']
                        if latex_path.exists():
                            try:
                                entry['latex_content'] = latex_path.read_text(encoding='utf-8')
                            except Exception:
                                entry['latex_content'] = None
                        else:
                            entry['latex_content'] = None
                    else:
                        entry['has_latex'] = False
                        entry['latex_content'] = None
                enriched_entries.append(entry)

        result = dict(concept)
        result['aliases'] = json.loads(result.get('aliases') or '[]')
        result['entries'] = enriched_entries
        return result

    # ──────────────────────────────────────────────
    # Location Management (simplified entry CRUD)
    # ──────────────────────────────────────────────

    def add_location(self, concept_name: str, kind: str, book_id: int,
                     page: int, statement_preview: str = None) -> Dict[str, Any]:
        """Primary method: register where a theorem/definition appears.
        
        Finds or creates the concept, adds a book+page entry.
        If the page is already cached in extracted_pages, it links automatically.
        """
        if kind not in VALID_KINDS:
            kind = 'theorem'

        with self.db.get_connection() as conn:
            # Find or create concept (case-insensitive match)
            concept = conn.execute(
                "SELECT id FROM concepts WHERE LOWER(name) = ?", (concept_name.lower(),)
            ).fetchone()

            if concept:
                concept_id = concept['id']
            else:
                # Fuzzy match before creating new
                try:
                    from rapidfuzz import fuzz
                    all_concepts = conn.execute("SELECT id, name FROM concepts").fetchall()
                    for c in all_concepts:
                        if fuzz.ratio(concept_name.lower(), c['name'].lower()) >= 90:
                            concept_id = c['id']
                            break
                    else:
                        cursor = conn.cursor()
                        cursor.execute("INSERT INTO concepts (name, kind) VALUES (?, ?)",
                                      (concept_name, kind))
                        concept_id = cursor.lastrowid
                except ImportError:
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO concepts (name, kind) VALUES (?, ?)",
                                  (concept_name, kind))
                    concept_id = cursor.lastrowid

            # Check for duplicate entry (same concept + book + page)
            existing = conn.execute("""
                SELECT id FROM entries 
                WHERE concept_id = ? AND book_id = ? AND page_start = ?
            """, (concept_id, book_id, page)).fetchone()
            if existing:
                return {"success": True, "concept_id": concept_id, "entry_id": existing['id'],
                        "message": "Location already registered"}

            # Validate book exists
            book = conn.execute("SELECT id FROM books WHERE id = ?", (book_id,)).fetchone()
            if not book:
                return {"success": False, "error": f"Book {book_id} not found"}

            # Add entry
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO entries (concept_id, book_id, page_start, page_end, statement)
                VALUES (?, ?, ?, ?, ?)
            """, (concept_id, book_id, page, page, statement_preview))
            entry_id = cursor.lastrowid

            # Auto-set canonical if first entry
            count = conn.execute(
                "SELECT COUNT(*) as cnt FROM entries WHERE concept_id = ?", (concept_id,)
            ).fetchone()['cnt']
            if count == 1:
                conn.execute("UPDATE entries SET is_canonical = 1 WHERE id = ?", (entry_id,))
                conn.execute("UPDATE concepts SET canonical_entry_id = ? WHERE id = ?",
                            (entry_id, concept_id))

            self._sync_concept_fts(conn, concept_id)

        return {"success": True, "concept_id": concept_id, "entry_id": entry_id}

    def add_entry(self, concept_id: int, book_id: int = None,
                  page_start: int = None, page_end: int = None,
                  statement: str = None, is_canonical: int = None) -> Dict[str, Any]:
        """Adds a location entry to an existing concept."""
        with self.db.get_connection() as conn:
            if not conn.execute("SELECT 1 FROM concepts WHERE id = ?", (concept_id,)).fetchone():
                return {"success": False, "error": f"Concept {concept_id} not found"}
            if book_id and not conn.execute("SELECT 1 FROM books WHERE id = ?", (book_id,)).fetchone():
                return {"success": False, "error": f"Book {book_id} not found"}

            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO entries (concept_id, book_id, page_start, page_end, statement, is_canonical)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (concept_id, book_id, page_start, page_end or page_start, statement, 0))
            new_id = cursor.lastrowid

            # Canonical logic
            count = conn.execute(
                "SELECT COUNT(*) as cnt FROM entries WHERE concept_id = ?", (concept_id,)
            ).fetchone()['cnt']
            if count == 1 or is_canonical == 1:
                conn.execute("UPDATE entries SET is_canonical = 0 WHERE concept_id = ?", (concept_id,))
                conn.execute("UPDATE entries SET is_canonical = 1 WHERE id = ?", (new_id,))
                conn.execute("UPDATE concepts SET canonical_entry_id = ? WHERE id = ?",
                            (new_id, concept_id))

            self._sync_concept_fts(conn, concept_id)

        return {"success": True, "id": new_id}

    def delete_entry(self, entry_id: int) -> Dict[str, Any]:
        """Deletes a location entry."""
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT concept_id FROM entries WHERE id = ?", (entry_id,)).fetchone()
            if not row:
                return {"success": False, "error": "Entry not found"}
            concept_id = row['concept_id']
            conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
            self._sync_concept_fts(conn, concept_id)
        return {"success": True}

    # ──────────────────────────────────────────────
    # Search & Browse
    # ──────────────────────────────────────────────

    def search_concepts(self, query: str, kind: str = None, limit: int = 20) -> List[Dict]:
        """FTS search over concepts, returns concepts with location counts."""
        with self.db.get_connection() as conn:
            # Try FTS first
            try:
                fts_ids = conn.execute("""
                    SELECT rowid FROM concept_fts
                    WHERE concept_fts MATCH ?
                    ORDER BY rank LIMIT ?
                """, (query, limit * 2)).fetchall()
                concept_ids = [r['rowid'] for r in fts_ids]
            except Exception:
                concept_ids = []

            # Fallback to LIKE if FTS empty
            if not concept_ids:
                rows = conn.execute("""
                    SELECT id FROM concepts
                    WHERE name LIKE ? OR aliases LIKE ?
                    LIMIT ?
                """, (f"%{query}%", f"%{query}%", limit * 2)).fetchall()
                concept_ids = [r['id'] for r in rows]

            if not concept_ids:
                return []

            # Fetch concepts with entry counts
            placeholders = ','.join(['?'] * len(concept_ids))
            results = conn.execute(f"""
                SELECT c.id, c.name, c.kind, c.domain, c.aliases, c.created_at,
                       COUNT(e.id) as location_count
                FROM concepts c
                LEFT JOIN entries e ON e.concept_id = c.id
                WHERE c.id IN ({placeholders})
                {'AND c.kind = ?' if kind else ''}
                GROUP BY c.id
                ORDER BY location_count DESC
            """, concept_ids + ([kind] if kind else [])).fetchall()

            return [
                {**dict(r), 'aliases': json.loads(r['aliases'] or '[]')}
                for r in results
            ][:limit]

    def browse_concepts(self, letter: str = None, sort: str = 'alpha',
                        kind: str = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """Browse concepts by letter with sorting. Returns paginated results + total count."""
        with self.db.get_connection() as conn:
            where_clauses = []
            params = []

            if letter and len(letter) == 1 and letter.isalpha():
                where_clauses.append("UPPER(SUBSTR(c.name, 1, 1)) = ?")
                params.append(letter.upper())

            if kind and kind in VALID_KINDS:
                where_clauses.append("c.kind = ?")
                params.append(kind)

            where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

            # Sorting
            if sort == 'links':
                order_sql = "ORDER BY location_count DESC, c.name ASC"
            elif sort == 'newest':
                order_sql = "ORDER BY c.created_at DESC"
            else:  # alpha (default)
                order_sql = "ORDER BY c.name ASC"

            # Total count
            count_row = conn.execute(f"""
                SELECT COUNT(DISTINCT c.id) as total
                FROM concepts c
                {where_sql}
            """, params).fetchone()
            total = count_row['total']

            # Fetch page
            results = conn.execute(f"""
                SELECT c.id, c.name, c.kind, c.domain, c.aliases, c.created_at,
                       COUNT(e.id) as location_count
                FROM concepts c
                LEFT JOIN entries e ON e.concept_id = c.id
                {where_sql}
                GROUP BY c.id
                {order_sql}
                LIMIT ? OFFSET ?
            """, params + [limit, offset]).fetchall()

            # Letter counts for the alphabet bar
            letter_counts = conn.execute("""
                SELECT UPPER(SUBSTR(name, 1, 1)) as letter, COUNT(*) as cnt
                FROM concepts
                GROUP BY letter
                ORDER BY letter
            """).fetchall()

            return {
                "concepts": [
                    {**dict(r), 'aliases': json.loads(r['aliases'] or '[]')}
                    for r in results
                ],
                "total": total,
                "letter_counts": {r['letter']: r['cnt'] for r in letter_counts}
            }

    # ──────────────────────────────────────────────
    # Proposal Management (auto-discovery approval)
    # ──────────────────────────────────────────────

    def list_proposals(self, status: str = 'pending', limit: int = 50) -> List[Dict]:
        """Returns proposals with book info and merge target suggestions."""
        with self.db.get_connection() as conn:
            rows = conn.execute("""
                SELECT p.*, 
                       b.title as book_title, b.author as book_author,
                       c.name as merge_target_name
                FROM kb_proposals p
                LEFT JOIN books b ON p.book_id = b.id
                LEFT JOIN concepts c ON p.merge_target_id = c.id
                WHERE p.status = ?
                ORDER BY p.created_at DESC
                LIMIT ?
            """, (status, limit)).fetchall()
        return [dict(r) for r in rows]

    def get_proposal(self, proposal_id: int) -> Optional[Dict[str, Any]]:
        """Returns a single proposal with full details."""
        with self.db.get_connection() as conn:
            row = conn.execute("""
                SELECT p.*, 
                       b.title as book_title, b.author as book_author,
                       c.name as merge_target_name
                FROM kb_proposals p
                LEFT JOIN books b ON p.book_id = b.id
                LEFT JOIN concepts c ON p.merge_target_id = c.id
                WHERE p.id = ?
            """, (proposal_id,)).fetchone()
        return dict(row) if row else None

    def approve_proposal(self, proposal_id: int) -> Dict[str, Any]:
        """Approves a proposal: creates new concept + location entry."""
        proposal = self.get_proposal(proposal_id)
        if not proposal:
            return {"success": False, "error": "Proposal not found"}
        if proposal['status'] != 'pending':
            return {"success": False, "error": f"Proposal is already {proposal['status']}"}

        result = self.add_location(
            concept_name=proposal['concept_name'],
            kind=proposal['kind'],
            book_id=proposal['book_id'],
            page=proposal['page_number'],
            statement_preview=proposal.get('snippet')
        )

        if result.get('success'):
            with self.db.get_connection() as conn:
                conn.execute(
                    "UPDATE kb_proposals SET status = 'approved' WHERE id = ?",
                    (proposal_id,))

        return {**result, "proposal_id": proposal_id}

    def merge_proposal(self, proposal_id: int, target_concept_id: int) -> Dict[str, Any]:
        """Merges a proposal into an existing concept as a new location."""
        proposal = self.get_proposal(proposal_id)
        if not proposal:
            return {"success": False, "error": "Proposal not found"}
        if proposal['status'] != 'pending':
            return {"success": False, "error": f"Proposal is already {proposal['status']}"}

        result = self.add_entry(
            concept_id=target_concept_id,
            book_id=proposal['book_id'],
            page_start=proposal['page_number'],
            statement=proposal.get('snippet')
        )

        if result.get('success'):
            with self.db.get_connection() as conn:
                conn.execute(
                    "UPDATE kb_proposals SET status = 'merged', merge_target_id = ? WHERE id = ?",
                    (target_concept_id, proposal_id))

        return {**result, "proposal_id": proposal_id, "merged_into": target_concept_id}

    def reject_proposal(self, proposal_id: int) -> Dict[str, Any]:
        """Rejects a proposal."""
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                "UPDATE kb_proposals SET status = 'rejected' WHERE id = ? AND status = 'pending'",
                (proposal_id,))
            if cursor.rowcount == 0:
                return {"success": False, "error": "Proposal not found or already processed"}
        return {"success": True}

    def get_proposal_count(self) -> int:
        """Returns count of pending proposals."""
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM kb_proposals WHERE status = 'pending'"
            ).fetchone()
        return row['cnt'] if row else 0

    # ──────────────────────────────────────────────
    # Schema Info
    # ──────────────────────────────────────────────

    def get_kb_schema_info(self) -> Dict[str, Any]:
        """Returns metadata about valid concept types."""
        return {
            "concept_kinds": sorted(VALID_KINDS),
        }

    # ──────────────────────────────────────────────
    # FTS Sync
    # ──────────────────────────────────────────────

    def _sync_concept_fts(self, conn, concept_id: int):
        """Syncs concept + its entries into concept_fts."""
        concept = conn.execute(
            "SELECT name, aliases FROM concepts WHERE id = ?",
            (concept_id,)
        ).fetchone()
        if not concept:
            return

        entries = conn.execute(
            "SELECT statement, notes FROM entries WHERE concept_id = ?",
            (concept_id,)
        ).fetchall()
        all_statements = " ".join(e['statement'] or '' for e in entries)
        all_notes = " ".join(e['notes'] or '' for e in entries)

        conn.execute("DELETE FROM concept_fts WHERE rowid = ?", (concept_id,))
        conn.execute("""
            INSERT INTO concept_fts (rowid, name, aliases, statement, notes)
            VALUES (?, ?, ?, ?, ?)
        """, (concept_id, concept['name'], concept['aliases'] or '',
              all_statements, all_notes))


knowledge_service = KnowledgeService()
