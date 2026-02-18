from flask import Blueprint, request, jsonify, send_from_directory, current_app, render_template, send_file
import shutil
import subprocess
import os
import sys
import traceback
from pathlib import Path
import time
import json

from core.config import DB_FILE, LIBRARY_ROOT, OBSIDIAN_INBOX, CONVERTED_NOTES_DIR
from core.database import db
from services.search import search_service
from services.library import library_service
from services.note import note_service
from services.metadata import metadata_service
from services.bibliography import bibliography_service

# Legacy/Transition Imports
from core.utils import parse_page_range

api_v1 = Blueprint('api_v1', __name__)

# --- 1. Search & Discovery ---

@api_v1.route('/search', methods=['GET'])
def search_endpoint():
    query = request.args.get('q', '')
    limit = request.args.get('limit', 20, type=int)
    page = request.args.get('page', 1, type=int)
    offset = request.args.get('offset', (page - 1) * limit, type=int)
    
    use_fts = request.args.get('fts') == 'true'
    use_vector = request.args.get('vec') == 'true'
    use_translate = request.args.get('trans') == 'true'
    use_rerank = request.args.get('rank') == 'true'
    field = request.args.get('field', 'all')
    
    if not query:
        return jsonify({'results': [], 'total_count': 0, 'page': page})
    
    try:
        search_data = search_service.search(
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
        # Enrich with BibTeX
        bib_key = metadata_service.generate_bibtex_key(item['author'], item['title'])
        bg_entry = metadata_service.generate_bibtex(item['title'], item['author'], Path(item['path']).name, year=item.get('year'), publisher=item.get('publisher'))
        
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

@api_v1.route('/books/<int:book_id>/deep-index', methods=['POST'])
def trigger_deep_indexing(book_id):
    """Triggers fine-grained (page-by-page) FTS indexing for a book."""
    try:
        from services.indexer import indexer_service
        success, message = indexer_service.deep_index_book(book_id)
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
        matches, is_deep = search_service.search_within_book(book_id, query, limit=limit)
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
        from services.indexer import indexer_service
        success, message = indexer_service.reconstruct_index(book_id)
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'error': message}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- 2. Tools & Utilities ---

