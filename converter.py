import os
import json
import gc
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from google.genai import types

from core.database import db
from core.ai import ai
from core.utils import PDFHandler

def convert_page(book_path: str, page_num: int) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Converts a PDF page to a markdown/LaTeX note using Gemini Vision.
    
    Args:
        book_path (str): Absolute path to the PDF file.
        page_num (int): Page number (1-based).
        
    Returns:
        tuple: (data_dict, error_message)
    """
    abs_path = Path(book_path)
    if not abs_path.exists():
        return None, "Book file not found."
        
    handler = PDFHandler(abs_path)
    slice_path = Path(f"/tmp/conv_slice_{os.getpid()}_{page_num}.pdf")
    
    try:
        # Create a single-page slice for Vision
        # PDFHandler uses 0-based indices
        handler.create_slice([page_num - 1], slice_path)
        
        uploaded = ai.upload_file(slice_path)
        if not uploaded:
            return None, "Failed to upload page slice to Gemini."

        prompt = (
            "You are a mathematical typesetter and transcription expert. \n"
            "TASK: Transcribe this Buchseite into TWO formats:\n"
            "1. Clean Markdown with LaTeX ($...$ or $$...$$).\n"
            "2. Standalone LaTeX code (article class).\n\n"
            "Maintain all mathematical formulas exactly. Ignore headers/footers/page numbers. \n"
            "Return a strictly valid JSON object with keys: 'markdown' and 'latex'."
        )
        
        contents = [types.Content(role="user", parts=[
            types.Part.from_uri(file_uri=uploaded.uri, mime_type=uploaded.mime_type),
            types.Part.from_text(text=prompt)
        ])]
        
        result_json = ai.generate_json(contents)
        
        # Cleanup
        ai.delete_file(uploaded.name)
        if slice_path.exists(): slice_path.unlink()
        gc.collect()
        
        if not result_json:
            return None, "AI analysis failed to return valid JSON."
            
        return result_json, None

    except Exception as e:
        if slice_path.exists(): slice_path.unlink()
        return None, f"Conversion Error: {str(e)}"

if __name__ == "__main__":
    import sys
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
        print(json.dumps(data, indent=2))
