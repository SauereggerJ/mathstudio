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
# JSON Schemas removed in favor of XML block extraction
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
        
        # Build prompt: Request XML formatting with strict labels
        prompt = (
            "You are an expert mathematical typesetter and LaTeX transcription specialist.\n"
            f"Transcribe the following {len(page_files)} textbook pages into clean, COMPILABLE LaTeX.\n\n"
            "=== STRICT ANTI-CRASH RULES ===\n"
            "1. NO TIKZ: Never use \\begin{tikzpicture}.\n"
            "2. DELIMITER BALANCE: Every \\left MUST have a corresponding \\right.\n"
            "3. PRESERVE TEXT: Preserve exact prose and spaces.\n\n"
            "=== OUTPUT FORMAT ===\n"
            "For each page, output an XML block structured EXACTLY like this:\n"
            "<page>\n  <pdf_page_idx>THE_PROVIDED_INDEX</pdf_page_idx>\n  <latex>... transcribed LaTeX code here ...</latex>\n</page>\n\n"
            "Output nothing else but the XML blocks."
        )
        parts.append(types.Part.from_text(text=prompt))

        for pnum, fpath, mime, rtxt in page_files:
            up = ai.client.files.upload(
                file=str(fpath),
                config=types.UploadFileConfig(display_name=f"p{pnum}")
            )
            uploaded_files.append(up)
            parts.append(types.Part.from_text(text=f"PDF_PAGE_IDX {pnum}:"))
            parts.append(types.Part.from_uri(file_uri=up.uri, mime_type=mime))

        # 3. Process via AI
        contents = [types.Content(role="user", parts=parts)]
        raw_text = ai.generate_text(contents)
        
        # 4. Cleanup
        for up in uploaded_files:
            try: ai.client.files.delete(name=up.name) 
            except: pass
        for _, fpath, _, _ in page_files:
            if fpath.exists(): fpath.unlink()

        # 5. Parse
        if raw_text:
            import re
            pages_data = []
            page_blocks = re.findall(r'<page>(.*?)</page>', raw_text, re.DOTALL)
            requested_pnums = [p for p, _, _, _ in page_files]
            raw_map = {p: rtxt for p, _, _, rtxt in page_files}

            for i, block in enumerate(page_blocks):
                num_match = re.search(r'<pdf_page_idx>(.*?)</pdf_page_idx>', block, re.DOTALL)
                latex_match = re.search(r'<latex>(.*?)</latex>', block, re.DOTALL)
                if latex_match:
                    try:
                        p_num = None
                        if num_match:
                            try:
                                candidate = int(re.sub(r'\D', '', num_match.group(1)))
                                if candidate in requested_pnums:
                                    p_num = candidate
                            except: pass
                        
                        if p_num is None and i < len(requested_pnums):
                            p_num = requested_pnums[i] # Fallback to order
                        
                        if p_num is not None:
                            latex_code = latex_match.group(1).strip()
                            if latex_code.startswith("```latex"):
                                latex_code = latex_code[8:].strip()
                            if latex_code.endswith("```"):
                                latex_code = latex_code[:-3].strip()
                            
                            pages_data.append({
                                'page_number': p_num,
                                'latex': latex_code,
                                'raw_text': raw_map.get(p_num, "")
                            })
                    except: pass
            
            if pages_data:
                return pages_data, None
            
        return None, "Gemini failed to return valid XML blocks for the batch."

    except Exception as e:
        # Cleanup on failure
        for _, fpath, _, _ in page_files:
            if fpath.exists(): fpath.unlink()
        logger.error(f"Batch conversion failed: {e}")
        return None, f"Conversion Error: {str(e)}"

