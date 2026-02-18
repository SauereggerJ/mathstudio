"""
Bibliography Page Extractor

Extracts bibliography pages from PDFs and saves them as separate files.
"""

import fitz  # PyMuPDF
from pathlib import Path
from typing import List, Tuple, Optional


def extract_bib_pages(book_path: str, book_id: int, book_title: str, bib_pages: List[int]) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract bibliography pages and save as a separate PDF.
    
    Args:
        book_path: Path to the source PDF
        book_id: Database ID of the book
        book_title: Title of the book
        bib_pages: List of page numbers to extract
        
    Returns:
        Tuple of (relative path to extracted PDF, error message)
    """
    try:
        print(f"[DEBUG] Extracting bib pages for book_id={book_id}")
        print(f"[DEBUG] Input path: {book_path}")
        
        book_path = Path(book_path)
        
        # Handle relative paths - assume they are relative to /library root
        # Database stores paths like "02_Analysis/..."
        # Docker mounts library root to /library
        if not book_path.is_absolute():
             candidate = Path("/library") / book_path
             if candidate.exists():
                 print(f"[DEBUG] Found file at: {candidate}")
                 book_path = candidate
             else:
                 # Fallback: try relative to current working dir (../)
                 candidate = Path("..") / book_path
                 if candidate.exists():
                     print(f"[DEBUG] Found file at: {candidate}")
                     book_path = candidate
        
        if not book_path.exists():
            print(f"[ERROR] Book file not found: {book_path}")
            return None, f"Book file not found: {book_path} (absolute: {book_path.absolute()})"
        
        # Create output directory for extracted pages
        # Use absolute path in Docker container
        output_dir = Path("/library/mathstudio/bib_extracts")
        output_dir.mkdir(exist_ok=True)
        print(f"[DEBUG] Output directory: {output_dir.absolute()}")
        
        # Generate output filename
        safe_title = "".join(c for c in book_title if c.isalnum() or c in (' ', '-', '_')).strip()
        safe_title = safe_title[:50]  # Limit length
        output_filename = f"{book_id}_{safe_title}_bib_pages.pdf"
        output_path = output_dir / output_filename
        
        print(f"[DEBUG] Extracting pages {bib_pages} to {output_path}")
        
        # Open source PDF and create new PDF with selected pages
        src_doc = fitz.open(str(book_path))
        dst_doc = fitz.open()  # Create new empty PDF
        
        # Copy selected pages
        for page_num in bib_pages:
            try:
                # Check if page exists (0-indexed)
                if 0 <= page_num < len(src_doc):
                    dst_doc.insert_pdf(src_doc, from_page=page_num, to_page=page_num)
                else:
                    print(f"[WARNING] Page {page_num} out of range (0-{len(src_doc)-1})")
            except Exception as e:
                 print(f"[ERROR] Failed to insert page {page_num}: {e}")
        
        # Save extracted pages
        dst_doc.save(str(output_path))
        dst_doc.close()
        src_doc.close()
        
        print(f"[DEBUG] Successfully extracted to {output_path}")
        
        # Return relative path for web access
        return str(output_path), None
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[ERROR] Exception in extract_bib_pages: {e}")
        return None, f"Error extracting pages: {str(e)}"
