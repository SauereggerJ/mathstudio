import os
import sys
from pathlib import Path
import pypdf
from google import genai
from google.genai import types

from utils import load_api_key

# Configuration (Mirrors search.py for consistency)
GEMINI_API_KEY = load_api_key()
LLM_MODEL = "gemini-2.0-flash"

import requests
import json



def extract_text_pypdf(pdf_path, page_num):
    """Extracts text from a single page of a PDF using pypdf."""
    try:
        reader = pypdf.PdfReader(pdf_path)
        if page_num < 1 or page_num > len(reader.pages):
            return None, f"Page {page_num} out of range (1-{len(reader.pages)})"
        
        # pypdf pages are 0-indexed
        page = reader.pages[page_num - 1]
        text = page.extract_text()
        return text, None
    except Exception as e:
        return None, str(e)

def convert_page(book_path, page_num):
    """
    Converts a PDF page to a markdown note.
    
    Args:
        book_path (str): Absolute path to the PDF file.
        page_num (int): Page number (1-based).
        
    Returns:
        tuple: (markdown_content, error_message)
    """
    if not os.path.exists(book_path):
        return None, "Book file not found."
        
    text, error = extract_text_pypdf(book_path, page_num)
    if error:
        return None, f"PDF Extraction Error: {error}"
        
    if not text or len(text.strip()) < 10:
        return None, "Extracted text is too short or empty."

    prompt = (
        "Du bist ein mathematischer Setzer. Formatiere diese Buchseite in ZWEI Formaten:\n"
        "1. Sauberes Markdown mit LaTeX ($...$).\n"
        "2. Vollständiger LaTeX-Code (standalone header, article class).\n\n"
        "Ignoriere Seitenzahlen/Header. Gib ein JSON-Objekt zurück mit den Keys: 'markdown' und 'latex'.\n"
        "Gib NUR das JSON zurück.\n\n"
        f"INHALT:\n{text}"
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{LLM_MODEL}:generateContent?key={GEMINI_API_KEY}"
    
    payload = {
        "contents": [{
            "parts": [{"text": prompt}],
            "role": "user"
        }],
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }

    try:
        response = requests.post(url, json=payload, timeout=60)
        
        if response.status_code != 200:
            return None, f"Gemini API Error {response.status_code}: {response.text}"
            
        result = response.json()
        if 'candidates' in result and result['candidates']:
            content_text = result['candidates'][0]['content']['parts'][0]['text']
            try:
                data = json.loads(content_text)
                return data, None 
            except json.JSONDecodeError:
                # Fallback if model returns raw text despite instructions
                return {'markdown': content_text, 'latex': '% LaTeX generation failed because strict JSON was not returned.'}, None
        else:
            return None, "No content returned from Gemini."
            
    except Exception as e:
        return None, f"Gemini Request Error: {str(e)}"

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