def extract_terms_batch(concatenated_latex, start_page, end_page, metadata=None):
    """
    Analyzes a window of LaTeX pages to extract terms (theorems, etc.) starting within a specific page range.
    Handles overflow into subsequent pages.
    """
    context_str = ""
    if metadata:
        context_str = f"BOOK CONTEXT: Title: {metadata.get('title')}, Author: {metadata.get('author')}\n\n"

    prompt = (
        "You are a mathematical knowledge extraction agent. You are provided with a multi-page LaTeX document extracted from a PDF.\n"
        f"{context_str}"
        "CRITICAL RULE: USE ONLY THE PROVIDED LATEX TEXT BELOW. DO NOT use your internal training data or memory of this book to invent terms. "
        "The page numbers provided (e.g. 'PAGE 141') refer to the PDF index, NOT the printed page numbers in the book. "
        "If the provided LaTeX text does not contain a specific theorem or definition, DO NOT REPORT IT, even if you know it exists elsewhere in this book.\n\n"
        f"TASK: Identify formal, valuable mathematical terms (Definition, Theorem, Lemma, Proposition, Corollary, Example, Exercise, Axiom, Notation, Remark) that BEGIN between PDF PAGE {start_page} and PDF PAGE {end_page} inclusive.\n\n"
        "RULES:\n"
        "1. QUALITY OVER QUANTITY: Only extract terms that are explicitly present in the LaTeX text provided.\n"
        "   - DO NOT extract: Chapter/Section titles, Table of Contents, simple sentences, or random headers.\n"
        "   - DO NOT imagine terms if none exist. If the page contains only text or titles, return an empty array: {\"terms\": []}.\n"
        f"2. RANGE: Only extract terms that explicitly begin their statement within PDF PAGE {start_page} to {end_page}.\n"
        "   - NO ORPHANS: If a Proof or Remark continues in this range, but its parent started BEFORE PDF PAGE {start_page}, SKIP IT.\n"
        "3. METADATA ONLY XML FORMAT:\n"
        "   For each term, output a strict XML block like this:\n"
        "   <term>\n"
        "     <name>Banach-Steinhaus Theorem (Theorem 5.1)</name>\n"
        "     <type>theorem</type>\n"
        "     <page_start>THE_PDF_PAGE_INDEX</page_start>\n"
        "     <used_terms>keyword1, keyword2</used_terms>\n"
        "     <start_marker>\\textbf{5.1 Theorem}</start_marker>\n"
        "     <end_marker>first 30 chars of the NEXT section</end_marker>\n"
        "   </term>\n"
        "4. DO NOT use JSON. Only output sequences of <term> blocks.\n\n"
        "LATEX CONTENT TO ANALYZE:\n"
        f"{concatenated_latex}"
    )

    logger.info(f"Full prompt start: {prompt[:500]}")
    try:
        import re
        term_blocks = ai.generate_xml_blocks(prompt, "term")
        
        parsed_terms = []
        for block in term_blocks:
            term_dict = {}
            for field in ['name', 'type', 'page_start', 'used_terms', 'start_marker', 'end_marker']:
                m = re.search(rf'<{field}>(.*?)</{field}>', block, re.DOTALL)
                if m:
                    val = m.group(1).strip()
                    if field == 'page_start':
                        try: val = int(val)
                        except: val = start_page
                    elif field == 'used_terms':
                        val = [x.strip() for x in val.split(',')]
                    term_dict[field] = val
            
            if 'name' in term_dict and 'type' in term_dict and 'page_start' in term_dict:
                parsed_terms.append(term_dict)

        if parsed_terms:
            return parsed_terms, None
        return [], "Failed to parse terms from XML response."
    except Exception as e:
        logger.error(f"Batch contextual extraction failed: {e}")
        return None, str(e)


def lint_latex(latex: str) -> list[str]:
    """Basic LaTeX sanity checks to detect common Gemini hallucinations."""
    errors = []
    if not latex or len(latex.strip()) < 10:
        errors.append("Empty LaTeX code")
        return errors
        
    # Check delimiters
    if latex.count('$') % 2 != 0:
        errors.append("Unbalanced $ delimiters")
    if latex.count('\\begin{') != latex.count('\\end{'):
        errors.append("Unbalanced \\begin/\\end environments")
    if latex.count('\\left') != latex.count('\\right'):
        errors.append("Unbalanced \\left/\\right delimiters")
        
    # Check for forbidden TIKZ
    if '\\begin{tikzpicture}' in latex:
        errors.append("Contains forbidden TikZ environment")
        
    return errors

def is_term_extractable(latex: str) -> bool:
    """Check if converted LaTeX has actual mathematical content worth extracting."""
    if not latex or len(latex) < 150:
        return False
    lower = latex.lower()
    has_math = '$' in latex or '\\begin{' in latex
    is_biblio = lower.count('\\bibitem') > 3 or lower.count('[') > 20
    return has_math and not is_biblio

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
    )
    
    try:
        blocks = ai.generate_xml_blocks(prompt, "repaired_latex")
        if blocks:
            # Return the first repaired block
            return blocks[0].replace('\\n', '\n')
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
