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
        self.last_request_time = 0
        self.min_delay = 1.0
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": f"MathStudio/1.0 (mailto:{self.CONTACT_EMAIL})",
        })

    def _wait_for_rate_limit(self):
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_delay:
            time.sleep(self.min_delay - elapsed)
        self.last_request_time = time.time()

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
        """Dual-Bridge: Translate DOI to zbMATH ID."""
        # Bridge A: OpenAlex
        self._wait_for_rate_limit()
        try:
            resp = self.session.get(f"{self.OPENALEX_URL}/https://doi.org/{doi}", timeout=10)
            if resp.status_code == 200:
                zbl = resp.json().get('ids', {}).get('zbm')
                if zbl: return zbl
        except: pass

        # Bridge B: OAI-PMH (Search by DOI via ListRecords if possible, 
        # but standard OAI doesn't support it well. 
        # Fallback: We'll store the DOI and wait for a background crawler)
        return None

    def get_full_metadata(self, zbl_id: str) -> Optional[Dict[str, Any]]:
        """Stage 3: Fetch full facts from zbMATH OAI-PMH."""
        self._wait_for_rate_limit()
        params = {"verb": "GetRecord", "metadataPrefix": "oai_dc", "identifier": f"oai:zbmath.org:{zbl_id}"}
        try:
            resp = requests.get(self.OAI_URL, params=params, timeout=15)
            if resp.status_code == 200 and "idDoesNotExist" not in resp.text:
                return self._parse_oai_xml(resp.text, zbl_id)
        except Exception as e: logger.error(f"OAI fetch failed: {e}")
        return None

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

zbmath_service = ZBMathService()
