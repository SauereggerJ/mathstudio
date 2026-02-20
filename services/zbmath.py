import requests
import time
import json
import logging
import xml.etree.ElementTree as ET
import re
from typing import Optional, List, Dict, Any
from core.database import db

logger = logging.getLogger(__name__)

class ZBMathService:
    OAI_URL = "https://oai.zbmath.org/v1/"
    CROSSREF_URL = "https://api.crossref.org/works"
    OPENALEX_URL = "https://api.openalex.org/works"
    CONTACT_EMAIL = "admin@mathstudio.local" 

    def __init__(self):
        self.db = db
        self.last_request_time = 0
        self.min_delay = 1.0
        self.api_ready = False
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": f"MathStudio/1.0 (mailto:{self.CONTACT_EMAIL})",
        })

    def _ensure_api_access(self):
        """Official API requires T&C agreement POST."""
        if self.api_ready: return
        try:
            # POST to agree to Terms and Conditions
            self.session.post('https://api.zbmath.org/v1/', data={'tnc_agreed': '1', 'submit': 'Submit'}, timeout=10)
            self.api_ready = True
        except Exception as e:
            logger.error(f"Failed to initialize zbMATH API access: {e}")

    def _wait_for_rate_limit(self):
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_delay:
            time.sleep(self.min_delay - elapsed)
        self.last_request_time = time.time()

    def verify_metadata(self, extracted_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Phase 4: Deterministic Verification.
        Checks LLM data against Crossref/OpenAlex.
        Handles book-chapter -> master book resolution.
        """
        query_title = extracted_data.get('title')
        query_doi = extracted_data.get('doi')
        query_isbn = extracted_data.get('isbn')
        
        results = {"verified": False, "source": None, "master_data": {}, "conflicts": []}

        # 1. Primary path: ISBN (The Golden Key)
        if query_isbn:
            isbn_res = self.resolve_isbn(query_isbn)
            if isbn_res:
                results.update({"verified": True, "source": "ISBN", "master_data": isbn_res})
                return results

        # 2. Secondary path: DOI check
        target_doi = query_doi
        if target_doi:
            try:
                r = self.session.get(f"{self.CROSSREF_URL}/{target_doi}", timeout=10)
                if r.status_code == 200:
                    data = r.json().get('message', {})
                    # TYPE FILTERING
                    if data.get('type') == 'book-chapter':
                        # RESOLVE TO PARENT
                        # Springer logic: prefix before underscore
                        if '10.1007' in target_doi and '_' in target_doi:
                            parent_doi = target_doi.split('_')[0]
                            parent_r = self.session.get(f"{self.CROSSREF_URL}/{parent_doi}", timeout=5)
                            if parent_r.status_code == 200:
                                data = parent_r.json().get('message', {})
                                results['conflicts'].append(f"DOI upgrade: chapter {target_doi} -> book {parent_doi}")
                    
                    results.update({
                        "verified": True, 
                        "source": "DOI", 
                        "master_data": {
                            "doi": data.get('DOI'),
                            "title": data.get('title', [None])[0],
                            "author": ", ".join([f"{a.get('family')}, {a.get('given')}" for a in data.get('author', [])]),
                            "publisher": data.get('publisher'),
                            "year": data.get('published-print', data.get('issued', {})).get('date-parts', [[None]])[0][0]
                        }
                    })
                    return results
            except: pass

        # 3. Tertiary path: Bibliographic search (Title/Author)
        if query_title:
            search_res = self.resolve_citation(f"{query_title} {extracted_data.get('author', '')}")
            if search_res and search_res.get('score', 0) > 80: # High confidence only
                results.update({"verified": True, "source": "Crossref-Search", "master_data": search_res})
        
        return results

    def resolve_citation(self, raw_string: str) -> Optional[Dict[str, Any]]:
        """Stage 1: Resolve raw string to DOI via Crossref."""
        clean_query = re.sub(r'^\[\d+\]\s*', '', raw_string)
        clean_query = re.sub(r'p\.\s*\d+.*$', '', clean_query).strip()
        self._wait_for_rate_limit()
        try:
            resp = self.session.get(self.CROSSREF_URL, params={"query.bibliographic": clean_query, "rows": 1}, timeout=15)
            if resp.status_code == 200:
                items = resp.json().get('message', {}).get('items', [])
                if items:
                    item = items[0]
                    return {'doi': item.get('DOI'), 'title': item.get('title', [None])[0], 'score': item.get('score', 0)}
        except Exception as e: logger.error(f"Crossref failed: {e}")
        return None

    def resolve_isbn(self, isbn: str) -> Optional[Dict[str, Any]]:
        """Fetch official metadata using ISBN."""
        # Clean ISBN (remove hyphens, spaces)
        clean_isbn = re.sub(r'[^0-9X]', '', isbn)
        if not clean_isbn: return None

        self._wait_for_rate_limit()
        # We query Crossref by ISBN
        params = {"filter": f"isbn:{clean_isbn}", "rows": 1}
        try:
            resp = self.session.get(self.CROSSREF_URL, params=params, timeout=15)
            if resp.status_code == 200:
                items = resp.json().get('message', {}).get('items', [])
                if items:
                    item = items[0]
                    return {
                        'doi': item.get('DOI'),
                        'title': item.get('title', [None])[0],
                        'author': ", ".join([f"{a.get('family')}, {a.get('given')}" for a in item.get('author', [])]),
                        'publisher': item.get('publisher'),
                        'year': item.get('published-print', item.get('issued', {})).get('date-parts', [[None]])[0][0],
                        'score': 1.0 # ISBN matches are perfect
                    }
        except Exception as e:
            logger.error(f"ISBN resolution failed for {isbn}: {e}")
        return None

    def get_zbl_id_from_doi(self, doi: str) -> Optional[str]:
        """Dual-Bridge: Translate DOI to zbMATH ID using official REST API."""
        if not doi or doi.lower() in ("unknown", "n/a", "none"):
            return None

        # Clean DOI: strip prefixes
        clean_doi = doi.strip()
        if 'doi.org/' in clean_doi:
            clean_doi = clean_doi.split('doi.org/')[-1]
        
        self._ensure_api_access()
        self._wait_for_rate_limit()
        try:
            url = f'https://api.zbmath.org/v1/document/_search?search_string=doi:{clean_doi}'
            resp = self.session.get(url, timeout=10)
            if resp.ok:
                data = resp.json()
                results = data.get('result', [])
                if results:
                    return results[0].get('identifier')
        except Exception as e:
            logger.error(f"zbMATH API DOI resolution failed for {clean_doi}: {e}")

        # Bridge B: OpenAlex (Fallback)
        self._wait_for_rate_limit()
        try:
            resp = self.session.get(f"{self.OPENALEX_URL}/https://doi.org/{clean_doi}", timeout=10)
            if resp.status_code == 200:
                zbl = resp.json().get('ids', {}).get('zbm')
                if zbl: return zbl
        except: pass

        return None

    def find_zbl_id_by_metadata(self, title: str, author: str = None) -> Optional[str]:
        """Search zbMATH by title and author to find a Zbl ID."""
        if not title or title.lower() in ("unknown", "untitled", ""):
            return None
            
        self._ensure_api_access()
        self._wait_for_rate_limit()
        
        # Clean title for API (remove special chars that might break the parser)
        clean_title = re.sub(r"[:/?#\[\]@!$&'()*+,;=]", " ", title).strip()
        search_string = f'ti:{clean_title}'
        if author and author.lower() != 'unknown':
            # Take first author name
            first_author = author.split(',')[0].split('&')[0].strip()
            if first_author:
                search_string += f' AND au:{first_author}'

        try:
            url = f'https://api.zbmath.org/v1/document/_search?search_string={requests.utils.quote(search_string)}'
            resp = self.session.get(url, timeout=10)
            if resp.ok:
                results = resp.json().get('result', [])
                if results:
                    # Return the identifier if title matches reasonably well
                    from rapidfuzz import fuzz
                    zb_title = results[0].get('title', {}).get('title', '')
                    if fuzz.partial_ratio(title.lower(), zb_title.lower()) > 70:
                        return results[0].get('identifier')
        except Exception as e:
            logger.error(f"zbMATH Metadata search failed: {e}")
            
        return None

    def get_full_metadata(self, zbl_id: str) -> Optional[Dict[str, Any]]:
        """Stage 3: Fetch full facts from zbMATH REST API (Preferred) or OAI-PMH."""
        self._ensure_api_access()
        self._wait_for_rate_limit()
        
        # Try REST API first (it's richer than OAI)
        try:
            url = f'https://api.zbmath.org/v1/document/_search?search_string=an:{zbl_id}'
            resp = self.session.get(url, timeout=10)
            if resp.ok:
                results = resp.json().get('result', [])
                if results:
                    doc = results[0]
                    authors = [a.get('name') for a in doc.get('contributors', {}).get('authors', [])]
                    review = ""
                    if doc.get('editorial_contributions'):
                        review = doc['editorial_contributions'][0].get('text', '')
                    
                    data = {
                        'zbl_id': zbl_id,
                        'title': doc.get('title', {}).get('title', ''),
                        'authors': authors,
                        'msc_code': ", ".join([m.get('code') for m in doc.get('msc', [])]),
                        'keywords': ", ".join(doc.get('keywords', [])),
                        'links': json.dumps(doc.get('links', [])),
                        'review_markdown': review
                    }
                    self._save_to_cache(data)
                    return data
        except Exception as e:
            logger.error(f"REST API fetch failed for {zbl_id}: {e}")

        # Fallback: OAI-PMH
        params = {"verb": "GetRecord", "metadataPrefix": "oai_dc", "identifier": f"oai:zbmath.org:{zbl_id}"}
        try:
            resp = self.session.get(self.OAI_URL, params=params, timeout=15)
            if resp.status_code == 200 and "idDoesNotExist" not in resp.text:
                data = self._parse_oai_xml(resp.text, zbl_id)
                if data:
                    self._save_to_cache(data)
                return data
        except Exception as e: logger.error(f"OAI fetch failed: {e}")
        return None

    def _save_to_cache(self, data: Dict[str, Any]):
        """Persists metadata to SQLite JSONB-ready schema."""
        try:
            with self.db.get_connection() as conn:
                conn.execute("""
                    INSERT INTO zbmath_cache (zbl_id, msc_code, authors, title, keywords, links, review_markdown)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(zbl_id) DO UPDATE SET
                        msc_code = excluded.msc_code,
                        authors = excluded.authors,
                        title = excluded.title,
                        keywords = excluded.keywords,
                        links = excluded.links,
                        review_markdown = excluded.review_markdown,
                        fetched_at = unixepoch()
                """, (
                    data['zbl_id'], 
                    data.get('msc_code', ''), 
                    json.dumps(data.get('authors', [])),
                    data['title'],
                    data.get('keywords', ''),
                    data.get('links', '[]'),
                    data.get('review_markdown', '')
                ))
        except Exception as e:
            logger.error(f"Failed to cache zbMATH data: {e}")

    def _parse_oai_xml(self, xml_text: str, original_id: str) -> Dict[str, Any]:
        try:
            root = ET.fromstring(xml_text)
            ns = {'oai': 'http://www.openarchives.org/OAI/2.0/', 'dc': 'http://purl.org/dc/elements/1.1/', 'oai_dc': 'http://www.openarchives.org/OAI/2.0/oai_dc/'}
            metadata = root.find('.//oai_dc:dc', ns)
            if metadata is None: return {}
            return {
                'zbl_id': original_id,
                'title': getattr(metadata.find('dc:title', ns), 'text', ''),
                'authors': [e.text for e in metadata.findall('dc:creator', ns)],
                'description': getattr(metadata.find('dc:description', ns), 'text', ''),
                'msc_code': '', # Requires zbmath metadata prefix, staying with DC for now
                'review_markdown': getattr(metadata.find('dc:description', ns), 'text', '')
            }
        except Exception as e: return {}

    def match_citation(self, raw_string: str) -> Optional[Dict[str, Any]]:
        res = self.resolve_citation(raw_string)
        if res and res.get('doi'):
            zbl = self.get_zbl_id_from_doi(res['doi'])
            if zbl: return self.get_full_metadata(zbl)
        return None

    def enrich_book(self, book_id: int) -> Dict[str, Any]:
        """Main entry point for verifiying and enriching a book with zbMATH data."""
        with self.db.get_connection() as conn:
            book = conn.execute("SELECT id, title, author, doi, zbl_id FROM books WHERE id = ?", (book_id,)).fetchone()
        
        if not book:
            return {"success": False, "error": "Book not found"}

        doi = book['doi']
        zbl_id = book['zbl_id']

        # 1. Resolve Zbl ID if missing but DOI exists
        if not zbl_id and doi:
            logger.info(f"Resolving Zbl ID for DOI: {doi}")
            zbl_id = self.get_zbl_id_from_doi(doi)
            if zbl_id:
                with self.db.get_connection() as conn:
                    conn.execute("UPDATE books SET zbl_id = ? WHERE id = ?", (zbl_id, book_id))

        # 1.1 Fallback: Search by metadata
        if not zbl_id:
            logger.info(f"Fallback: Searching Zbl ID by metadata for: {book['title']}")
            zbl_id = self.find_zbl_id_by_metadata(book['title'], book['author'])
            if zbl_id:
                with self.db.get_connection() as conn:
                    conn.execute("UPDATE books SET zbl_id = ? WHERE id = ?", (zbl_id, book_id))

        if not zbl_id:
            return {"success": False, "error": "No Zbl ID could be found for this book"}

        # 2. Fetch Full Metadata from zbMATH
        logger.info(f"Fetching full zbMATH metadata for Zbl {zbl_id}")
        zb_data = self.get_full_metadata(zbl_id)
        if not zb_data:
            return {"success": False, "error": "Failed to fetch metadata from zbMATH API"}

        # 3. Compare and Update
        from rapidfuzz import fuzz
        
        # Calculate Trust Score (Title similarity)
        local_title = book['title'] or ""
        zb_title = zb_data.get('title', '')
        similarity = fuzz.ratio(local_title.lower(), zb_title.lower()) / 100.0
        
        status = 'verified' if similarity > 0.85 else 'conflict'
        if local_title.lower() in ("unknown", "untitled", ""):
            status = 'verified' # Always trust zbMATH if we have nothing
            similarity = 1.0

        # Sync key fields back to 'books'
        msc = zb_data.get('msc_code', '')
        zb_author_str = ", ".join(zb_data.get('authors', []))

        with self.db.get_connection() as conn:
            conn.execute("""
                UPDATE books SET 
                    zbl_id = ?,
                    msc_class = ?,
                    author = CASE WHEN author IS NULL OR author = 'Unknown' THEN ? ELSE author END,
                    title = CASE WHEN title IS NULL OR title = 'Unknown' THEN ? ELSE title END,
                    metadata_status = ?,
                    trust_score = ?,
                    last_metadata_refresh = unixepoch()
                WHERE id = ?
            """, (zbl_id, msc, zb_author_str, zb_title, status, similarity, book_id))

        return {
            "success": True, 
            "zbl_id": zbl_id, 
            "status": status, 
            "trust_score": similarity,
            "msc": msc
        }

zbmath_service = ZBMathService()
