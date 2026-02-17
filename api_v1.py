from flask import Blueprint, request, jsonify, send_from_directory, current_app, render_template, send_file
import sqlite3
import shutil
import hashlib
import subprocess
import os
import sys
import traceback
from pathlib import Path
from pathlib import Path
import datetime
import datetime
import time
import re

from config import DB_FILE, LIBRARY_ROOT, OBSIDIAN_INBOX, CONVERTED_NOTES_DIR, parent_dir

# New Imports for Features
from search import search, get_book_details, get_similar_books
from book_ingestor import BookIngestor
import sqlite3

# Existing Logic Imports (from parent dir, enabled by config.py sys.path)
from search import search, search_books_semantic, search_books_fts
from bibgen import generate_bibtex_key, generate_bibtex
import converter
import bib_hunter
import bib_extractor
import json

api_v1 = Blueprint('api_v1', __name__)

# --- 1. Search & Discovery ---

@api_v1.route('/search', methods=['GET'])
def search_endpoint():
    query = request.args.get('q', '')
    limit = request.args.get('limit', 20, type=int)
    page = request.args.get('page', 1, type=int)
    
    # Priority: Explicit offset > Page-based offset
    offset = request.args.get('offset', type=int)
    if offset is None:
        offset = (page - 1) * limit
    
    use_fts = request.args.get('fts') == 'true'
    use_vector = request.args.get('vec') == 'true'
    use_translate = request.args.get('trans') == 'true'
    use_rerank = request.args.get('rank') == 'true'
    field = request.args.get('field', 'all')
    
    if not query:
        return jsonify({'results': [], 'total_count': 0, 'page': page})
    
    try:
        # Fallback to Metadata Search if no flags are provided
        if not use_fts and not use_vector:
            # Metadata Search (SQL LIKE)
            # This is fast and uses no external API calls
            from search import search_books
            results = search_books(query, limit=limit, offset=offset, field=field)
            total_count = len(results) # Approximate for simple search (or implement count query)
            expanded_query = None
            
            # Convert tuple results to dicts for JSON response
            # search_books returns list of tuples: (id, title, author, path, isbn, publisher, year)
            dict_results = []
            for r in results:
                dict_results.append({
                    'type': 'book',
                    'id': r[0],
                    'title': r[1],
                    'author': r[2],
                    'path': r[3],
                    'isbn': r[4],
                    'publisher': r[5],
                    'year': r[6]
                })
            results = dict_results

        else:
            # Advanced Search (Semantic + FTS)
            search_data = search(
                query, 
                limit=limit,
                offset=offset,
                use_fts=use_fts,
                use_vector=use_vector,
                use_translate=use_translate,
                use_rerank=use_rerank,
                field=field
            )
            results = search_data['results']
            total_count = search_data['total_count']
            expanded_query = search_data['expanded_query']
            
    except Exception as e:
        print(f"Search API Error: {e}", file=sys.stderr)
        return jsonify({'error': str(e)}), 500
    
    json_results = []
    for item in results:
        item_type = item.get('type', 'book')
        if item_type == 'book':
            # Enrich with BibTeX
            filename = Path(item['path']).name if item.get('path') else "unknown"
            bib_key = generate_bibtex_key(item['author'], item['title'])
            bg_entry = generate_bibtex((item['title'], item['author'], item['path'], filename))
            
            # Simple template replacement cleanup
            if item.get('year'):
                 bg_entry = bg_entry.replace('year      = {20XX}', f'year      = {{{item["year"]}}}')
            if item.get('publisher'):
                 bg_entry = bg_entry.replace('publisher = {Unknown}', f'publisher = {{{item["publisher"]}}}')
            
            item.update({
                'bib_key': bib_key,
                'bibtex': bg_entry,
                'cover_url': f'/static/thumbnails/{item["id"]}/page_1.png'
            })
        json_results.append(item)
        
    return jsonify({
        'results': json_results,
        'total_count': total_count,
        'page': page,
        'expanded_query': expanded_query
    })

def parse_page_range(pages_str, max_pages):
    """
    Parses a page range string into a list of integers.
    Supports: "10", "10-15", "10,12,15", "10-12,15".
    """
    if not pages_str:
        return []
    
    pages = set()
    parts = str(pages_str).split(',')
    for part in parts:
        part = part.strip()
        if '-' in part:
            try:
                start, end = map(int, part.split('-'))
                # Safety limit: clamp to max_pages and prevent massive ranges
                start = max(1, start)
                end = min(max_pages, end)
                if start <= end:
                    # Hard limit to 100 pages to prevent memory issues
                    if end - start > 100:
                        end = start + 100
                    for p in range(start, end + 1):
                        pages.add(p)
            except ValueError:
                continue
        else:
            try:
                p = int(part)
                if 1 <= p <= max_pages:
                    pages.add(p)
            except ValueError:
                continue
    return sorted(list(pages))

