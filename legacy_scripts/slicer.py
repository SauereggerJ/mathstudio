import io
import re
from pypdf import PdfReader, PdfWriter
from pathlib import Path

def create_context_slice(file_path, page_str, padding=10):
    """
    Creates a new PDF containing the requested pages plus padding.
    All processing is done in-memory.
    """
    # 1. Parse pages
    requested_pages = []
    # Find all numbers and ranges
    parts = re.split(r'[,\s]+', page_str)
    for part in parts:
        if '-' in part or '–' in part: # Handle both hyphen and en-dash
            m = re.match(r'(\d+)[\-–](\d+)', part)
            if m:
                start, end = int(m.group(1)), int(m.group(2))
                requested_pages.extend(range(start, end + 1))
        elif part.isdigit():
            requested_pages.append(int(part))

    if not requested_pages:
        return None

    # 2. Add padding and sort
    ranges = []
    for p in requested_pages:
        ranges.append((max(1, p - padding), p + padding))
    
    ranges.sort()

    # 3. Merge overlapping ranges
    merged = []
    if ranges:
        curr_start, curr_end = ranges[0]
        for next_start, next_end in ranges[1:]:
            if next_start <= curr_end + 1:
                curr_end = max(curr_end, next_end)
            else:
                merged.append((curr_start, curr_end))
                curr_start, curr_end = next_start, next_end
        merged.append((curr_start, curr_end))

    # 4. Extract pages from PDF
    reader = PdfReader(file_path)
    writer = PdfWriter()
    
    # Add a simple cover page if possible
    # (Creating a full LaTeX cover page in-memory without temp files is complex, 
    # so we just add the content pages for now. pypdf doesn't easily create text pages from scratch)
    
    total_pdf_pages = len(reader.pages)
    
    for start, end in merged:
        # pypdf is 0-indexed, user input is 1-indexed
        for p_idx in range(start - 1, min(end, total_pdf_pages)):
            writer.add_page(reader.pages[p_idx])

    # 5. Output to buffer
    output_buffer = io.BytesIO()
    writer.write(output_buffer)
    output_buffer.seek(0)
    
    return output_buffer
