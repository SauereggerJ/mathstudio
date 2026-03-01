"""
Bibliography Hunter Module

Extracts bibliographies from books, parses them with AI, and cross-checks against the library.
"""

import sqlite3
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import fitz  # PyMuPDF
from google import genai
from google.genai import types

from utils import load_api_key

# Configuration
DB_FILE = "library.db"
GEMINI_API_KEY = load_api_key()
LLM_MODEL = "gemini-2.5-flash-lite-preview-09-2025"

client = genai.Client(api_key=GEMINI_API_KEY)

# Bibliography keywords in multiple languages
BIB_KEYWORDS = [
    # English
    "bibliography", "references", "cited works", "works cited", "literature cited",
    # German
    "literaturverzeichnis", "bibliographie", "quellenverzeichnis", "literatur",
    # Common patterns
    "list of references", "reference list"
]


class BibHunter:
    """Extracts and analyzes bibliographies from books."""
    
    def __init__(self, db_file: str = DB_FILE):
        self.db_file = db_file
    
    def find_bib_pages(self, book_id: int) -> Tuple[Optional[List[int]], Optional[str]]:
        """
        Finds bibliography pages in a book by scanning the last 30 pages.
        
        Args:
            book_id: Database ID of the book
            
        Returns:
            Tuple of (list of page numbers, error message)
        """
        try:
            # Get book path from database
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            cursor.execute("SELECT path FROM books WHERE id = ?", (book_id,))
            result = cursor.fetchone()
            conn.close()
            
            if not result:
                return None, f"Book with ID {book_id} not found"
            
            book_path = Path(result[0])
            
            # Handle relative paths (assuming library root is parent of this script)
            if not book_path.is_absolute():
                # Try to find the library root
                script_dir = Path(__file__).parent
                # Check if we're in a subdirectory structure
                possible_roots = [
                    script_dir,
                    script_dir.parent,
                    Path("/srv/data/math/New_Research_Library")
                ]
                
                for root in possible_roots:
                    full_path = root / book_path
                    if full_path.exists():
                        book_path = full_path
                        break
            
            if not book_path.exists():
                return None, f"Book file not found: {book_path}"
            
            # Only support PDF for now (DjVu conversion would be added later)
            if book_path.suffix.lower() != '.pdf':
                return None, f"Unsupported format: {book_path.suffix}. Only PDF is supported."
            
            # Open PDF and scan last 30 pages
            doc = fitz.open(str(book_path))
            total_pages = len(doc)
            
            # Determine range to scan (last 30 pages)
            start_page = max(0, total_pages - 30)
            bib_pages = []
            
            for page_num in range(start_page, total_pages):
                page = doc[page_num]
                text = page.get_text().lower()
                
                # Check for bibliography keywords
                for keyword in BIB_KEYWORDS:
                    if keyword in text:
                        # Check if it's likely a section header (appears near start of page or in large text)
                        # Simple heuristic: keyword appears in first 500 chars of page
                        if text.index(keyword) < 500:
                            bib_pages.append(page_num + 1)  # Convert to 1-indexed
                            break
            
            doc.close()
            
            if not bib_pages:
                return None, "No bibliography section found in the last 30 pages"
            
            # Return continuous range from first detected page to end
            # (bibliographies are usually continuous)
            first_bib_page = min(bib_pages)
            # Extend to a reasonable range (e.g., 10 pages or until end)
            last_bib_page = min(first_bib_page + 9, total_pages)
            
            return list(range(first_bib_page, last_bib_page + 1)), None
            
        except Exception as e:
            return None, f"Error finding bibliography pages: {str(e)}"
    
    def parse_bib_with_ai(self, book_id: int, pages: List[int]) -> Tuple[Optional[List[Dict]], Optional[str]]:
        """
        Parses bibliography pages using Gemini AI.
        
        Args:
            book_id: Database ID of the book
            pages: List of page numbers to extract (1-indexed)
            
        Returns:
            Tuple of (list of citations, error message)
        """
        try:
            # Get book path from database
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            cursor.execute("SELECT path FROM books WHERE id = ?", (book_id,))
            result = cursor.fetchone()
            conn.close()
            
            if not result:
                return None, f"Book with ID {book_id} not found"
            
            book_path = Path(result[0])
            
            # Handle relative paths
            if not book_path.is_absolute():
                script_dir = Path(__file__).parent
                possible_roots = [
                    script_dir,
                    script_dir.parent,
                    Path("/srv/data/math/New_Research_Library")
                ]
                
                for root in possible_roots:
                    full_path = root / book_path
                    if full_path.exists():
                        book_path = full_path
                        break
            
            if not book_path.exists():
                return None, f"Book file not found: {book_path}"
            
            # Extract text from bibliography pages
            doc = fitz.open(str(book_path))
            bib_text = ""
            
            for page_num in pages:
                if page_num <= len(doc):
                    page = doc[page_num - 1]  # Convert to 0-indexed
                    bib_text += f"\n--- Page {page_num} ---\n"
                    bib_text += page.get_text()
            
            doc.close()
            
            if not bib_text.strip():
                return None, "No text extracted from bibliography pages"
            
            # Limit text length to avoid token limits (keep first 20000 chars)
            if len(bib_text) > 20000:
                bib_text = bib_text[:20000] + "\n... [truncated]"
            
            # Create AI prompt
            prompt = f"""You are a bibliography extraction expert. Extract all BOOK citations from the following bibliography text.

IMPORTANT RULES:
1. Extract ONLY books (monographs, textbooks, edited volumes)
2. IGNORE journal articles, conference papers, and other non-book citations
3. For each book, extract the title and author(s)
4. Return ONLY a valid JSON array with this exact format: [{{"title": "Book Title", "author": "Author Name"}}, ...]
5. If a citation has multiple authors, include all authors in the author field (e.g., "John Smith and Jane Doe")
6. Do not include any explanatory text, only the JSON array

Bibliography text:
{bib_text}

Return the JSON array now:"""

            # Call Gemini API
            response = client.models.generate_content(
                model=LLM_MODEL,
                contents=prompt
            )
            
            response_text = response.text.strip()
            
            # Extract JSON from response (handle markdown code blocks)
            json_match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', response_text, re.DOTALL)
            if json_match:
                json_text = json_match.group(1)
            else:
                # Try to find JSON array directly
                json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
                if json_match:
                    json_text = json_match.group(0)
                else:
                    return None, f"Could not extract JSON from AI response: {response_text[:200]}"
            
            # Parse JSON
            try:
                citations = json.loads(json_text)
                if not isinstance(citations, list):
                    return None, "AI response is not a JSON array"
                
                # Validate structure
                valid_citations = []
                for citation in citations:
                    if isinstance(citation, dict) and 'title' in citation and 'author' in citation:
                        valid_citations.append({
                            'title': citation['title'].strip(),
                            'author': citation['author'].strip()
                        })
                
                return valid_citations, None
                
            except json.JSONDecodeError as e:
                return None, f"Failed to parse AI response as JSON: {str(e)}"
            
        except Exception as e:
            return None, f"Error parsing bibliography with AI: {str(e)}"
    
    def cross_check_with_library(self, bib_list: List[Dict]) -> Tuple[Optional[List[Dict]], Optional[str]]:
        """
        Cross-checks parsed bibliography against the library database using improved fuzzy matching.
        
        Args:
            bib_list: List of citations with 'title' and 'author' fields
            
        Returns:
            Tuple of (enriched citation list, error message)
        """
        try:
            from fuzzy_book_matcher import FuzzyBookMatcher
            
            # Initialize matcher with threshold
            matcher = FuzzyBookMatcher(self.db_file, threshold=0.75, debug=False)
            
            # Match all citations
            results = matcher.batch_match(bib_list)
            
            # Build enriched citation list
            enriched_list = []
            for i, result in enumerate(results):
                citation = bib_list[i]
                enriched_citation = {
                    'title': citation.get('title', ''),
                    'author': citation.get('author', ''),
                    'status': 'owned' if result['found'] else 'missing'
                }
                
                if result['found']:
                    enriched_citation['match'] = result['match']
                
                enriched_list.append(enriched_citation)
            
            return enriched_list, None
            
        except Exception as e:
            return None, f"Error cross-checking with library: {str(e)}"
    
    def scan_book(self, book_id: int) -> Dict:
        """
        Complete bibliography scan workflow.
        
        Args:
            book_id: Database ID of the book
            
        Returns:
            Dictionary with scan results and statistics
        """
        result = {
            'success': False,
            'book_id': book_id,
            'error': None
        }
        
        # Step 1: Find bibliography pages
        bib_pages, error = self.find_bib_pages(book_id)
        if error:
            result['error'] = error
            return result
        
        result['bib_pages'] = bib_pages
        
        # Step 2: Parse with AI
        citations, error = self.parse_bib_with_ai(book_id, bib_pages)
        if error:
            result['error'] = error
            return result
        
        # Step 3: Cross-check with library
        enriched_citations, error = self.cross_check_with_library(citations)
        if error:
            result['error'] = error
            return result
        
        result['citations'] = enriched_citations
        
        # Calculate statistics
        total = len(enriched_citations)
        owned = sum(1 for c in enriched_citations if c['status'] == 'owned')
        missing = total - owned
        
        result['stats'] = {
            'total': total,
            'owned': owned,
            'missing': missing
        }
        
        result['success'] = True
        return result


if __name__ == "__main__":
    # Simple CLI for testing
    import argparse
    
    parser = argparse.ArgumentParser(description="Bibliography Hunter - Extract and analyze book bibliographies")
    parser.add_argument("book_id", type=int, help="Database ID of the book to scan")
    args = parser.parse_args()
    
    hunter = BibHunter()
    result = hunter.scan_book(args.book_id)
    
    print(json.dumps(result, indent=2))
