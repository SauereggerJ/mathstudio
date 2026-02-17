import re
import requests
import xml.etree.ElementTree as ET
from core.config import LIBRARY_ROOT
from pypdf import PdfReader

class MetadataService:
    def fetch_arxiv_metadata(self, arxiv_id):
        url = f'http://export.arxiv.org/api/query?id_list={arxiv_id}'
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                ns = {'atom': 'http://www.w3.org/2005/Atom', 'arxiv': 'http://arxiv.org/schemas/atom'}
                entry = root.find('atom:entry', ns)
                if entry:
                    meta = {}
                    meta['title'] = entry.find('atom:title', ns).text.strip().replace('
', ' ')
                    authors = [a.find('atom:name', ns).text for a in entry.findall('atom:author', ns)]
                    meta['author'] = ", ".join(authors)
                    published = entry.find('atom:published', ns).text
                    if published: meta['year'] = int(published[:4])
                    meta['publisher'] = "ArXiv"
                    summary = entry.find('atom:summary', ns)
                    meta['description'] = summary.text.strip() if summary is not None else ""
                    meta['arxiv_id'] = arxiv_id
                    return meta
        except Exception: pass
        return None

    def fetch_open_library_metadata(self, isbn):
        if not isbn: return None
        url = f"https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&jscmd=data&format=json"
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                key = f"ISBN:{isbn}"
                if key in data:
                    book_data = data[key]
                    meta = {}
                    meta['title'] = book_data.get('title')
                    authors = book_data.get('authors', [])
                    meta['author'] = ", ".join([a['name'] for a in authors]) if authors else None
                    publishers = book_data.get('publishers', [])
                    meta['publisher'] = publishers[0]['name'] if publishers else None
                    year_text = book_data.get('publish_date')
                    if year_text:
                        year_match = re.search(r'\d{4}', year_text)
                        if year_match: meta['year'] = int(year_match.group(0))
                    meta['isbn'] = isbn
                    return meta
        except Exception: pass
        return None

    def fetch_crossref_metadata(self, query_text):
        if not query_text or len(query_text) < 10: return None
        url = "https://api.crossref.org/works"
        params = {'query.bibliographic': query_text, 'rows': 1}
        try:
            response = requests.get(url, params=params, timeout=5)
            if response.status_code == 200:
                items = response.json().get('message', {}).get('items', [])
                if items:
                    item = items[0]
                    meta = {'title': item.get('title', [''])[0]}
                    authors = item.get('author', [])
                    auth_names = [f"{a.get('given', '')} {a['family']}" for a in authors if 'family' in a]
                    meta['author'] = ", ".join(auth_names) if auth_names else None
                    meta['publisher'] = item.get('publisher')
                    date_parts = item.get('created', {}).get('date-parts', [[None]])
                    if date_parts and date_parts[0] and date_parts[0][0]:
                         meta['year'] = date_parts[0][0]
                    meta['doi'] = item.get('DOI')
                    return meta
        except Exception: pass
        return None

    def extract_isbn(self, file_path):
        """Attempts to extract ISBN from the first few pages of a PDF."""
        if file_path.suffix.lower() != '.pdf':
            return None
        try:
            reader = PdfReader(file_path)
            num_pages = min(len(reader.pages), 5)
            text = ""
            for i in range(num_pages):
                text += reader.pages[i].extract_text() or ""
            isbn_pattern = re.compile(r'ISBN(?:-1[03])?:?\s*([\d\- X]{10,17})', re.IGNORECASE)
            match = isbn_pattern.search(text)
            if match:
                isbn_clean = re.sub(r'[^\dXx]', '', match.group(1))
                if len(isbn_clean) in [10, 13]:
                    return isbn_clean
        except Exception: pass
        return None

# Global instance
metadata_service = MetadataService()
