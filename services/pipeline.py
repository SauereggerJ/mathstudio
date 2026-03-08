import logging
import json
import time
import re
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

from core.database import db
from core.config import CONVERTED_NOTES_DIR, LIBRARY_ROOT, PROJECT_ROOT
import converter as conv

logger = logging.getLogger(__name__)

class PipelineService:
    def __init__(self):
        pass

    def run_pass_0(self, book_id: int) -> bool:
        """Pass 0: Content Boundary Detection. Determines content_start and content_end."""
        logger.info(f"Pipeline [Pass 0]: Book {book_id}")

        with db.get_connection() as conn:
            book = conn.execute(
                "SELECT id, title, page_count, page_offset, toc_json FROM books WHERE id = ?",
                (book_id,)
            ).fetchone()

        if not book: return False

        page_count = book['page_count'] or 0
        page_offset = book['page_offset'] or 0
        toc_json = book['toc_json']

        # Determine start/end heuristics
        content_start = None
        content_end = None

        if toc_json:
            try:
                toc = json.loads(toc_json) if isinstance(toc_json, str) else toc_json
                if isinstance(toc, list) and len(toc) > 0:
                    for entry in toc:
                        page = None
                        if isinstance(entry, list) and len(entry) >= 3:
                            page = entry[2] if isinstance(entry[2], int) else None
                        elif isinstance(entry, dict):
                            page = entry.get('page', entry.get('page_number'))
                        if page and isinstance(page, int) and page > 0:
                            content_start = page
                            break
            except Exception: pass

        if content_start is None:
            content_start = max(1, int(page_count * 0.05)) + page_offset if page_count >= 50 else 1
        
        if content_end is None:
            content_end = max(content_start, int(page_count * 0.97)) if page_count >= 50 else page_count

        with db.get_connection() as conn:
            conn.execute(
                "UPDATE books SET content_start = ?, content_end = ? WHERE id = ?",
                (content_start, content_end, book_id)
            )
        return True

    def run_pass_1(self, book_id: int, retry_failed: bool = False, pages: List[int] = None, progress_callback=None) -> Dict[str, int]:
        """Pass 1: Visual Harvester. PDF -> LaTeX conversion."""
        logger.info(f"Pipeline [Pass 1]: Book {book_id}")

        with db.get_connection() as conn:
            book = conn.execute("SELECT path, content_start, content_end FROM books WHERE id = ?", (book_id,)).fetchone()
        if not book: return {"error": -1}

        page_start = book['content_start']
        page_end = book['content_end']
        book_path = str(LIBRARY_ROOT / book['path'])

        if pages:
            pages_to_process = pages
        else:
            all_pages = list(range(page_start, page_end + 1))
            if retry_failed:
                with db.get_connection() as conn:
                    failed = conn.execute("SELECT page_number FROM extracted_pages WHERE book_id = ? AND status != 'ok'", (book_id,)).fetchall()
                pages_to_process = [r['page_number'] for r in failed]
            else:
                with db.get_connection() as conn:
                    ok = conn.execute("SELECT page_number FROM extracted_pages WHERE book_id = ? AND status = 'ok'", (book_id,)).fetchall()
                ok_set = {r['page_number'] for r in ok}
                pages_to_process = [p for p in all_pages if p not in ok_set]

        stats = {"ok": 0, "failed": 0, "repaired": 0}
        batch_size = 10
        for i in range(0, len(pages_to_process), batch_size):
            batch = pages_to_process[i:i + batch_size]
            results, error = conv.convert_pages_batch(book_path, batch)
            
            if error:
                for p in batch: self._update_page_status(book_id, p, 'failed', error)
                stats["failed"] += len(batch)
                continue

            for res in results:
                p_num = res.get('page_number')
                latex = res.get('latex', '')
                if not latex:
                    self._update_page_status(book_id, p_num, 'empty')
                    stats["failed"] += 1
                    continue

                # Lint & Repair
                lint_errors = conv.lint_latex(latex)
                if lint_errors and lint_errors != ["Empty LaTeX code"]:
                    fixed = conv.repair_latex(latex, "", "; ".join(lint_errors))
                    if fixed:
                        latex = fixed
                        stats["repaired"] += 1

                # Save file
                page_dir = CONVERTED_NOTES_DIR / str(book_id)
                page_dir.mkdir(parents=True, exist_ok=True)
                tex_path = page_dir / f"page_{p_num}.tex"
                tex_path.write_text(latex, encoding='utf-8')
                rel_path = str(tex_path.relative_to(PROJECT_ROOT))

                with db.get_connection() as conn:
                    conn.execute("""
                        INSERT INTO extracted_pages (book_id, page_number, latex_path, status)
                        VALUES (?, ?, ?, 'ok')
                        ON CONFLICT(book_id, page_number) DO UPDATE SET latex_path=excluded.latex_path, status='ok'
                    """, (book_id, p_num, rel_path))
                stats["ok"] += 1
            
            if progress_callback:
                progress_callback(stats["ok"] + stats["failed"])

            time.sleep(1) # Rate limit
        return stats

    def run_pass_2(self, book_id: int, api: str = "gemini", pages: List[int] = None, progress_callback=None) -> Dict[str, Any]:
        """Pass 2: Term Extraction. LaTeX -> Terms with 3-page context."""
        logger.info(f"Pipeline [Pass 2]: Book {book_id} via {api}")

        with db.get_connection() as conn:
            book = conn.execute("SELECT title, author, content_start, content_end FROM books WHERE id = ?", (book_id,)).fetchone()
        if not book: return {"error": -1}

        page_start = book['content_start']
        page_end = book['content_end']

        if pages:
            processable = pages
        else:
            with db.get_connection() as conn:
                rows = conn.execute("SELECT page_number FROM extracted_pages WHERE book_id = ? AND status = 'ok'", (book_id,)).fetchall()
            cached_pages = {r['page_number'] for r in rows}
            total_range = list(range(page_start, page_end + 1))
            processable = [p for p in total_range if p in cached_pages]

        stats = {"found": 0, "saved": 0, "no_terms": 0, "error": 0}
        
        from core.ai import ai
        prompt_tmpl = """You are a mathematical knowledge extraction agent.
BOOK: "{title}" by {author}

Below are 3 consecutive pages of raw LaTeX. Identify terms (Definition, Theorem, Lemma, etc.) that BEGIN on PAGE {p}.
Pages {p1} and {p2} are overflow context.

CRITICAL RULES:
1. STRICT START PAGE REQUIREMENT: You MUST ONLY extract items whose text physically begins under the `=== PAGE {p} ===` header. DO NOT abstractly summarize items from the later pages. If an item begins under `=== PAGE {p1} ===` or `=== PAGE {p2} ===`, IGNORE IT entirely.
2. Theorems usually have Proofs. A Proof MUST be captured together with its Theorem as a SINGLE combined body.
   - If the Theorem begins on PAGE {p}, extract the Theorem AND its entire Proof, even if the Proof spills over onto PAGE {p1} or {p2}.
   - If the Theorem began on a PREVIOUS page (before PAGE {p}) and only its Proof spills over onto PAGE {p}, DO NOT extract the Proof here. It was already securely captured when the previous page was processed.
3. Therefore: NEVER extract an isolated "Proof" as its own term.
4. NAMING: If a term has an explicitly written name (e.g. "Cauchy-Schwarz Inequality"), use it. If the term is unnamed (e.g. just "Lemma 1.7", "Theorem 2.13", or "Example"), YOU MUST formulate a concise, descriptive name based on its mathematical content (e.g., "Lemma 1.7: Continuity of Stronger Norms" or "Example: Incomplete L^2 Sequence"). Do not output generic names like "Lemma 2.14" without adding descriptive context.

Format:
### [Name] ([Type])
Keywords: kw1, kw2
[LaTeX Body]

---

Return exactly the string NO_TERMS_FOUND if no valid terms begin on PAGE {p}."""

        for i, p in enumerate(processable):
            text_n = self._load_page_text(book_id, p)
            text_n1 = self._load_page_text(book_id, p + 1)
            text_n2 = self._load_page_text(book_id, p + 2)

            if not text_n: continue
            
            prompt = prompt_tmpl.format(
                title=book['title'], author=book['author'], 
                p=p, p1=p+1, p2=p+2
            ) + f"\n\n=== PAGE {p} ===\n{text_n}\n\n=== PAGE {p+1} ===\n{text_n1}\n\n=== PAGE {p+2} ===\n{text_n2}"
            
            try:
                response = ai.generate_text(prompt)
                if response:
                    terms = self._parse_extraction_output(response, p)
                    if not terms:
                        stats["no_terms"] += 1
                    else:
                        stats["found"] += len(terms)
                        for t in terms:
                            if self._save_term(book_id, t):
                                stats["saved"] += 1
                time.sleep(0.2)
                if progress_callback:
                    progress_callback(i + 1, stats["saved"])
            except Exception as e:
                logger.error(f"Pass 2 Error on p{p}: {e}")
                stats["error"] += 1

        return stats

    def _update_page_status(self, book_id, page, status, comment=None):
        with db.get_connection() as conn:
            conn.execute("INSERT INTO extracted_pages (book_id, page_number, status, quality_comments) VALUES (?, ?, ?, ?) ON CONFLICT(book_id, page_number) DO UPDATE SET status=excluded.status, quality_comments=excluded.quality_comments", (book_id, page, status, comment))

    def _load_page_text(self, book_id, page):
        p = CONVERTED_NOTES_DIR / str(book_id) / f"page_{page}.tex"
        return p.read_text(encoding='utf-8') if p.exists() else ""

    def _parse_extraction_output(self, raw, page) -> list:
        # Strip markdown markers if present
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            if lines[0].startswith("```"): lines = lines[1:]
            if lines and lines[-1].startswith("```"): lines = lines[:-1]
            raw = "\n".join(lines).strip()

        if "NO_TERMS_FOUND" in raw: return []
        
        terms = []
        # Support AI dropping the '---' separator by splitting directly at headers
        blocks = [b.strip() for b in re.split(r'(?m)(?=^###\s+)', raw) if b.strip()]
        
        for block in blocks:
            # Use search instead of match to be more flexible with leading whitespace/newlines
            header = re.search(r'^###\s+(.+?)\s*\(([^)]+)\)\s*$', block, re.MULTILINE)
            if header:
                name, t_type = header.groups()
                kw_match = re.search(r'^Keywords:\s*(.+)$', block, re.MULTILINE)
                keywords = [k.strip() for k in kw_match.group(1).split(',')] if kw_match else []
                # Body is everything after keywords or after header
                body_start = kw_match.end() if kw_match else header.end()
                body = block[body_start:].strip()
                
                terms.append({
                    'name': name.strip(),
                    'type': t_type.lower().strip(),
                    'used_terms': keywords,
                    'latex_content': body,
                    'page_start': page
                })
        return terms

    def _save_term(self, book_id, term) -> bool:
        tid = None
        with db.get_connection() as conn:
            existing = conn.execute("SELECT id FROM knowledge_terms WHERE book_id=? AND LOWER(name)=?", (book_id, term['name'].lower())).fetchone()
            if existing: return False
            cursor = conn.cursor()
            cursor.execute("INSERT INTO knowledge_terms (book_id, page_start, name, term_type, latex_content, used_terms, status) VALUES (?,?,?,?,?,?, 'approved')", (book_id, term['page_start'], term['name'], term['type'], term['latex_content'], json.dumps(term['used_terms'])))
            tid = cursor.lastrowid
            conn.execute("INSERT INTO knowledge_terms_fts (rowid, name, used_terms, latex_content) VALUES (?,?,?,?)", (tid, term['name'], ", ".join(term['used_terms']), term['latex_content']))
            
        if tid:
            try:
                from services.knowledge import knowledge_service
                knowledge_service.sync_term_to_federated(tid)
            except Exception as e:
                logger.error(f"Failed to sync term {tid} to federated search: {e}")
        return True

# Global instance
pipeline_service = PipelineService()
