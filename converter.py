import os
import sys
import json
import logging
import subprocess
from pathlib import Path
import fitz  # PyMuPDF
from google.genai import types
import requests

from core.ai import ai
from core.config import TEMP_UPLOADS_DIR

logger = logging.getLogger(__name__)

# --- JSON Schemas for Gemini Structured Output ---
PAGE_CONVERSION_SCHEMA = {
    "type": "object",
    "properties": {
        "pages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "page_number": {"type": "integer"},
                    "latex": {"type": "string"}
                },
                "required": ["page_number", "latex"]
            }
        }
    },
    "required": ["pages"]
}

TERM_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                    "page_start": {"type": "integer"},
                    "used_terms": {"type": "array", "items": {"type": "string"}},
                    "start_marker": {"type": "string"},
                    "end_marker": {"type": "string"}
                },
                "required": ["name", "type", "page_start", "start_marker"]
            }
        }
    },
    "required": ["terms"]
}

REPAIR_SCHEMA = {
    "type": "object",
    "properties": {
        "repaired_latex": {"type": "string"}
    },
    "required": ["repaired_latex"]
}


def _render_djvu_page_to_image(book_path: str, page_num: int, out_path: Path) -> str | None:
    """Render a single DjVu page to a PNG image.
    Uses ddjvu to render to TIFF first (as some versions lack PNG support),
    then converts to PNG via PyMuPDF.
    """
    temp_tiff = out_path.with_suffix(".tiff")
    try:
        # 1. Render to TIFF
        result = subprocess.run(
            [
                "ddjvu",
                "-format=tiff",
                "-scale=300",          # Higher scale for better OCR
                f"-page={page_num}",
                book_path,
                str(temp_tiff)
            ],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            return f"ddjvu error: {result.stderr.strip() or 'unknown'}"
            
        if not temp_tiff.exists() or temp_tiff.stat().st_size < 100:
            return "ddjvu produced empty/missing TIFF"
            
        # 2. Convert TIFF to PNG via PyMuPDF
        doc = fitz.open(str(temp_tiff))
        page = doc[0]
        pix = page.get_pixmap()
        pix.save(str(out_path))
        doc.close()
        
        # Cleanup temp tiff
        if temp_tiff.exists():
            temp_tiff.unlink()
            
        if not out_path.exists() or out_path.stat().st_size < 100:
            return "TIFF to PNG conversion failed"
            
        return None
    except Exception as e:
        if temp_tiff.exists():
            temp_tiff.unlink()
        return f"djvu rendering exception: {e}"


def _extract_djvu_text(book_path: str, page_num: int) -> str | None:
    """Extract raw text from a DjVu page using djvutxt."""
    try:
        result = subprocess.run(
            ["djvutxt", f"--page={page_num}", book_path],
            capture_output=True, text=True, timeout=30
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None

def extract_raw_text(book_path, page_num):
    """
    Extracts raw text from a PDF (or DjVu) page.
    Fast, free, no API calls. Used as fallback when AI conversion fails.
    """
    if book_path.lower().endswith('.djvu'):
        return _extract_djvu_text(book_path, page_num)
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


def get_page_char_count(book_path: str, page_num: int) -> int:
    """Returns the number of characters in the embedded text stream of a PDF page."""
    try:
        doc = fitz.open(book_path)
        if page_num < 1 or page_num > len(doc):
            doc.close()
            return 0
        page = doc[page_num - 1]
        text_count = len(page.get_text().strip())
        doc.close()
        return text_count
    except Exception:
        return 0

def convert_pages_batch(book_path: str, pages: list[int]):
    """
    Converts a batch of pages (10-15) to high-quality LaTeX using Gemini.
    Uses 'Gate' logic to decide between Technique A (Native PDF) and Technique B (Raster).
    Returns (list_of_results, error_string).
    """
    if not os.path.exists(book_path):
        return None, "Book file not found."

    is_djvu = book_path.lower().endswith('.djvu')
    page_files = [] # List of (page_num, file_path, mime_type, raw_text)
    
    try:
        if is_djvu:
            # DjVu doesn't support Technique A, always use Raster (Technique B)
            for page_num in pages:
                temp_image = TEMP_UPLOADS_DIR / f"batch_p{page_num}_{os.getpid()}.png"
                err = _render_djvu_page_to_image(book_path, page_num, temp_image)
                raw_text = _extract_djvu_text(book_path, page_num) or ""
                if not err:
                    page_files.append((page_num, temp_image, "image/png", raw_text))
                    logger.info(f"Added DjVu page {page_num} to batch.")
                else:
                    logger.error(f"Failed to render DjVu page {page_num}: {err}")
        else:
            # PDF: Apply Gate Logic
            doc = fitz.open(book_path)
            for page_num in pages:
                if page_num < 1 or page_num > len(doc):
                    continue
                    
                page = doc[page_num - 1]
                raw_text = page.get_text()
                char_count = len(raw_text.strip())
                
                if char_count > 50:
                    # TECHNIQUE A: Born-Digital (Save single page PDF)
                    temp_pdf = TEMP_UPLOADS_DIR / f"batch_p{page_num}_{os.getpid()}.pdf"
                    new_doc = fitz.open()
                    new_doc.insert_pdf(doc, from_page=page_num-1, to_page=page_num-1)
                    new_doc.save(str(temp_pdf))
                    new_doc.close()
                    page_files.append((page_num, temp_pdf, "application/pdf", raw_text))
                    logger.info(f"Added PDF page {page_num} to batch (Technique A).")
                else:
                    # TECHNIQUE B: Scanned (High-res Raster 300 DPI)
                    temp_image = TEMP_UPLOADS_DIR / f"batch_p{page_num}_{os.getpid()}.png"
                    pix = page.get_pixmap(matrix=fitz.Matrix(4, 4)) # ~300 DPI (4x zoom)
                    pix.save(str(temp_image))
                    page_files.append((page_num, temp_image, "image/png", raw_text))
                    logger.info(f"Added PDF page {page_num} to batch (Technique B).")
            doc.close()

        if not page_files:
            return [], "No valid pages to process."

        # 2. Upload all files and prepare Gemini message
        uploaded_files = []
        parts = []
        
        # Build prompt: Request flattened schema, ONLY LATEX, NO DISCOVERIES
        prompt = (
            "You are an expert mathematical typesetter and LaTeX transcription specialist.\n"
            f"Transcribe the following {len(page_files)} textbook pages into clean, compilable LaTeX.\n\n"
            "=== REQUIREMENTS ===\n"
            "- Use amsmath, amssymb, amsthm for all mathematical notation.\n"
            "- Preserve ALL prose text EXACTLY.\n"
            "- IGNORE page numbers, running headers, and footers.\n"
            "- Every word in the original text is separated by a space. You MUST preserve these spaces.\n\n"
            "=== OUTPUT FORMAT ===\n"
            "Return a strictly valid JSON object with a 'pages' array where each object has:\n"
            "- 'page_number': (integer)\n"
            "- 'latex': (string)\n\n"
            "IMPORTANT: Return ONLY the JSON object. Use actual newlines (\\n) in the LaTeX string."
        )
        parts.append(types.Part.from_text(text=prompt))

        for pnum, fpath, mime, rtxt in page_files:
            up = ai.client.files.upload(
                file=str(fpath),
                config=types.UploadFileConfig(display_name=f"page_{pnum}")
            )
            uploaded_files.append(up)
            parts.append(types.Part.from_text(text=f"PAGE {pnum}:"))
            parts.append(types.Part.from_uri(file_uri=up.uri, mime_type=mime))

        # 3. Process via AI
        contents = [types.Content(role="user", parts=parts)]
        data = ai.generate_json(contents, schema=PAGE_CONVERSION_SCHEMA)

        # 4. Cleanup
        for up in uploaded_files:
            try: ai.client.files.delete(name=up.name) 
            except: pass
        for _, fpath, _, _ in page_files:
            if fpath.exists(): fpath.unlink()

        if data and 'pages' in data:
            # Reattach raw text from local extraction
            raw_map = {pnum: rtxt for pnum, _, _, rtxt in page_files}
            for p_res in data['pages']:
                p_res['raw_text'] = raw_map.get(p_res['page_number'], "")
            return data['pages'], None
            
        return None, "Gemini failed to return valid JSON for the batch."

    except Exception as e:
        # Cleanup on failure
        for _, fpath, _, _ in page_files:
            if fpath.exists(): fpath.unlink()
        logger.error(f"Batch conversion failed: {e}")
        return None, f"Conversion Error: {str(e)}"

def extract_terms_from_context(concatenated_latex, target_page_num, metadata=None):
    """
    Analyzes a window of LaTeX pages to extract terms (theorems, etc.) starting on a specific page.
    Handles overflow into subsequent pages.
    """
    context_str = ""
    if metadata:
        context_str = f"BOOK CONTEXT: Title: {metadata.get('title')}, Author: {metadata.get('author')}\n\n"

    prompt = (
        "You are a mathematical knowledge extraction agent. You are provided with a multi-page LaTeX document from a math book.\n"
        f"{context_str}"
        f"TASK: Identify every formal term (Definition, Theorem, Lemma, Proposition, Corollary, Example, Exercise) that STARTS on Page {target_page_num}.\n\n"
        "RULES:\n"
        f"1. ONLY extract terms that explicitly begin their statement on Page {target_page_num}.\n"
        f"   - CRITICAL: If a Proof starts or continues on Page {target_page_num}, but its parent Theorem/Proposition started on a PREVIOUS page, DO NOT EXTRACT IT.\n"
        "2. For each term, provide ONLY metadata — do NOT include the full LaTeX content:\n"
        "   - 'name': A HIGHLY DESCRIPTIVE, SEMANTIC CONCEPT NAME followed by the formal label in parentheses. Example: 'Dominated Convergence Theorem (Theorem 2.25)'. NEVER use a generic label like 'Theorem 3' as the entire name.\n"
        "   - 'type': One of: definition, theorem, lemma, proposition, corollary, example, exercise, remark, note. (NEVER use 'proof').\n"
        f"   - 'page_start': {target_page_num}\n"
        "   - 'used_terms': Technical mathematical keywords and notation used in the term.\n"
        "   - 'start_marker': A short text string (5-30 chars) that uniquely identifies WHERE this term begins in the LaTeX. Use the formal label like '2.25 Theorem' or 'Definition 3.1' or the first few distinctive words.\n"
        "   - 'end_marker': (optional) A short text string identifying where the NEXT term or section begins, marking the end of this term. Use the next label like '2.26' or 'Corollary' or leave empty if it's the last item on the page.\n"
        "3. Return a JSON object with key 'terms' containing an array.\n"
        "4. If no terms start on the target page, return: {\"terms\": []}\n\n"
        "LATEX CONTENT:\n"
        f"{concatenated_latex}\n\n"
        "IMPORTANT: Return ONLY the JSON object. Do NOT include any LaTeX content in your response."
    )

    try:
        data = ai.generate_json(prompt, schema=TERM_EXTRACTION_SCHEMA)
        if data and 'terms' in data:
            return data['terms'], None
        return [], "Failed to parse terms from AI response."
    except Exception as e:
        logger.error(f"Contextual extraction failed: {e}")
        return None, str(e)


def extract_terms_batch(concatenated_latex, start_page, end_page, metadata=None):
    """
    Analyzes a window of LaTeX pages to extract terms (theorems, etc.) starting within a specific page range.
    Handles overflow into subsequent pages.
    """
    context_str = ""
    if metadata:
        context_str = f"BOOK CONTEXT: Title: {metadata.get('title')}, Author: {metadata.get('author')}\n\n"

    prompt = (
        "You are a mathematical knowledge extraction agent. You are provided with a multi-page LaTeX document from a math book.\n"
        f"{context_str}"
        f"TASK: Identify every formal term (Definition, Theorem, Lemma, Proposition, Corollary, Example, Exercise) that STARTS between Page {start_page} and Page {end_page} inclusive.\n\n"
        "RULES:\n"
        f"1. ONLY extract terms that explicitly begin their statement within Page {start_page} to {end_page}.\n"
        f"   - CRITICAL: If a Proof starts or continues in this range, but its parent started BEFORE Page {start_page}, DO NOT EXTRACT IT.\n"
        "2. For each term, provide ONLY metadata — do NOT include the full LaTeX content:\n"
        "   - 'name': A HIGHLY DESCRIPTIVE, SEMANTIC CONCEPT NAME followed by the formal label in parentheses. Example: 'Dominated Convergence Theorem (Theorem 2.25)'. NEVER use a generic label like 'Theorem 3' as the entire name.\n"
        "   - 'type': One of: definition, theorem, lemma, proposition, corollary, example, exercise, remark, note. (NEVER use 'proof').\n"
        "   - 'page_start': (integer) The exact page number where this term begins.\n"
        "   - 'used_terms': Technical mathematical keywords and notation used in the term.\n"
        "   - 'start_marker': A short text string (5-30 chars) that uniquely identifies WHERE this term begins in the LaTeX. Use the formal label like '2.25 Theorem' or 'Definition 3.1' or the first few distinctive words.\n"
        "   - 'end_marker': (optional) A short text string identifying where the NEXT term or section begins.\n"
        "3. Return a JSON object with key 'terms' containing an array.\n"
        "4. If no terms start in the range, return: {\"terms\": []}\n\n"
        "LATEX CONTENT:\n"
        f"{concatenated_latex}\n\n"
        "IMPORTANT: Return ONLY the JSON object. Do NOT include any LaTeX content in your response."
    )

    try:
        data = ai.generate_json(prompt, schema=TERM_EXTRACTION_SCHEMA)
        if data and 'terms' in data:
            return data['terms'], None
        return [], "Failed to parse terms from AI response."
    except Exception as e:
        logger.error(f"Batch contextual extraction failed: {e}")
        return None, str(e)


def repair_latex(latex_content: str, original_text_preview: str, error_msg: str) -> str | None:
    """Active Repair Loop: Takes failed LaTeX and attempts to fix it based on error messages."""
    prompt = (
        "You are an expert mathematical LaTeX repair specialist.\n"
        "The following LaTeX code failed quality or compilation checks. Your task is to FIX IT.\n\n"
        "=== ORIGINAL TEXT ===\n"
        f"{original_text_preview[:4000]}\n\n"
        "=== FAILED LATEX ===\n"
        f"{latex_content}\n\n"
        "=== ERROR MESSAGE ===\n"
        f"{error_msg}\n\n"
        "=== INSTRUCTIONS ===\n"
        "1. Analyze the error message and the failed LaTeX.\n"
        "2. Cross-reference with the original text to ensure mathematical fidelity.\n"
        "3. Return the COMPLETE REPAIRED LaTeX code.\n"
        "4. Return ONLY the JSON object: {\"repaired_latex\": \"...\"}"
    )
    
    try:
        data = ai.generate_json(prompt, schema=REPAIR_SCHEMA)
        if data and 'repaired_latex' in data:
            return data['repaired_latex'].replace('\\n', '\n')
    except Exception as e:
        logger.error(f"Repair attempt failed: {e}")
    return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    # Test execution
    if len(sys.argv) < 3:
        print("Usage: python converter.py <pdf_path> <page_num>")
        sys.exit(1)
    
    path = sys.argv[1]
    page = int(sys.argv[2])
    data_list, err = convert_pages_batch(path, [page])
    
    if err or not data_list:
        print(f"Error: {err or 'Batch conversion returned no data'}")
    else:
        data = data_list[0]
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
        
        # Save LaTeX
        with open(tex_path, 'w', encoding='utf-8') as f:
            content = data.get('latex', '').replace('\\n', '\n')
            f.write(content)
        print(f"Saved: {tex_path}")
        
        # Save a simple Markdown version that just embeds the LaTeX
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(f"# {filename}\n\n```latex\n{content}\n```")
        print(f"Saved: {md_path}")