@api_v1.route('/books/<int:book_id>', methods=['GET'])
def get_book_details_endpoint(book_id):
    """Returns detailed metadata for a specific book."""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM books WHERE id = ?
            """, (book_id,))
            row = cursor.fetchone()
            
            if not row:
                return jsonify({'error': 'Book not found'}), 404
            
            # Check if deep-indexed
            cursor.execute("SELECT book_id FROM deep_indexed_books WHERE book_id = ?", (book_id,))
            is_deep = bool(cursor.fetchone())
        
        row_dict = dict(row)
        
        # Try to extract page_offset from toc_json
        page_offset = 0
        if row_dict.get('toc_json'):
            try:
                toc_data = json.loads(row_dict['toc_json'])
                for item in toc_data:
                    if isinstance(item, dict) and item.get('pdf_page') and item.get('page'):
                        page_offset = int(item['pdf_page']) - int(item['page'])
                        break
            except: pass

        abs_path = (LIBRARY_ROOT / row_dict['path']).resolve()
        
        page_count = row_dict.get('page_count') or 0
        if page_count == 0 and abs_path.exists() and abs_path.suffix.lower() == '.pdf':
            try:
                import pypdf
                reader = pypdf.PdfReader(abs_path)
                page_count = len(reader.pages)
            except: pass

        # Get similar books
        similar = []
        try:
            similar_raw = search_service.get_similar_books(book_id, limit=5)
            similar = [{'id': r[0], 'title': r[1], 'author': r[2]} for r in similar_raw]
        except: pass

        return jsonify({
            **row_dict,
            'page_count': page_count,
            'page_offset': page_offset,
            'has_index': bool(row_dict.get('index_text')),
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
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT path FROM books WHERE id = ?", (book_id,))
            res = cursor.fetchone()
        
        if not res: return jsonify({'error': 'Book not found'}), 404
        rel_path = res['path']
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
        from services.fuzzy_matcher import FuzzyBookMatcher
        
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
    pages_input = data.get("pages") or data.get("page")
    
    if not book_id or not pages_input:
        return jsonify({'error': 'book_id and pages are required'}), 400
        
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT path FROM books WHERE id = ?", (book_id,))
            res = cursor.fetchone()
            if not res: return jsonify({'error': 'Book not found'}), 404
            abs_path = (LIBRARY_ROOT / res['path']).resolve()

        import pypdf
        reader = pypdf.PdfReader(abs_path)
        total_pages = len(reader.pages)
        
        target_pages = parse_page_range(str(pages_input), total_pages)
        if not target_pages:
            return jsonify({'error': 'Invalid page range'}), 400
            
        result, error = note_service.create_note_from_pdf(book_id, target_pages)
        
        if error:
            return jsonify({'error': error}), 500
            
        return jsonify({
            'success': True,
            'message': f'Note created: {result["filename"]}',
            'content': result['content'],
            'filename': result['filename']
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
        data = request.json if request.is_json else request.form
        book_id = data.get('book_id')
        if not book_id: return jsonify({'error': 'book_id is required'}), 400
        
        result = bibliography_service.scan_book(int(book_id))
        if not result['success']:
            return jsonify({'success': False, 'error': result.get('error')}), 500
        
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT title, author, path FROM books WHERE id = ?", (book_id,))
            book = cursor.fetchone()

        extracted_pdf_filename = None
        if result.get('pages') and book['path']:
            from services.metadata import metadata_service # Actually should be in bibliography?
            # For now I'll use the existing bib_extractor if it still works or migrate it.
            # Actually, I migrated bib_hunter to bibliography_service.
            from services import bib_extractor
            pdf_path, error = bib_extractor.extract_bib_pages(book['path'], book_id, book['title'], result['pages'])
            if pdf_path and not error:
                extracted_pdf_filename = Path(pdf_path).name
        
        return render_template('bib_results.html',
            book_id=book_id,
            book_title=book['title'],
            book_author=book['author'],
            bib_pages=result.get('pages', []),
            citations=result.get('citations', []),
            stats=result.get('stats', {}),
            extracted_pdf_filename=extracted_pdf_filename
        )
    except Exception as e:
         return jsonify({'success': False, 'error': str(e)}), 500

@api_v1.route('/bib-extracts/check-citation', methods=['POST'])
def check_citation():
    """Deep checks a citation against the library."""
    try:
        from services.fuzzy_matcher import FuzzyBookMatcher
        
        data = request.json
        title = data.get('title')
        author = data.get('author')
        
        matcher = FuzzyBookMatcher(str(DB_FILE), debug=True)
        result = matcher.match_book(title, author)
        
        if result['found']:
             return jsonify({'found': True, 'match': result['match']})
        else:
             return jsonify({'found': False})
             
    except Exception as e:
        return jsonify({'found': False, 'error': str(e)}), 500

@api_v1.route('/books/<int:book_id>/reindex', methods=['POST'])
def reindex_book(book_id):
    """Triggers AI-powered re-indexing for a book."""
    try:
        data = request.json if request.is_json else request.form
        ai_care = str(data.get('ai_care', True)).lower() == 'true'
        
        from services.ingestor import ingestor_service
        result = ingestor_service.reprocess_book(book_id, ai_care=ai_care)
        
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
        from services.ingestor import ingestor_service
        data = request.json or {}
        ai_care = str(data.get('ai_care', True)).lower() == 'true'
        result = ingestor_service.preview_reindex(book_id, ai_care=ai_care)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@api_v1.route('/books/<int:book_id>/metadata', methods=['PATCH'])
def update_book_metadata(book_id):
    """Manually updates book metadata fields."""
    try:
        data = request.json
        success, message = library_service.update_metadata(book_id, data)
        
        if not success:
            return jsonify({'error': message}), 400
            
        # Handle ToC update if provided (usually from AI proposal)
        if 'toc' in data:
            try:
                from services.ingestor import ingestor_service
                ingestor_service.sync_chapters(book_id, data['toc'], page_offset=data.get('page_offset', 0))
            except Exception as e:
                print(f"Failed to sync chapters: {e}")

        return jsonify({'success': True, 'message': message})
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
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT path FROM books WHERE id = ?", (book_id,))
            res = cursor.fetchone()
        
        if not res: return jsonify({'error': 'Book not found'}), 404
        
        rel_path = res['path']
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
    execute = not data.get('dry_run', True)
    
    from services.ingestor import ingestor_service
    from core.config import UNSORTED_DIR
    
    files = list(UNSORTED_DIR.glob("*.pdf")) + list(UNSORTED_DIR.glob("*.djvu"))
    results = []
    for f in files:
        results.append(ingestor_service.process_file(f, execute=execute))
        
    return jsonify({
        'success': True,
        'dry_run': not execute,
        'results': results
    })

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
    """Triggers the indexer (FTS rebuild)."""
    data = request.json or {}
    force = data.get('force', False)
    
    try:
        from services.indexer import indexer_service
        indexer_service.scan_library(force=force)
        return jsonify({'success': True, 'message': 'Indexer finished successfully.'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/admin/stats', methods=['GET'])
def admin_stats():
    """Returns database statistics."""
    try:
        with db.get_connection() as conn:
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
            newest = [{'id': r['id'], 'title': r['title'], 'author': r['author']} for r in cursor.fetchall()]
        
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
        results = library_service.check_sanity(fix=False)
        return jsonify({'success': True, 'results': results})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/admin/sanity/fix', methods=['POST'])
def admin_sanity_fix():
    """Runs the database sanity fix."""
    try:
        results = library_service.check_sanity(fix=True)
        return jsonify({'success': True, 'results': results})
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
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT toc_json FROM books WHERE id = ?", (book_id,))
            row = cursor.fetchone()
        
        if not row:
            return jsonify({'error': 'Book not found'}), 404
            
        toc_json = row['toc_json']
        if not toc_json:
             return jsonify({'toc': []})
             
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
            
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO bookmarks (book_id, page_range, tags, notes) VALUES (?, ?, ?, ?)",
                (book_id, page_range, tags, notes)
            )
            new_id = cursor.lastrowid
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
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
        
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
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
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
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT path, title, author, page_count, file_hash FROM books WHERE id = ?", (book_id,))
            row = cursor.fetchone()
            if not row: return jsonify({'error': 'Book not found'}), 404
            
            old_rel_path, old_title, old_author, old_page_count, old_hash = row['path'], row['title'], row['author'], row['page_count'], row['file_hash']
            old_abs_path = (LIBRARY_ROOT / old_rel_path).resolve()
        
        # 2. Save new file to temp
        temp_dir = Path("temp_uploads")
        temp_dir.mkdir(exist_ok=True)
        temp_path = temp_dir / f"replace_{book_id}_{new_file.filename}"
        new_file.save(str(temp_path))
        
        # 3. Heuristics Check
        from services.ingestor import ingestor_service
        new_structure = ingestor_service.extract_structure(temp_path)
        
        if not new_structure:
            if temp_path.exists(): os.remove(temp_path)
            return jsonify({'error': 'Could not read new file structure (Extraction failed)'}), 400
            
        new_page_count = new_structure.get('page_count', 0)
        
        # Heuristic 1: Page Count (allow 10% deviance for better versions)
        if old_page_count and old_page_count > 0:
            diff = abs(new_page_count - old_page_count)
            if diff / old_page_count > 0.10:
                if temp_path.exists(): os.remove(temp_path)
                return jsonify({
                    'error': f'Page count mismatch. Old: {old_page_count}, New: {new_page_count}. This looks like a different book.'
                }), 400

        # Heuristic 2: Hash Check
        new_hash = library_service.calculate_hash(temp_path)
        if new_hash == old_hash:
            if temp_path.exists(): os.remove(temp_path)
            return jsonify({'error': 'This is the exact same file.'}), 400

        # 4. Perform Exchange
        archive_dir = LIBRARY_ROOT / "_Admin" / "Archive" / "Replaced"
        archive_dir.mkdir(parents=True, exist_ok=True)
        
        # Backup old
        if old_abs_path.exists():
            shutil.move(str(old_abs_path), str(archive_dir / f"{book_id}_{old_abs_path.name}"))
        
        # Move new into place
        final_rel_path = Path(old_rel_path).with_suffix(temp_path.suffix.lower())
        final_abs_path = LIBRARY_ROOT / final_rel_path
        shutil.move(str(temp_path), str(final_abs_path))
        
        # 5. Update DB (Technical fields only)
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE books SET 
                    path = ?, 
                    file_hash = ?, 
                    size_bytes = ?, 
                    page_count = ?,
                    last_modified = ?
                WHERE id = ?
            """, (str(final_rel_path), new_hash, final_abs_path.stat().st_size, new_page_count, time.time(), book_id))
        
        return jsonify({
            'success': True, 
            'message': 'File replaced successfully. Original metadata preserved.',
            'new_path': str(final_rel_path)
        })
        
    except Exception as e:
        return jsonify({'error': f"Internal error: {str(e)}", 'trace': traceback.format_exc()}), 500

@api_v1.route('/books/<int:book_id>', methods=['DELETE'])
def delete_book_endpoint(book_id):
    """Safely deletes a book: moves file to archive and removes DB entry."""
    try:
        success, message = library_service.delete_book(book_id)
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'error': message}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500