@api_v1.route('/books/<int:book_id>/deep-index', methods=['POST'])
def trigger_deep_indexing(book_id):
    """Triggers fine-grained (page-by-page) FTS indexing for a book."""
    try:
        from indexer import deep_index_book
        success, message = deep_index_book(book_id)
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'error': message}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/books/<int:book_id>/search', methods=['GET'])
def search_within_book_endpoint(book_id):
    """Searches for a query within a specific book (using page-level indexing)."""
    query = request.args.get('q', '')
    limit = request.args.get('limit', 50, type=int)
    
    if not query:
        return jsonify({'error': 'Missing query parameter (q)'}), 400
        
    try:
        from search import search_within_book
        matches, is_deep = search_within_book(book_id, query, limit=limit)
        return jsonify({
            'book_id': book_id,
            'query': query,
            'matches': matches,
            'is_deep_indexed': is_deep
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/books/<int:book_id>/reindex/index', methods=['POST'])
def trigger_index_reconstruction(book_id):
    """Triggers AI-driven Index (back of book) reconstruction."""
    try:
        from index_backfill import extract_candidate_pages, clean_index_with_gemini, validate_content, update_db
        import fitz
        
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("SELECT path, title FROM books WHERE id = ?", (book_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return jsonify({'error': 'Book not found'}), 404
            
        rel_path, title = row
        abs_path = (LIBRARY_ROOT / rel_path).resolve()
        
        if not abs_path.exists():
            return jsonify({'error': 'File not found'}), 404
            
        doc = fitz.open(abs_path)
        raw_text, page_count = extract_candidate_pages(doc)
        doc.close()
        
        if not raw_text:
            return jsonify({'success': False, 'error': 'No index pages detected via heuristics.'}), 400
            
        clean_text = clean_index_with_gemini(raw_text, title)
        
        if clean_text == "NOT_INDEX":
            return jsonify({'success': False, 'error': 'AI rejected content as not an index.'}), 400
            
        if not clean_text:
            return jsonify({'success': False, 'error': 'AI failed to process index.'}), 500
            
        is_valid, reason = validate_content(clean_text)
        if is_valid:
            if update_db(book_id, clean_text):
                return jsonify({'success': True, 'message': f'Index updated ({len(clean_text)} characters)'})
            else:
                return jsonify({'success': False, 'error': 'Database update failed'}), 500
        else:
            return jsonify({'success': False, 'error': f'Validation failed: {reason}'}), 400
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- 2. Tools & Utilities ---

@api_v1.route('/books/<int:book_id>', methods=['GET'])
def get_book_details(book_id):
    """Returns detailed metadata for a specific book."""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, title, author, path, isbn, publisher, year, summary, 
                   level, description, tags, index_text, doi, toc_json
            FROM books WHERE id = ?
        """, (book_id,))
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return jsonify({'error': 'Book not found'}), 404
            
        # Try to extract page_offset from toc_json if available
        page_offset = 0
        if row[13]:
            try:
                toc_data = json.loads(row[13])
                for item in toc_data:
                    if isinstance(item, dict) and item.get('pdf_page') and item.get('page'):
                        page_offset = int(item['pdf_page']) - int(item['page'])
                        break
            except: pass

        # Check if deep-indexed
        cursor.execute("SELECT book_id FROM deep_indexed_books WHERE book_id = ?", (book_id,))
        is_deep = bool(cursor.fetchone())
        
        conn.close()
        
        rel_path = row[3]
        abs_path = (LIBRARY_ROOT / rel_path).resolve()
        
        page_count = 0
        if abs_path.exists() and abs_path.suffix.lower() == '.pdf':
            try:
                import pypdf
                reader = pypdf.PdfReader(abs_path)
                page_count = len(reader.pages)
            except Exception as e:
                print(f"Error reading page count: {e}")

        # Get similar books
        similar = []
        try:
            from search import get_similar_books
            similar_raw = get_similar_books(book_id, limit=5)
            similar = [{'id': r[0], 'title': r[1], 'author': r[2]} for r in similar_raw]
        except Exception:
            pass

        return jsonify({
            'id': row[0],
            'title': row[1],
            'author': row[2],
            'path': row[3],
            'isbn': row[4],
            'publisher': row[5],
            'year': row[6],
            'summary': row[7],
            'level': row[8],
            'description': row[9],
            'tags': row[10],
            'doi': row[12],
            'page_count': page_count,
            'page_offset': page_offset,
            'has_index': bool(row[11]),
            'is_deep_indexed': is_deep,
            'similar_books': similar
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/tools/pdf-to-text', methods=['POST'])
def pdf_to_text_tool():
    """Extracts raw text from a PDF range without AI processing."""
    data = request.json
    book_id = data.get('book_id')
    pages_str = data.get("pages") or data.get("page")
    
    if not book_id or not pages_str:
        return jsonify({'error': 'book_id and pages are required'}), 400
        
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("SELECT path FROM books WHERE id = ?", (book_id,))
        res = cursor.fetchone()
        conn.close()
        
        if not res: return jsonify({'error': 'Book not found'}), 404
        rel_path = res[0]
        abs_path = (LIBRARY_ROOT / rel_path).resolve()
        
        if not abs_path.exists(): return jsonify({'error': 'File missing'}), 404
        
        import pypdf
        reader = pypdf.PdfReader(abs_path)
        total_pages = len(reader.pages)
        
        target_pages = parse_page_range(pages_str, total_pages)
        if not target_pages:
            return jsonify({'error': 'Invalid page range'}), 400
            
        full_text = ""
        for p in target_pages:
            try:
                page_text = reader.pages[p-1].extract_text()
                full_text += f"\n--- PDF Page {p} ---\n{page_text}\n"
            except Exception as e:
                full_text += f"\n--- PDF Page {p} (Error: {e}) ---\n"
                
        return jsonify({
            'success': True,
            'book_id': book_id,
            'pages': target_pages,
            'text': full_text
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/tools/check-wishlist', methods=['POST'])
def check_wishlist_tool():
    """Bulk checks a list of books against the library using improved fuzzy matching."""
    try:
        from fuzzy_book_matcher import FuzzyBookMatcher
        
        data = request.json
        lines = data.get('lines', [])
        
        if not lines:
            return jsonify({'found': [], 'missing': []})
        
        # Parse wishlist lines into book dicts
        books = []
        original_lines = []
        
        for line in lines[:500]:  # Limit to 500 lines
            original_line = line.strip()
            if not original_line:
                continue
            
            original_lines.append(original_line)
            
            # Parse "Title ; Author" or just "Title"
            parts = [p.strip() for p in original_line.split(';') if p.strip()]
            
            if len(parts) >= 2:
                books.append({'title': parts[0], 'author': parts[1]})
            else:
                books.append({'title': parts[0], 'author': ''})
        
        # Use fuzzy matcher
        matcher = FuzzyBookMatcher(DB_FILE, threshold=0.75, debug=False)
        results = matcher.batch_match(books)
        
        # Build response
        found = []
        missing = []
        
        for i, result in enumerate(results):
            if result['found']:
                found.append(result['match'])
            else:
                missing.append(original_lines[i])
        
        return jsonify({
            'found': found,
            'missing': missing
        })
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


@api_v1.route('/tools/pdf-to-note', methods=['POST'])
def convert_tool():
    """Converts one or more PDF pages to notes with AI structuring."""
    data = request.json
    book_id = data.get('book_id')
    pages_input = data.get("pages") or data.get("page") # Supports int or string range
    
    if not book_id or not pages_input:
        return jsonify({'error': 'book_id and pages are required'}), 400
        
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("SELECT path, title, author FROM books WHERE id = ?", (book_id,))
        res = cursor.fetchone()
        conn.close()
        
        if not res: return jsonify({'error': 'Book not found'}), 404
        rel_path, title, author = res
        abs_path = (LIBRARY_ROOT / rel_path).resolve()
        
        import pypdf
        reader = pypdf.PdfReader(abs_path)
        total_pages = len(reader.pages)
        
        # Parse range
        target_pages = parse_page_range(str(pages_input), total_pages)
        if not target_pages:
            return jsonify({'error': 'Invalid page range'}), 400
            
        combined_markdown = ""
        combined_latex = ""
        
        for page_num in target_pages:
            # Clean up title (remove newlines and extra spaces)
            title = " ".join(title.split())
            
            # Use converter to get content (one by one for now to avoid massive prompt bloat)
            result_data, error = converter.convert_page(str(abs_path), page_num)
            
            if error:
                combined_markdown += f"\n\n> [Error extracting Page {page_num}: {error}]\n\n"
                continue
                
            combined_markdown += f"\n\n## Page {page_num}\n\n" + result_data.get('markdown', '')
            combined_latex += f"\n% --- Page {page_num} ---\n" + result_data.get('latex', '')
        
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        
        if error: return jsonify({'error': error}), 500
            
        markdown_content = result_data.get('markdown', '')
        latex_content = result_data.get('latex', '')
        
        # Prepend header
        page_ref = f"p. {target_pages[0]}" if len(target_pages) == 1 else f"pp. {target_pages[0]}-{target_pages[-1]}"
        header = f"---\ntitle: Note from {title} ({page_ref})\nauthor: {author}\ndate: {timestamp}\ntags: [auto-note, {title}]\n---\n\n"
        full_markdown = header + combined_markdown
        
        # Save locally
        if not CONVERTED_NOTES_DIR.exists(): CONVERTED_NOTES_DIR.mkdir()
            
        safe_title = "".join(x for x in title if x.isalnum() or x in " -_")[:50]
        filename_base = f"{safe_title}_p{target_pages[0]}"
        if len(target_pages) > 1: filename_base += f"-{target_pages[-1]}"
        
        md_filename = f"{filename_base}.md"
        tex_filename = f"{filename_base}.tex"
        
        with open(CONVERTED_NOTES_DIR / md_filename, 'w', encoding='utf-8') as f: f.write(full_markdown)
        with open(CONVERTED_NOTES_DIR / tex_filename, 'w', encoding='utf-8') as f: f.write(combined_latex)
        
        # Generate recommendations for metadata using simpler keyword search
        recommendations = []
        try:
            # Extract key terms from the markdown content for search
            import re
            # Get first 500 chars and extract mathematical terms
            sample_text = markdown_content[:500]
            # Simple keyword extraction - look for capitalized words and math terms
            keywords = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', sample_text)
            search_query = ' '.join(keywords[:5]) if keywords else title
            
            # Use FTS search instead of semantic search
            conn = sqlite3.connect(DB_FILE, timeout=30)
            cursor = conn.cursor()
            clean_query = search_query.replace('"', '""')
            cursor.execute("""
                SELECT b.id, b.title, b.author 
                FROM books_fts f 
                JOIN books b ON f.rowid = b.id 
                WHERE books_fts MATCH ? 
                ORDER BY rank 
                LIMIT 5
            """, (clean_query,))
            results = cursor.fetchall()
            conn.close()
            
            recommendations = [
                {
                    'id': r[0],
                    'title': r[1],
                    'author': r[2],
                    'score': 0.8  # Dummy score for FTS results
                }
                for r in results
            ]
        except Exception as e:
            print(f"Recommendation Error: {e}")
            
        # Save metadata JSON
        metadata = {
            'title': f"Note from {title} ({page_ref})",
            'original_filename': filename_base,
            'created': timestamp,
            'tags': ['auto-note', title],
            'recommendations': recommendations,
            'pages': target_pages
        }
        json_filename = f"{filename_base}.json"
        with open(CONVERTED_NOTES_DIR / json_filename, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2)
        
        # Extract PDF pages from source PDF
        try:
            from pypdf import PdfReader, PdfWriter
            pdf_filename = f"{filename_base}.pdf"
            
            reader = PdfReader(abs_path)
            writer = PdfWriter()
            
            for p_num in target_pages:
                if p_num <= len(reader.pages):
                    writer.add_page(reader.pages[p_num - 1])
            
            if len(writer.pages) > 0:
                with open(CONVERTED_NOTES_DIR / pdf_filename, 'wb') as output_pdf:
                    writer.write(output_pdf)
                print(f"Extracted PDF pages {target_pages} to {pdf_filename}")
        except Exception as e:
            print(f"PDF extraction error: {e}")
        
        # Obsidian Sync
        if os.path.exists(OBSIDIAN_INBOX):
            try:
                import shutil
                shutil.copy2(CONVERTED_NOTES_DIR / md_filename, os.path.join(OBSIDIAN_INBOX, md_filename))
            except Exception as e:
                print(f"Bridge Error: {e}")
                
        return jsonify({
            'success': True,
            'message': f'Note created: {md_filename}',
            'content': full_markdown,
            'filename': md_filename
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/open-external', methods=['GET'])
def open_external_tool():
    """Opens a file in the local OS (Linux)."""
    filepath = request.args.get('path', '')
    if not filepath: return jsonify({'error': 'Missing path'}), 400
        
    try:
        abs_path = (LIBRARY_ROOT / filepath).resolve()
        # Security check
        if LIBRARY_ROOT.resolve() not in abs_path.parents and abs_path != LIBRARY_ROOT.resolve():
             return jsonify({'error': 'Access denied'}), 403
             
        if not abs_path.exists(): return jsonify({'error': 'File not found'}), 404
            
        subprocess.Popen(['xdg-open', str(abs_path)], start_new_session=True)
        return jsonify({'success': True, 'message': 'Opened in external viewer'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/tools/bib-scan', methods=['POST'])
def bib_scan_tool():
    """Scans a book's bibliography, extracts pages, and shows results page."""
    try:
        # Accept both JSON and form data
        if request.is_json:
            data = request.json
        else:
            data = request.form
        
        book_id = data.get('book_id')
        
        if not book_id:
            return jsonify({'error': 'book_id is required'}), 400
        
        # Validate book exists
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, author, path FROM books WHERE id = ?", (book_id,))
        book = cursor.fetchone()
        conn.close()
        
        if not book:
            return jsonify({'error': f'Book with ID {book_id} not found'}), 404
        
        # Run bibliography scan
        hunter = bib_hunter.BibHunter(DB_FILE)
        result = hunter.scan_book(book_id)
        
        if not result['success']:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Unknown error occurred')
            }), 500
        
        # Extract bibliography pages as separate PDF
        bib_pages = result.get('bib_pages', [])
        print(f"[DEBUG] bib_pages={bib_pages}, book path={book[3]}", flush=True)
        
        extracted_pdf_path = None
        extracted_pdf_filename = None
        
        if bib_pages and book[3]:  # book[3] is path
            print(f"[DEBUG] Calling extract_bib_pages for {book[1]}", flush=True)
            pdf_path, error = bib_extractor.extract_bib_pages(book[3], book_id, book[1], bib_pages)
            print(f"[DEBUG] Extraction result: path={pdf_path}, error={error}", flush=True)
            if pdf_path and not error:
                extracted_pdf_path = pdf_path
                extracted_pdf_filename = Path(pdf_path).name
        
        # Render results page
        return render_template('bib_results.html',
            book_id=book_id,
            book_title=book[1],
            book_author=book[2],
            bib_pages=bib_pages,
            citations=result.get('citations', []),
            stats=result.get('stats', {}),
            extracted_pdf_path=extracted_pdf_path,
            extracted_pdf_filename=extracted_pdf_filename
        )
        
    except Exception as e:
         return jsonify({'success': False, 'error': str(e)}), 500

@api_v1.route('/bib-extracts/check-citation', methods=['POST'])
def check_citation():
    """Deep checks a citation against the library."""
    try:
        from fuzzy_book_matcher import FuzzyBookMatcher
        
        data = request.json
        title = data.get('title')
        author = data.get('author')
        
        matcher = FuzzyBookMatcher(DB_FILE, debug=True)
        match = matcher.deep_match(title, author)
        
        if match:
             return jsonify({'found': True, 'match': match})
        else:
             return jsonify({'found': False})
             
    except Exception as e:
        return jsonify({'found': False, 'error': str(e)}), 500

@api_v1.route('/books/<int:book_id>/reindex', methods=['POST'])
def reindex_book(book_id):
    """Triggers AI-powered re-indexing for a book."""
    try:
        from book_ingestor import BookIngestor
        
        # Get options
        if request.is_json:
            data = request.json
        else:
            data = request.form
            
        ai_care_val = data.get('ai_care', True)
        if isinstance(ai_care_val, str):
             ai_care = ai_care_val.lower() == 'true'
        else:
             ai_care = bool(ai_care_val)
        
        # Initialize ingestor in execute mode
        ingestor = BookIngestor(execute=True)
        result = ingestor.reprocess_book(book_id, ai_care=ai_care)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_v1.route('/books/<int:book_id>/reindex/preview', methods=['POST'])
def preview_reindex_book(book_id):
    """Generates a metadata proposal without saving it."""
    try:
        from book_ingestor import BookIngestor
        data = request.json or {}
        ai_care = data.get('ai_care', True)
        ingestor = BookIngestor(execute=True)
        result = ingestor.preview_reindex(book_id, ai_care=ai_care)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@api_v1.route('/books/<int:book_id>/metadata', methods=['PATCH'])
def update_book_metadata(book_id):
    """Manually updates book metadata fields."""
    try:
        data = request.json
        fields = ['title', 'author', 'publisher', 'year', 'isbn', 'msc_class', 'summary', 'tags', 'description', 'level', 'audience']
        
        updates = []
        params = []
        for f in fields:
            if f in data:
                updates.append(f"{f} = ?")
                params.append(data[f])
        
        if not updates:
            return jsonify({'error': 'No fields to update'}), 400
            
        # Handle ToC update if provided (usually from AI proposal)
        if 'toc' in data:
            ingestor = None
            try:
                from book_ingestor import BookIngestor
                ingestor = BookIngestor(execute=True)
                ingestor.sync_chapters(book_id, data['toc'], page_offset=data.get('page_offset', 0))
            except Exception as e:
                # Log but don't fail the whole metadata update
                print(f"Failed to sync chapters during metadata update: {e}")
            finally:
                if ingestor:
                    ingestor.close()

        import time
        params.append(time.time())
        params.append(book_id)
        
        query = f"UPDATE books SET {', '.join(updates)}, last_modified = ? WHERE id = ?"
        
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute(query, params)
        
        # --- NEW: Explicit FTS Synchronization ---
        try:
            # 1. Remove old entry from FTS
            cursor.execute("DELETE FROM books_fts WHERE rowid = ?", (book_id,))
            # 2. Re-insert fresh data from the updated books table
            cursor.execute("""
                INSERT INTO books_fts (rowid, title, author, index_content)
                SELECT id, title, author, index_text FROM books WHERE id = ?
            """, (book_id,))
        except Exception as fts_err:
            print(f"FTS Sync Warning: {fts_err}")
        # ------------------------------------------

        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Metadata updated successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
@api_v1.route('/bib-extracts/<filename>', methods=['GET'])
def serve_bib_extract(filename):
    """Serve extracted bibliography PDF files."""
    try:
        # Use absolute path relative to Docker container root
        extract_dir = Path('/library/mathstudio/bib_extracts')
        file_path = extract_dir / filename
        
        if not file_path.exists():
            # Fallback: check relative to current dir just in case
            extract_dir = Path('bib_extracts').resolve()
            file_path = extract_dir / filename
            
        if not file_path.exists():
             return jsonify({'error': f'File not found at {file_path}'}), 404
        
        return send_file(str(file_path), mimetype='application/pdf')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- 3. Content Delivery ---

@api_v1.route('/books/<int:book_id>/download', methods=['GET'])
def download_book(book_id):
    """Serves the raw book file, converting DjVu to PDF if needed."""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("SELECT path FROM books WHERE id = ?", (book_id,))
        res = cursor.fetchone()
        conn.close()
        
        if not res: return jsonify({'error': 'Book not found'}), 404
        
        rel_path = res[0]
        abs_path = (LIBRARY_ROOT / rel_path).resolve()
        
        if not abs_path.exists(): return jsonify({'error': 'File missing on server'}), 404
            
        # PDF: Serve directly
        if abs_path.suffix.lower() == '.pdf':
            return send_from_directory(abs_path.parent, abs_path.name)
            
        # DjVu: Convert on fly
        if abs_path.suffix.lower() == '.djvu':
            cache_dir = Path(current_app.root_path) / "static/cache/pdf"
            if not cache_dir.exists(): cache_dir.mkdir(parents=True)
                
            pdf_filename = f"{book_id}.pdf"
            pdf_path = cache_dir / pdf_filename
            
            if not pdf_path.exists():
                subprocess.run(['ddjvu', '-format=pdf', str(abs_path), str(pdf_path)], check=True)
            
            return send_from_directory(cache_dir, pdf_filename)
            
        return jsonify({'error': 'Unsupported format'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- 4. Admin & Ingestion ---

@api_v1.route('/admin/ingest', methods=['POST'])
def admin_ingest():
    """Triggers the book ingestion pipeline."""
    data = request.json or {}
    dry_run = data.get('dry_run', True)
    # Defaulting to dry-run for safety via API
    
    cmd = ["python3", str(parent_dir / "book_ingestor.py")]
    if dry_run:
        cmd.append("--dry-run")
    else:
        cmd.append("--execute")
        
    try:
        # Run and capture output
        result = subprocess.run(cmd, cwd=str(parent_dir), capture_output=True, text=True, timeout=1200)
        return jsonify({
            'success': result.returncode == 0,
            'dry_run': dry_run,
            'stdout': result.stdout,
            'stderr': result.stderr
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/admin/ingest/report', methods=['GET'])
def admin_ingest_report():
    """Returns the current ingestion status report."""
    try:
        cmd = ["python3", str(parent_dir / "ingestion_report.py")]
        result = subprocess.run(cmd, cwd=str(parent_dir), capture_output=True, text=True, timeout=60)
        return jsonify({
            'success': result.returncode == 0,
            'stdout': result.stdout,
            'stderr': result.stderr
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/admin/indexer', methods=['POST'])
def admin_indexer():
    """Triggers the indexer (FTS/Vector rebuild)."""
    data = request.json or {}
    force = data.get('force', False)
    
    cmd = ["python3", str(parent_dir / "indexer.py")]
    if force: cmd.append("--force")
        
    try:
        result = subprocess.run(cmd, cwd=str(parent_dir), capture_output=True, text=True, timeout=600)
        return jsonify({
            'success': result.returncode == 0,
            'stdout': result.stdout,
            'stderr': result.stderr
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/admin/stats', methods=['GET'])
def admin_stats():
    """Returns database statistics."""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        
        # 1. Basic Counts
        cursor.execute("SELECT COUNT(*) FROM books")
        total_books = cursor.fetchone()[0]
        
        cursor.execute("SELECT SUM(size_bytes) FROM books")
        total_size = cursor.fetchone()[0] or 0
        
        # 2. Category Breakdown
        cursor.execute("SELECT directory, COUNT(*) FROM books GROUP BY directory ORDER BY COUNT(*) DESC")
        categories = cursor.fetchall()
        
        # 3. Newest Books
        cursor.execute("SELECT id, title, author, last_modified FROM books ORDER BY last_modified DESC LIMIT 5")
        newest = [{'id': r[0], 'title': r[1], 'author': r[2]} for r in cursor.fetchall()]
        
        conn.close()
        
        return jsonify({
            'total_books': total_books,
            'total_size_gb': round(total_size / (1024**3), 2),
            'categories': [{'name': c[0], 'count': c[1]} for c in categories],
            'newest': newest
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/admin/sanity/check', methods=['POST'])
def admin_sanity_check():
    """Runs the database sanity check."""
    try:
        cmd = ["python3", str(parent_dir / "db_sanity.py")]
        result = subprocess.run(cmd, cwd=str(parent_dir), capture_output=True, text=True, timeout=300)
        return jsonify({
            'success': result.returncode == 0,
            'stdout': result.stdout,
            'stderr': result.stderr
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/admin/sanity/fix', methods=['POST'])
def admin_sanity_fix():
    """Runs the database sanity fix."""
    try:
        cmd = ["python3", str(parent_dir / "db_sanity.py"), "--fix"]
        result = subprocess.run(cmd, cwd=str(parent_dir), capture_output=True, text=True, timeout=300)
        return jsonify({
            'success': result.returncode == 0,
            'stdout': result.stdout,
            'stderr': result.stderr
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/admin/logs', methods=['GET'])
def admin_logs():
    """Retrieves the last 100 lines of the process log."""
    log_file = parent_dir / "process_notes.log"
    try:
        if not log_file.exists():
            return jsonify({'logs': 'Log file not found.'})
            
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            last_lines = "".join(lines[-100:])
            
        return jsonify({'logs': last_lines})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- 5. Bookmarks & Structure ---

@api_v1.route('/books/<int:book_id>/toc', methods=['GET'])
def get_book_toc_endpoint(book_id):
    """Returns the structured Table of Contents for a book."""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("SELECT toc_json FROM books WHERE id = ?", (book_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return jsonify({'error': 'Book not found'}), 404
            
        toc_json = row[0]
        if not toc_json:
             return jsonify({'toc': []}) # Return empty list if no TOC
             
        return jsonify({'toc': json.loads(toc_json)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/bookmarks', methods=['POST'])
def create_bookmark():
    """Create a new bookmark."""
    try:
        data = request.json
        book_id = data.get('book_id')
        page_range = data.get('page_range')
        tags = data.get('tags', '')
        notes = data.get('notes', '')
        
        if not book_id:
            return jsonify({'error': 'book_id is required'}), 400
            
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO bookmarks (book_id, page_range, tags, notes) VALUES (?, ?, ?, ?)",
            (book_id, page_range, tags, notes)
        )
        conn.commit()
        new_id = cursor.lastrowid
        conn.close()
        return jsonify({'success': True, 'id': new_id})
    except Exception as e:
         return jsonify({'error': str(e)}), 500

@api_v1.route('/bookmarks', methods=['GET'])
def list_bookmarks():
    """List bookmarks, optionally filtered."""
    book_id = request.args.get('book_id')
    tag = request.args.get('tag')
    
    query = "SELECT b.id, b.book_id, bk.title, b.page_range, b.tags, b.notes, b.created_at FROM bookmarks b JOIN books bk ON b.book_id = bk.id WHERE 1=1"
    params = []
    
    if book_id:
        query += " AND b.book_id = ?"
        params.append(book_id)
    if tag:
        query += " AND b.tags LIKE ?"
        params.append(f"%{tag}%")
        
    query += " ORDER BY b.created_at DESC"
    
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        results = []
        for r in rows:
            results.append({
                'id': r[0],
                'book_id': r[1],
                'book_title': r[2],
                'page_range': r[3],
                'tags': r[4],
                'notes': r[5],
                'created_at': r[6]
            })
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/bookmarks/<int:bookmark_id>', methods=['DELETE'])
def delete_bookmark(bookmark_id):
    """Delete a bookmark."""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/books/<int:book_id>/replace', methods=['POST'])
def replace_book_file(book_id):
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
        
    new_file = request.files['file']
    if new_file.filename == '':
        return jsonify({'error': 'Empty filename'}), 400

    try:
        # 1. Get existing record
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute("SELECT path, title, author, page_count, file_hash FROM books WHERE id = ?", (book_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return jsonify({'error': 'Book not found'}), 404
            
        old_rel_path, old_title, old_author, old_page_count, old_hash = row
        old_abs_path = (LIBRARY_ROOT / old_rel_path).resolve()
        
        # 2. Save new file to temp
        temp_dir = Path("temp_uploads")
        temp_dir.mkdir(exist_ok=True)
        temp_path = temp_dir / f"replace_{book_id}_{new_file.filename}"
        new_file.save(str(temp_path))
        
        # 3. Heuristics Check
        ingestor = BookIngestor(dry_run=True)
        new_structure = ingestor.extract_structure(temp_path)
        
        if not new_structure:
            if temp_path.exists(): os.remove(temp_path)
            conn.close()
            return jsonify({'error': 'Could not read new file structure (Extraction failed)'}), 400
            
        new_page_count = new_structure.get('page_count', 0)
        
        # Heuristic 1: Page Count (allow 10% deviance for better versions)
        if old_page_count and old_page_count > 0:
            diff = abs(new_page_count - old_page_count)
            if diff / old_page_count > 0.10:
                if temp_path.exists(): os.remove(temp_path)
                conn.close()
                return jsonify({
                    'error': f'Page count mismatch. Old: {old_page_count}, New: {new_page_count}. This looks like a different book.'
                }), 400

        # Heuristic 2: Hash Check
        new_hash = ingestor.calculate_hash(temp_path)
        if new_hash == old_hash:
            if temp_path.exists(): os.remove(temp_path)
            conn.close()
            return jsonify({'error': 'This is the exact same file.'}), 400

        # 4. Perform Exchange
        archive_dir = LIBRARY_ROOT / "_Admin" / "Archive" / "Replaced"
        archive_dir.mkdir(parents=True, exist_ok=True)
        
        # Backup old
        if old_abs_path.exists():
            shutil.move(str(old_abs_path), str(archive_dir / f"{book_id}_{old_abs_path.name}"))
        
        # Move new into place (Keep path but update ext if needed)
        final_rel_path = Path(old_rel_path).with_suffix(temp_path.suffix.lower())
        final_abs_path = LIBRARY_ROOT / final_rel_path
        shutil.move(str(temp_path), str(final_abs_path))
        
        # 5. Update DB (Technical fields only)
        cursor.execute("""
            UPDATE books SET 
                path = ?, 
                file_hash = ?, 
                size_bytes = ?, 
                page_count = ?,
                last_modified = ?
            WHERE id = ?
        """, (str(final_rel_path), new_hash, final_abs_path.stat().st_size, new_page_count, time.time(), book_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': 'File replaced successfully. Original metadata preserved.',
            'new_path': str(final_rel_path)
        })
        
    except Exception as e:
        import traceback
        return jsonify({'error': f"Internal error: {str(e)}", 'trace': traceback.format_exc()}), 500

@api_v1.route('/books/<int:book_id>', methods=['DELETE'])
def delete_book(book_id):
    """Safely deletes a book: moves file to archive and removes DB entry."""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        
        # 1. Get book path
        cursor.execute("SELECT path, title FROM books WHERE id = ?", (book_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return jsonify({'error': 'Book not found'}), 404
            
        rel_path, title = row
        abs_path = (LIBRARY_ROOT / rel_path).resolve()
        
        # 2. Archive the file
        archive_dir = LIBRARY_ROOT / "_Admin" / "Archive" / "Deleted"
        archive_dir.mkdir(parents=True, exist_ok=True)
        
        if abs_path.exists():
            dest_path = archive_dir / f"{book_id}_{abs_path.name}"
            import shutil
            shutil.move(str(abs_path), str(dest_path))
            print(f"[DELETE] Archived file to {dest_path}")
        
        # 3. Remove from Database
        cursor.execute("DELETE FROM books WHERE id = ?", (book_id,))
        # Also clean up FTS
        cursor.execute("DELETE FROM books_fts WHERE rowid = ?", (book_id,))
        # And bookmarks
        cursor.execute("DELETE FROM bookmarks WHERE book_id = ?", (book_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f"Book '{title}' deleted and archived successfully."})
        
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500
