import json
import logging
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from jinja2 import Environment, FileSystemLoader

from core.database import db
from core.config import (
    KNOWLEDGE_VAULT_ROOT, KNOWLEDGE_GENERATED_DIR,
    KNOWLEDGE_DRAFTS_DIR, KNOWLEDGE_TEMPLATES_DIR,
    LIBRARY_ROOT
)

logger = logging.getLogger(__name__)

class KnowledgeService:
    def __init__(self):
        self.db = db
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(KNOWLEDGE_TEMPLATES_DIR)),
            trim_blocks=True, lstrip_blocks=True
        )
        # Register custom filters
        self.jinja_env.filters['wikilink'] = self.wikilink_text
        self.jinja_env.filters['filename_safe'] = lambda x: x.replace(' ', '_').replace('/', '_')

    def wikilink_text(self, text: str) -> str:
        """Auto-links known concepts within a block of text, protecting LaTeX."""
        if not text: return ""
        
        # 1. Protect LaTeX blocks by temporary substitution
        import re
        latex_blocks = []
        def placeholder(m):
            latex_blocks.append(m.group(0))
            return f"__LATEX_BLOCK_{len(latex_blocks)-1}__"
        
        # Replace $$...$$ and $...$
        text = re.sub(r"\$\$.*?\$\$", placeholder, text, flags=re.DOTALL)
        text = re.sub(r"\$.*?\$", placeholder, text)

        # 2. Perform wikilinking on remaining text
        with self.db.get_connection() as conn:
            all_concepts = conn.execute("SELECT name FROM concepts").fetchall()
            concept_names = sorted([c['name'] for c in all_concepts], key=len, reverse=True)
            
        for name in concept_names:
            # Avoid linking if already linked
            pattern = rf"(?<!\[\[)\b({re.escape(name)})\b(?!\]\])"
            text = re.sub(pattern, r"[[\1]]", text)

        # 3. Restore LaTeX blocks
        for i, block in enumerate(latex_blocks):
            text = text.replace(f"__LATEX_BLOCK_{i}__", block)
            
        return text

    # --- CRUD: Concepts ---

    def add_concept(self, name: str, kind: str, domain: str = None,
                    aliases: list = None) -> Dict[str, Any]:
        """Creates a new concept. Returns the new concept dict."""
        # Valid kinds for enforcement
        VALID_KINDS = {'definition', 'theorem', 'lemma', 'proposition',
                       'corollary', 'example', 'axiom', 'notation'}
        if kind not in VALID_KINDS:
            return {"success": False, "error": f"Invalid kind. Must be one of: {VALID_KINDS}"}

        # Dedup check: exact name match
        with self.db.get_connection() as conn:
            existing = conn.execute(
                "SELECT id, name FROM concepts WHERE name = ?", (name,)
            ).fetchone()
            if existing:
                return {"success": False, "error": f"Concept '{name}' already exists (ID {existing['id']})"}

            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO concepts (name, kind, domain, aliases)
                VALUES (?, ?, ?, ?)
            """, (name, kind, domain, json.dumps(aliases or [])))
            new_id = cursor.lastrowid

        return {"success": True, "id": new_id}

    def update_concept(self, concept_id: int, **kwargs) -> Dict[str, Any]:
        """Updates concept fields (name, kind, domain, aliases, synthesis)."""
        allowed = {'name', 'kind', 'domain', 'aliases', 'synthesis'}
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
            
            # Sync FTS if name/aliases changed
            if 'name' in updates or 'aliases' in updates:
                self._sync_concept_fts(conn, concept_id)
                
        return {"success": True}

    def delete_concept(self, concept_id: int) -> Dict[str, Any]:
        """Deletes a concept and all its entries/relations (via CASCADE)."""
        with self.db.get_connection() as conn:
            cursor = conn.execute("DELETE FROM concepts WHERE id = ?", (concept_id,))
            if cursor.rowcount == 0:
                return {"success": False, "error": "Concept not found"}
            # Clean up FTS
            conn.execute("DELETE FROM concept_fts WHERE rowid = ?", (concept_id,))
        return {"success": True}

    def get_concept(self, concept_id: int) -> Optional[Dict[str, Any]]:
        """Returns concept with all entries and relations."""
        with self.db.get_connection() as conn:
            concept = conn.execute(
                "SELECT * FROM concepts WHERE id = ?", (concept_id,)
            ).fetchone()
            if not concept:
                return None

            entries = conn.execute("""
                SELECT e.*, b.title as book_title, b.author as book_author, b.path as book_path
                FROM entries e
                LEFT JOIN books b ON e.book_id = b.id
                WHERE e.concept_id = ?
                ORDER BY e.is_canonical DESC, e.created_at ASC
            """, (concept_id,)).fetchall()

            relations_out = conn.execute("""
                SELECT r.*, c.name as target_name
                FROM relations r
                JOIN concepts c ON r.to_concept_id = c.id
                WHERE r.from_concept_id = ?
            """, (concept_id,)).fetchall()

            relations_in = conn.execute("""
                SELECT r.*, c.name as source_name
                FROM relations r
                JOIN concepts c ON r.from_concept_id = c.id
                WHERE r.to_concept_id = ?
            """, (concept_id,)).fetchall()

        result = dict(concept)
        result['aliases'] = json.loads(result['aliases'] or '[]')
        result['entries'] = [dict(e) for e in entries]
        result['relations_out'] = [dict(r) for r in relations_out]
        result['relations_in'] = [dict(r) for r in relations_in]
        # Strip embedding blobs from entries for JSON serialization
        for e in result['entries']:
            if e.get('embedding'):
                e['has_embedding'] = True
                del e['embedding']
            else:
                e['has_embedding'] = False
        return result

    # --- CRUD: Entries ---

    def add_entry(self, concept_id: int, statement: str,
                  book_id: int = None, page_start: int = None,
                  page_end: int = None, proof: str = None,
                  notes: str = None, scope: str = None,
                  language: str = 'en', style: str = None,
                  confidence: float = 1.0, is_canonical: int = None) -> Dict[str, Any]:
        """Adds a formulation to a concept."""
        with self.db.get_connection() as conn:
            # Validate concept exists
            if not conn.execute("SELECT 1 FROM concepts WHERE id = ?", (concept_id,)).fetchone():
                return {"success": False, "error": f"Concept {concept_id} not found"}
            # Validate book exists if provided
            if book_id and not conn.execute("SELECT 1 FROM books WHERE id = ?", (book_id,)).fetchone():
                return {"success": False, "error": f"Book {book_id} not found"}

            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO entries (concept_id, book_id, page_start, page_end,
                    statement, proof, notes, scope, language, style, confidence, is_canonical)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (concept_id, book_id, page_start, page_end,
                  statement, proof, notes, scope, language, style, confidence, 0))
            new_id = cursor.lastrowid

            # Canonical Logic
            count = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE concept_id = ?", (concept_id,)
            ).fetchone()[0]
            
            # Auto-set as canonical if it's the first entry OR if explicitly requested
            if count == 1 or is_canonical == 1:
                conn.execute("UPDATE entries SET is_canonical = 0 WHERE concept_id = ?", (concept_id,))
                conn.execute("UPDATE entries SET is_canonical = 1 WHERE id = ?", (new_id,))
                conn.execute("UPDATE concepts SET canonical_entry_id = ? WHERE id = ?",
                             (new_id, concept_id))

            # Sync FTS
            self._sync_concept_fts(conn, concept_id)

        return {"success": True, "id": new_id}

    def update_entry(self, entry_id: int, **kwargs) -> Dict[str, Any]:
        """Updates formulation entry fields."""
        allowed = {'statement', 'proof', 'notes', 'scope', 'style',
                   'page_start', 'page_end', 'is_canonical', 'confidence'}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return {"success": False, "error": "No valid fields to update"}
            
        with self.db.get_connection() as conn:
            # If canonical is being set to 1, unset others for this concept
            if updates.get('is_canonical') == 1:
                concept_id = conn.execute(
                    "SELECT concept_id FROM entries WHERE id = ?", (entry_id,)
                ).fetchone()['concept_id']
                conn.execute("UPDATE entries SET is_canonical = 0 WHERE concept_id = ?", (concept_id,))
                conn.execute("UPDATE concepts SET canonical_entry_id = ? WHERE id = ?", (entry_id, concept_id))

            query = "UPDATE entries SET " + ", ".join(f"{k} = ?" for k in updates.keys())
            query += " WHERE id = ?"
            cursor = conn.execute(query, list(updates.values()) + [entry_id])
            
            if cursor.rowcount == 0:
                return {"success": False, "error": "Entry not found"}
            
            # Re-sync FTS if statement/notes changed
            if 'statement' in updates or 'notes' in updates:
                concept_id = conn.execute(
                    "SELECT concept_id FROM entries WHERE id = ?", (entry_id,)
                ).fetchone()['concept_id']
                self._sync_concept_fts(conn, concept_id)
                
        return {"success": True}

    def delete_entry(self, entry_id: int) -> Dict[str, Any]:
        """Deletes a formulation entry."""
        with self.db.get_connection() as conn:
            concept_id = conn.execute(
                "SELECT concept_id FROM entries WHERE id = ?", (entry_id,)
            ).fetchone()['concept_id']
            cursor = conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
            if cursor.rowcount == 0:
                return {"success": False, "error": "Entry not found"}
            self._sync_concept_fts(conn, concept_id)
        return {"success": True}

    # --- CRUD: Relations ---

    def add_relation(self, from_id: int, to_id: int, relation_type: str,
                     context: str = None, source_entry_id: int = None,
                     confidence: float = 1.0) -> Dict[str, Any]:
        """Adds a directed edge between two concepts."""
        VALID_TYPES = {'uses', 'implies', 'equivalent_to', 'generalizes',
                       'special_case_of', 'proved_by', 'counterexample_to',
                       'see_also', 'prerequisite'}
        if relation_type not in VALID_TYPES:
            return {"success": False, "error": f"Invalid relation type. Must be one of: {VALID_TYPES}"}
        if from_id == to_id:
            return {"success": False, "error": "Self-referencing relations are not allowed"}

        with self.db.get_connection() as conn:
            try:
                conn.execute("""
                    INSERT INTO relations (from_concept_id, to_concept_id,
                        relation_type, context, source_entry_id, confidence)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (from_id, to_id, relation_type, context,
                      source_entry_id, confidence))
            except Exception as e:
                if "UNIQUE" in str(e) or "PRIMARY KEY" in str(e):
                    return {"success": False, "error": "Relation already exists"}
                raise

        return {"success": True}

    def delete_relation(self, from_id: int, to_id: int, relation_type: str) -> Dict[str, Any]:
        """Deletes a relation."""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                DELETE FROM relations WHERE from_concept_id = ? AND to_concept_id = ? AND relation_type = ?
            """, (from_id, to_id, relation_type))
            if cursor.rowcount == 0:
                return {"success": False, "error": "Relation not found"}
        return {"success": True}

    # --- Book Metadata & Offsets ---

    def set_book_offset(self, book_id: int, offset: int) -> Dict[str, Any]:
        """Stores a persistent page offset for a book."""
        with self.db.get_connection() as conn:
            cursor = conn.execute("UPDATE books SET page_offset = ? WHERE id = ?", (offset, book_id))
            if cursor.rowcount == 0:
                return {"success": False, "error": "Book not found"}
        return {"success": True}

    def get_kb_schema_info(self) -> Dict[str, Any]:
        """Returns metadata about valid concept types and relations."""
        return {
            "concept_kinds": ['definition', 'theorem', 'lemma', 'proposition',
                              'corollary', 'example', 'axiom', 'notation'],
            "relation_types": ['uses', 'implies', 'equivalent_to', 'generalizes',
                               'special_case_of', 'proved_by', 'counterexample_to',
                               'see_also', 'prerequisite'],
            "scopes": ['undergraduate', 'graduate', 'research']
        }

    def ingest_from_page(self, concept_id: int, book_id: int, page: int,
                         kind: str = 'statement_and_proof',
                         scope: str = None, style: str = None) -> Dict[str, Any]:
        """
        High-fidelity extraction: uses note_service to convert a page to LaTeX,
        then stores it as a KB entry.
        """
        from services.note import note_service
        
        # 1. Convert page to note (uses cache if available)
        result, error = note_service.create_note_from_pdf(book_id, [page])
        if error:
            return {"success": False, "error": f"Extraction failed: {error}"}
        
        content = result['content']
        
        # 2. Heuristic split into statement and proof (if applicable)
        # Note: This is a simple split, the LLM can refine this later via update_entry.
        statement = content
        proof = None
        
        lower_content = content.lower()
        proof_markers = ['proof', 'beweis', 'demonstration']
        for marker in proof_markers:
            idx = lower_content.find(f"## {marker}")
            if idx == -1: idx = lower_content.find(f"**{marker}")
            if idx != -1:
                statement = content[:idx].strip()
                proof = content[idx:].strip()
                break
        
        # 3. Add as entry
        return self.add_entry(
            concept_id=concept_id,
            statement=statement,
            book_id=book_id,
            page_start=page,
            page_end=page,
            proof=proof,
            scope=scope,
            style=style,
            confidence=0.9 # High confidence due to direct extraction
        )

    # --- Search ---

    def search_concepts(self, query: str, kind: str = None,
                        domain: str = None, limit: int = 20) -> List[Dict]:
        """FTS search over concepts + entries."""
        with self.db.get_connection() as conn:
            # FTS query
            fts_results = conn.execute("""
                SELECT rowid, rank FROM concept_fts
                WHERE concept_fts MATCH ?
                ORDER BY rank LIMIT ?
            """, (query, limit)).fetchall()

            if not fts_results:
                # Fallback to simple LIKE search if FTS yielded nothing
                results = []
                concepts = conn.execute("""
                    SELECT id, name, kind, domain, aliases FROM concepts
                    WHERE name LIKE ? OR aliases LIKE ?
                    LIMIT ?
                """, (f"%{query}%", f"%{query}%", limit)).fetchall()

                for c in concepts:
                    d = dict(c)
                    d['aliases'] = json.loads(d['aliases'] or '[]')
                    d['match_source'] = 'concept'
                    results.append(d)
                return results

            # We need to figure out which table each rowid came from.
            # Since concept_fts combines concepts and entries, we use a
            # simpler approach: search concepts by name + entries by statement.
            results = []
            concepts = conn.execute("""
                SELECT id, name, kind, domain, aliases FROM concepts
                WHERE name LIKE ? OR aliases LIKE ?
                LIMIT ?
            """, (f"%{query}%", f"%{query}%", limit)).fetchall()

            for c in concepts:
                d = dict(c)
                d['aliases'] = json.loads(d['aliases'] or '[]')
                d['match_source'] = 'concept'
                results.append(d)

            entries = conn.execute("""
                SELECT e.id as entry_id, e.concept_id, e.statement, e.scope,
                       c.name as concept_name, c.kind
                FROM entries e
                JOIN concepts c ON e.concept_id = c.id
                WHERE e.statement LIKE ? OR e.notes LIKE ?
                LIMIT ?
            """, (f"%{query}%", f"%{query}%", limit)).fetchall()

            for e in entries:
                results.append({**dict(e), 'match_source': 'entry'})

        return results[:limit]

    # --- Graph Traversal ---

    def get_related_concepts(self, concept_id: int, depth: int = 1,
                             max_depth: int = 3) -> Dict[str, Any]:
        """BFS graph traversal with HARD depth cap."""
        # SAFETY: Hard cap at 3, regardless of input
        effective_depth = min(depth, max_depth, 3)

        visited = set()
        result = {"root": concept_id, "depth": effective_depth, "nodes": [], "edges": []}

        queue = [(concept_id, 0)]
        while queue:
            current_id, current_depth = queue.pop(0)
            if current_id in visited or current_depth > effective_depth:
                continue
            visited.add(current_id)

            with self.db.get_connection() as conn:
                concept = conn.execute(
                    "SELECT id, name, kind, domain FROM concepts WHERE id = ?",
                    (current_id,)
                ).fetchone()
                if concept:
                    result["nodes"].append(dict(concept))

                rels = conn.execute("""
                    SELECT r.*, c.name as target_name
                    FROM relations r
                    JOIN concepts c ON r.to_concept_id = c.id
                    WHERE r.from_concept_id = ?
                """, (current_id,)).fetchall()

                for r in rels:
                    edge = dict(r)
                    result["edges"].append(edge)
                    if current_depth < effective_depth:
                        queue.append((r['to_concept_id'], current_depth + 1))

        return result

    # --- Task Queue ---

    def queue_task(self, task_type: str, payload: dict = None,
                   priority: int = 5) -> Dict[str, Any]:
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO llm_tasks (task_type, payload, priority)
                VALUES (?, ?, ?)
            """, (task_type, json.dumps(payload or {}), priority))
        return {"success": True, "id": cursor.lastrowid}

    def get_pending_tasks(self, limit: int = 10) -> List[Dict]:
        """Returns pending tasks. Never returns blocked tasks."""
        with self.db.get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM llm_tasks
                WHERE status = 'pending'
                ORDER BY priority ASC, created_at ASC
                LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def fail_task(self, task_id: int, error: str) -> Dict[str, Any]:
        """Increments retry. Blocks if exceeded."""
        with self.db.get_connection() as conn:
            task = conn.execute(
                "SELECT retry_count, max_retries, error_log FROM llm_tasks WHERE id = ?",
                (task_id,)
            ).fetchone()
            if not task:
                return {"success": False, "error": "Task not found"}

            errors = json.loads(task['error_log'] or '[]')
            errors.append({"error": error, "at": int(time.time())})
            new_count = task['retry_count'] + 1
            new_status = 'blocked' if new_count >= task['max_retries'] else 'pending'

            conn.execute("""
                UPDATE llm_tasks SET retry_count = ?, error_log = ?, status = ?
                WHERE id = ?
            """, (new_count, json.dumps(errors), new_status, task_id))

        return {"success": True, "new_status": new_status, "retry_count": new_count}

    def complete_task(self, task_id: int, result: dict = None) -> Dict[str, Any]:
        with self.db.get_connection() as conn:
            conn.execute("""
                UPDATE llm_tasks SET status = 'done', result = ?,
                    completed_at = unixepoch() WHERE id = ?
            """, (json.dumps(result or {}), task_id))
        return {"success": True}

    # --- Vault Rendering ---

    def write_obsidian_note(self, concept_id: int) -> Dict[str, Any]:
        """Renders a concept to a Markdown file in the vault."""
        concept = self.get_concept(concept_id)
        if not concept:
            return {"success": False, "error": "Concept not found"}

        # Pick template by kind
        kind = concept['kind']
        if kind in ('definition', 'axiom', 'notation'):
            template_name = 'definition.md.j2'
        elif kind in ('theorem', 'lemma', 'proposition', 'corollary'):
            template_name = 'theorem.md.j2'
        else:
            template_name = 'definition.md.j2'  # Fallback

        template = self.jinja_env.get_template(template_name)

        # Find canonical entry
        canonical = None
        for e in concept['entries']:
            if e.get('is_canonical'):
                canonical = e
                break
        if not canonical and concept['entries']:
            canonical = concept['entries'][0]

        # Get book path for linking
        with self.db.get_connection() as conn:
            book = conn.execute("SELECT path FROM books WHERE id = ?", (canonical.get('book_id'),)).fetchone()
            book_path = book['path'] if book else None

        # Remove canonical entry from variants list so it isn't repeated
        variant_entries = [e for e in concept['entries'] if e['id'] != canonical['id']] if canonical else concept['entries']

        from datetime import datetime
        rendered = template.render(
            concept=concept,
            canonical=canonical,
            entries=variant_entries,
            relations=concept['relations_out'],
            relations_in=concept['relations_in'],
            library_root=str(LIBRARY_ROOT),
            now=datetime.now().strftime('%Y-%m-%d')
        )

        # Determine target folder by kind
        subfolder = "Definitions"
        if kind in ('theorem', 'lemma', 'proposition', 'corollary'):
            subfolder = "Theorems"
        elif kind == 'example':
            subfolder = "Examples"
        elif kind == 'notation':
            subfolder = "Notations"

        # Safe filename
        safe_name = concept['name'].replace(' ', '_').replace('/', '_')
        filename = f"{safe_name}.md"

        # Write to Generated/ (overwrite is intentional)
        target_dir = KNOWLEDGE_GENERATED_DIR / subfolder
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / filename
        target_path.write_text(rendered, encoding='utf-8')

        # Update obsidian_path in DB
        rel_path = f"Generated/{subfolder}/{filename}"
        with self.db.get_connection() as conn:
            conn.execute(
                "UPDATE concepts SET obsidian_path = ?, updated_at = unixepoch() WHERE id = ?",
                (rel_path, concept_id)
            )

        return {"success": True, "path": rel_path}

    def regenerate_vault(self) -> Dict[str, Any]:
        """Re-renders ALL concepts to the vault and updates the index."""
        with self.db.get_connection() as conn:
            concept_ids = [r['id'] for r in conn.execute("SELECT id FROM concepts").fetchall()]
            concepts_all = conn.execute("""
                SELECT c.*, (SELECT COUNT(*) FROM entries WHERE concept_id = c.id) as entry_count
                FROM concepts c
                ORDER BY c.domain, c.name
            """).fetchall()

        concepts_processed = []
        for c in concepts_all:
            d = dict(c)
            if d.get('domain') is None:
                d['domain'] = "General"
            concepts_processed.append(d)

        count = 0
        errors = 0
        for cid in concept_ids:
            res = self.write_obsidian_note(cid)
            if res.get('success'):
                count += 1
            else:
                errors += 1
        
        # Render Index
        template = self.jinja_env.get_template('index.md.j2')
        from datetime import datetime
        rendered_index = template.render(
            concepts=concepts_processed,
            now=datetime.now().strftime('%Y-%m-%d')
        )
        index_path = KNOWLEDGE_GENERATED_DIR / "_Index.md"
        index_path.write_text(rendered_index, encoding='utf-8')

        return {"success": True, "rendered": count, "errors": errors, "index": "_Index.md"}

    # --- FTS Sync Helper ---

    def _sync_concept_fts(self, conn, concept_id: int):
        """Syncs concept + its entries into concept_fts."""
        concept = conn.execute(
            "SELECT name, aliases FROM concepts WHERE id = ?",
            (concept_id,)
        ).fetchone()
        if not concept:
            return

        # Aggregate all entry statements and notes
        entries = conn.execute(
            "SELECT statement, notes FROM entries WHERE concept_id = ?",
            (concept_id,)
        ).fetchall()
        all_statements = " ".join(e['statement'] or '' for e in entries)
        all_notes = " ".join(e['notes'] or '' for e in entries)

        # Upsert into FTS (delete + re-insert)
        conn.execute("DELETE FROM concept_fts WHERE rowid = ?", (concept_id,))
        conn.execute("""
            INSERT INTO concept_fts (rowid, name, aliases, statement, notes)
            VALUES (?, ?, ?, ?, ?)
        """, (concept_id, concept['name'], concept['aliases'] or '',
              all_statements, all_notes))


knowledge_service = KnowledgeService()
