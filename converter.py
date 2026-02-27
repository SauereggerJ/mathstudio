import os
import sys
import json
import logging
from pathlib import Path
import fitz  # PyMuPDF
from google.genai import types
import requests

from core.ai import ai
from core.config import TEMP_UPLOADS_DIR

logger = logging.getLogger(__name__)

def extract_raw_text(book_path, page_num):
    """
    Extracts raw text from a PDF page using PyMuPDF.
    Fast, free, no API calls. Used as fallback when AI conversion fails.
    """
    try:
        doc = fitz.open(book_path)
        if page_num < 1 or page_num > len(doc):
            doc.close()
            return None
        page = doc[page_num - 1]
        text = page.get_text()
        doc.close()
        return text
    except Exception as e:
        logger.error(f"Raw text extraction failed: {e}")
        return None


def convert_page(book_path, page_num):
    """
    Converts a PDF page to high-quality LaTeX using Gemini Vision.
    Also detects definitions/theorems on the page for KB proposals.
    Returns (data_dict, error_string).
    """
    if not os.path.exists(book_path):
        return None, "Book file not found."
        
    temp_image = TEMP_UPLOADS_DIR / f"page_conv_{os.getpid()}_{page_num}.png"
    
    try:
        # 1. Render page to high-res image + extract raw text BEFORE closing
        doc = fitz.open(book_path)
        if page_num < 1 or page_num > len(doc):
            doc.close()
            return None, f"Page {page_num} out of range."
        
        page = doc[page_num - 1]
        raw_text = page.get_text()  # Extract raw text while doc is open
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2)) # 2x zoom for better OCR
        pix.save(str(temp_image))
        doc.close()

        # 2. Prepare Prompt — also asks for theorem/definition discovery
        prompt = (
            "You are a master mathematical typesetter. Convert this image of a book page into TWO formats:\n"
            "1. Clean Markdown with LaTeX ($...$).\n"
            "2. High-quality LaTeX code (using amsmath, amssymb). Focus on structural correctness.\n\n"
            "Additionally, extract any formal definitions, theorems, lemmas, propositions, or corollaries on this page.\n\n"
            "Requirements:\n"
            "- Extract ONLY the core mathematical content. Ignore headers, footers, and page numbers.\n"
            "- Ensure complex formulas are perfectly preserved.\n"
            "CRITICAL RULES FOR DISCOVERIES:\n"
            "- ONLY extract explicitly labeled or boxed mathematical environments (e.g., 'Definition 1.2.1', 'Theorem 3.4', 'Lemma'). Do NOT extract inline text.\n"
            "- The 'name' MUST be a descriptive, searchable concept name inferred from the text, followed by the formal label in parentheses. (e.g., 'Matrix Representation (Definition 1.2.1)' or 'Cauchy Sequence (Definition 3)'). Never just use 'Definition X'.\n"
            "- The 'snippet' MUST contain the ENTIRE text and math of the block, not just a single equation. Include all the prose explaining the theorem/definition.\n"
            "- Return a strictly valid JSON object with keys: 'markdown', 'latex', 'discoveries'.\n"
            "- 'discoveries' is an array of objects: [{\"name\": \"...\", \"kind\": \"theorem|definition|lemma|proposition|corollary\", \"snippet\": \"full text and LaTeX of the statement\"}]\n"
            "- If no formal definitions or theorems are found, return an empty array [] for 'discoveries'.\n"
            "IMPORTANT: Return ONLY the JSON."
        )

        # 3. Upload and Process via AIService
        uploaded_file = ai.client.files.upload(
            file=str(temp_image),
            config=types.UploadFileConfig(display_name=f"page_{page_num}_image")
        )
        
        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(text=prompt),
                    types.Part.from_uri(file_uri=uploaded_file.uri, mime_type=uploaded_file.mime_type)
                ]
            )
        ]
        
        data = ai.generate_json(contents)
        
        # Cleanup uploaded file
        try:
            ai.client.files.delete(name=uploaded_file.name)
        except Exception:
            pass
        if temp_image.exists():
            temp_image.unlink()

        if data:
            data['raw_text'] = raw_text
            # Ensure discoveries key exists
            if 'discoveries' not in data:
                data['discoveries'] = []
            return data, None
        else:
            return None, "Gemini failed to return valid JSON for the page image."

    except Exception as e:
        if temp_image.exists():
            temp_image.unlink()
        logger.error(f"Vision conversion failed: {e}")
        return None, f"Conversion Error: {str(e)}"

if __name__ == "__main__":
    # Test execution
    if len(sys.argv) < 3:
        print("Usage: python converter.py <pdf_path> <page_num>")
        sys.exit(1)
    
    path = sys.argv[1]
    page = int(sys.argv[2])
    data, err = convert_page(path, page)
    
    if err:
        print(f"Error: {err}")
    else:
        # Create output directory
        out_dir = Path("converted_notes")
        if not out_dir.exists():
            out_dir.mkdir()
            
        # Determine filename
        base_name = Path(path).stem
        safe_name = "".join(x for x in base_name if x.isalnum() or x in " -_")[:50]
        filename = f"{safe_name}_p{page}"
        
        md_path = out_dir / f"{filename}.md"
        tex_path = out_dir / f"{filename}.tex"
        
        # Save Markdown
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(data.get('markdown', ''))
        print(f"Saved: {md_path}")
            
        # Save LaTeX
        with open(tex_path, 'w', encoding='utf-8') as f:
            f.write(data.get('latex', ''))
        print(f"Saved: {tex_path}")
