import io
import re
from pypdf import PdfReader, PdfWriter
from pathlib import Path

def parse_page_range(page_str, max_pages=None):
    """Parses a page range string into a list of integers."""
    if not page_str:
        return []
    
    pages = set()
    parts = re.split(r'[,\s]+', str(page_str))
    for part in parts:
        if '-' in part or '–' in part:
            m = re.match(r'(\d+)[\-–](\d+)', part)
            if m:
                start, end = int(m.group(1)), int(m.group(2))
                start = max(1, start)
                if max_pages: end = min(max_pages, end)
                if start <= end:
                    for p in range(start, end + 1):
                        pages.add(p)
        elif part.isdigit():
            p = int(part)
            if p >= 1:
                if max_pages and p > max_pages: continue
                pages.add(p)
    return sorted(list(pages))

def create_pdf_slice(file_path, page_str, padding=0):
    """Creates a new PDF containing requested pages."""
    try:
        reader = PdfReader(file_path)
        total_pages = len(reader.pages)
        requested = parse_page_range(page_str, total_pages)
        
        if not requested: return None
        
        if padding > 0:
            padded = set()
            for p in requested:
                for i in range(max(1, p - padding), min(total_pages, p + padding) + 1):
                    padded.add(i)
            requested = sorted(list(padded))

        writer = PdfWriter()
        for p in requested:
            writer.add_page(reader.pages[p - 1])

        output = io.BytesIO()
        writer.write(output)
        output.seek(0)
        return output
    except Exception as e:
        print(f"[Utils] Slice error: {e}")
        return None
