from flask import Blueprint, request, jsonify, send_from_directory, current_app, render_template, send_file
import sqlite3
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
from services.ingestor import ingestor_service
from services.zbmath import zbmath_service
from services.enrichment import enrichment_service
from services.knowledge import knowledge_service
from services.compilation import compilation_service
from services.analytics import analytics_service
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

@api_v1.route('/search/vector', methods=['GET'])
def vector_search_endpoint():
    """Semantic discovery using vector embeddings."""
    query = request.args.get('q', '')
    limit = request.args.get('limit', 20, type=int)
    
    if not query:
        return jsonify({'results': []})
        
    try:
        # Get embedding for query
        query_vec = search_service.get_embedding(query)
        if not query_vec:
            return jsonify({'error': 'Failed to generate embedding'}), 500
            
        # Search semantically
        results = search_service.search_books_semantic(query_vec, top_k=limit)
        
        # Populate results with metadata
        json_results = []
        with db.get_connection() as conn:
            for r in results:
                book = conn.execute("SELECT * FROM books WHERE id = ?", (r['id'],)).fetchone()
                if book:
                    item = dict(book)
                    # Strip binary embedding
                    if item.get('embedding'):
                        item['has_embedding'] = True
                        del item['embedding']
                    item['score'] = r['score']
                    item['cover_url'] = f'/static/thumbnails/{item["id"]}/page_1.png'
                    json_results.append(item)
                    
        return jsonify({'results': json_results})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/browse', methods=['GET'])
def browse_endpoint():
    """Browse library by metadata filters: author, msc, year, keyword."""
    author = request.args.get('author')
    msc = request.args.get('msc')
    year = request.args.get('year') # Changed from type=int to support prefixes
    keyword = request.args.get('keyword')
    limit = request.args.get('limit', 100, type=int)
    
    query = "SELECT * FROM books WHERE 1=1"
    params = []
    
    if author:
        # Use % between name parts to handle middle initials/dots
        parts = [p.strip() for p in author.split(' ') if p.strip()]
        flexible_author = "%" + "%".join(parts) + "%"
        query += " AND author LIKE ?"
        params.append(flexible_author)
    if msc:
        msc_list = msc.split(',')
        msc_clauses = []
        for m in msc_list:
            # Match MSC at start of string or after a space/comma
            msc_clauses.append("(msc_class LIKE ? OR msc_class LIKE ?)")
            params.append(f"{m.strip()}%")
            params.append(f"%, {m.strip()}%")
        query += f" AND ({' OR '.join(msc_clauses)})"
    if year:
        # If year is 4 digits, exact match. If 3 digits, decade match.
        if len(year) == 3:
            query += " AND CAST(year AS TEXT) LIKE ?"
            params.append(f"{year}%")
        else:
            query += " AND year = ?"
            params.append(year)
    if keyword:
        query += " AND (title LIKE ? OR summary LIKE ? OR tags LIKE ?)"
        params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])
        
    query += " ORDER BY year DESC LIMIT ?"
    params.append(limit)
    
    try:
        with db.get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
        
        results = []
        for r in rows:
            item = dict(r)
            if 'embedding' in item: del item['embedding']
            item['cover_url'] = f'/static/thumbnails/{item["id"]}/page_1.png'
            results.append(item)
            
        filter_str = ", ".join([f"{k}={v}" for k, v in request.args.items() if v])
        return jsonify({
            'results': results,
            'total_count': len(results),
            'filter': filter_str
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/msc-stats', methods=['GET'])
def msc_stats_endpoint():
    """Returns book counts per MSC code at all levels (2-digit, 3-char, 5-char)."""
    try:
        with db.get_connection() as conn:
            rows = conn.execute("""
                SELECT msc_class FROM books 
                WHERE msc_class IS NOT NULL AND msc_class != ''
            """).fetchall()

        counts = {}
        for row in rows:
            for code in row['msc_class'].split(','):
                code = code.strip()
                if not code:
                    continue
                # Count at every level
                if len(code) >= 2:
                    p2 = code[:2]
                    counts[p2] = counts.get(p2, 0) + 1
                if len(code) >= 3:
                    p3 = code[:3]
                    counts[p3] = counts.get(p3, 0) + 1
                if len(code) >= 5:
                    counts[code] = counts.get(code, 0) + 1

        return jsonify(counts)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/msc-tree', methods=['GET'])
def msc_tree_endpoint():
    """Serves the full MSC 2020 hierarchy from dokumentation/msc2020.json."""
    import json
    tree_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dokumentation', 'msc2020.json')
    try:
        with open(tree_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except FileNotFoundError:
        return jsonify({'error': 'MSC tree file not found'}), 404

@api_v1.route('/books/<int:book_id>/deep-index', methods=['POST'])
def trigger_deep_indexing(book_id):
    try:
        from services.indexer import indexer_service
        success, message = indexer_service.deep_index_book(book_id)
        if success:
            return jsonify({'success': True, 'message': message})
        return jsonify({'success': False, 'error': message}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/books/<int:book_id>', methods=['GET'])
def get_book_details_endpoint(book_id):
    """Returns JSON metadata for a specific book, joined with zbmath facts."""
    try:
        with db.get_connection() as conn:
            # Join with zbmath_cache to get the 'good shit'
            row = conn.execute("""
                SELECT b.*, z.msc_code as zb_msc, z.keywords, z.links, z.review_markdown as zb_review
                FROM books b
                LEFT JOIN zbmath_cache z ON b.zbl_id = z.zbl_id
                WHERE b.id = ?
            """, (book_id,)).fetchone()
            is_deep = conn.execute("SELECT 1 FROM deep_indexed_books WHERE book_id = ?", (book_id,)).fetchone()
        
        if not row:
            return jsonify({'error': 'Book not found'}), 404
            
        data = dict(row)
        # Helper flags for UI/MCP
        data['has_index'] = bool(data.get('index_text'))
        data['has_toc'] = bool(data.get('toc_json'))
        data['is_deep_indexed'] = bool(is_deep)
        
        # Handle binary embedding
        if data.get('embedding'):
            data['has_embedding'] = True
            del data['embedding']
        else:
            data['has_embedding'] = False
            
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/books/<int:book_id>/search', methods=['GET'])
def search_within_book_endpoint(book_id):
    query = request.args.get('q', '')
    limit = request.args.get('limit', 50, type=int)
    if not query: return jsonify({'error': 'Missing query parameter (q)'}), 400
    try:
        matches, is_deep = search_service.search_within_book(book_id, query, limit=limit)
        return jsonify({'book_id': book_id, 'query': query, 'matches': matches, 'is_deep_indexed': is_deep})
    except Exception as e: return jsonify({'error': str(e)}), 500

@api_v1.route('/books/<int:book_id>/toc', methods=['GET'])
def get_book_toc_endpoint(book_id):
    """Returns structured Table of Contents."""
    try:
        chapters = search_service.get_chapters(book_id)
        return jsonify({'book_id': book_id, 'toc': chapters})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/books/<int:book_id>/reindex', methods=['POST'])
@api_v1.route('/books/<int:book_id>/reindex/<mode>', methods=['POST'])
def trigger_reindex(book_id, mode='auto'):
    """Triggers AI reconstruction of TOC or Back-of-Book Index."""
    try:
        from services.indexer import indexer_service
        
        results = {}
        if mode in ('toc', 'auto'):
            # Current refresh_metadata in ingestor handles TOC/Metadata
            res = ingestor_service.refresh_metadata(book_id)
            results['toc'] = res
            
        if mode in ('index', 'auto'):
            success, msg = indexer_service.reconstruct_index(book_id)
            results['index'] = {'success': success, 'message': msg}
            
        return jsonify({'success': True, 'results': results})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/msc/hierarchy', methods=['GET'])
def get_msc_hierarchy():
    """Serves the MSC 2020 hierarchy as a clean JSON response."""
    try:
        msc_path = Path(current_app.root_path) / "dokumentation/msc2020.json"
        if not msc_path.exists():
            # Fallback to static if it was moved
            msc_path = Path(current_app.root_path) / "static/msc_codes.json"
            
        if not msc_path.exists():
            return jsonify({'error': 'MSC hierarchy file not found'}), 404
            
        with open(msc_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500        

@api_v1.route('/books/<int:book_id>/pages/latex', methods=['GET'])
def get_book_pages_latex(book_id):
    """Returns high-quality LaTeX for a range of pages, utilizing cache and quality checks."""
    pages_str = request.args.get('pages', '')
    force_refresh = request.args.get('refresh') == 'true'
    min_quality = request.args.get('min_quality', 0.7, type=float)
    
    if not pages_str:
        return jsonify({'error': 'pages parameter is required'}), 400
        
    try:
        with db.get_connection() as conn:
            row = conn.execute("SELECT page_count FROM books WHERE id = ?", (book_id,)).fetchone()
        if not row:
            return jsonify({'error': 'Book not found'}), 404
            
        target_pages = parse_page_range(pages_str, row['page_count'])
        if not target_pages:
            return jsonify({'error': 'Invalid page range'}), 400
            
        results, error = note_service.get_or_convert_pages(
            book_id, target_pages, force_refresh=force_refresh, min_quality=min_quality
        )
        
        if error:
            return jsonify({'error': error}), 500
            
        return jsonify({
            'book_id': book_id,
            'pages': results
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@api_v1.route('/notes', methods=['POST'])
def create_note_endpoint():
    """Creates a new note from Markdown/LaTeX content."""
    try:
        data = request.json
        if not data.get('title') or not data.get('markdown'):
            return jsonify({'error': 'title and markdown are required'}), 400
            
        note_id = note_service.create_note(
            title=data['title'],
            markdown_content=data['markdown'],
            latex_content=data.get('latex'),
            tags=data.get('tags'),
            msc=data.get('msc'),
            source_book_id=data.get('book_id')
        )

        # Optional immediate compilation (default: True)
        if data.get('compile', True):
            try:
                compilation_service.compile_note(note_id)
            except Exception as e:
                print(f"Auto-compilation failed: {e}")

        return jsonify({'success': True, 'id': note_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/notes/<int:note_id>/compile', methods=['POST'])
def compile_note_endpoint(note_id):
    """Compiles a specific note's LaTeX to PDF."""
    try:
        result = compilation_service.compile_note(note_id)
        if result.get('success'):
            return jsonify(result)
        return jsonify(result), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/notes/metadata', methods=['GET'])
def get_notes_metadata():
    notes = note_service.list_notes()
    # note_service.list_notes() gives base_name, title, created, modified, directory
    # Let's enrich it with has_pdf and tags.
    from core.config import NOTES_OUTPUT_DIR, CONVERTED_NOTES_DIR
    result = []
    for n in notes:
        base_name = n['base_name']
        d = NOTES_OUTPUT_DIR if n['directory'] == NOTES_OUTPUT_DIR.name else CONVERTED_NOTES_DIR
        has_pdf = (d / f"{base_name}.pdf").exists()
        meta = note_service.get_note_metadata(base_name, d)
        tags = meta.get('tags', [])
        
        result.append({
            'filename': n['filename'],
            'base_name': base_name,
            'title': n['title'],
            'modified': n['modified'],
            'has_pdf': has_pdf,
            'tags': tags
        })
    return jsonify(result)

@api_v1.route('/notes/<filename>', methods=['GET'])
def download_note_file(filename):
    from flask import send_from_directory
    from core.config import NOTES_OUTPUT_DIR, CONVERTED_NOTES_DIR
    for d in [NOTES_OUTPUT_DIR, CONVERTED_NOTES_DIR]:
        if (d / filename).exists():
            return send_from_directory(d, filename)
    return "Note file not found", 404

@api_v1.route('/notes/compile', methods=['POST'])
def compile_notes_endpoint():
    """Triggers the compilation of LaTeX notes into category and master PDFs."""
    try:
        result = compilation_service.compile_all()
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
        
# --- 2. Universal Pipeline Tools ---
@api_v1.route('/books/<int:book_id>/metadata/refresh', methods=['POST'])
def refresh_book_metadata(book_id):
    """Triggers the new Universal Vision-Reflection Pipeline."""
    try:
        result = ingestor_service.refresh_metadata(book_id)
        if result.get('success'):
            return jsonify(result)
        return jsonify(result), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/books/<int:book_id>/metadata/refresh/preview', methods=['POST'])
def preview_metadata_refresh(book_id):
    """Generates a proposal using the new pipeline logic (no save)."""
    try:
        result = ingestor_service.preview_metadata_update(book_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/books/<int:book_id>/enrich', methods=['POST'])
def enrich_book_endpoint(book_id):
    """Enriches a specific book with zbMATH data."""
    try:
        result = zbmath_service.enrich_book(book_id)
        if result.get('success'):
            enrichment_service.sync_fts_after_enrichment(book_id)
            return jsonify(result)
        return jsonify(result), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/admin/enrich/batch', methods=['POST'])
def batch_enrich_endpoint():
    """Triggers batch enrichment for raw books."""
    try:
        limit = request.json.get('limit', 50) if request.is_json else 50
        results = enrichment_service.enrich_batch(limit=limit)
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/tools/bib-scan', methods=['POST'])
def bib_scan_tool():
    """Scans bibliography and resolves citations using the specialized service."""
    try:
        data = request.json if request.is_json else request.form
        book_id = data.get('book_id')
        if not book_id: return jsonify({'error': 'book_id is required'}), 400
        book_id = int(book_id)
        
        # 1. Extraction (Vision-First)
        scan_res = bibliography_service.scan_book(book_id)
        if not scan_res.get('success'):
            return jsonify({'success': False, 'error': scan_res.get('error')}), 500
            
        # 2. Resolution (Optional - can be slow, so we might want to return early and resolve in bg)
        # For now, let's do a partial resolution or return extraction results
        
        return render_template('bib_results.html',
            book_id=book_id,
            book_title=scan_res.get('book_title', 'Book Details'),
            bib_pages="Extracted via specialized Vision-Chunking",
            citations=scan_res.get('citations', []),
            stats={"total": len(scan_res.get('citations', [])), "owned": 0, "missing": len(scan_res.get('citations', []))}
        )
    except Exception as e:
         return jsonify({'success': False, 'error': str(e)}), 500

@api_v1.route('/books/<int:book_id>/citations/resolve', methods=['POST'])
def resolve_book_citations(book_id):
    """Triggers background resolution of citations for a book."""
    try:
        # Since this can take minutes, we'd ideally background it.
        # For REHAB simplicity, we'll run it and return results.
        result = bibliography_service.resolve_citations(book_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/books/<int:book_id>/metadata', methods=['PATCH'])
def update_book_metadata(book_id):
    """Manually updates book metadata, syncs ToC and Bibliography."""
    try:
        data = request.json
        success, message = library_service.update_metadata(book_id, data)
        if not success: return jsonify({'error': message}), 400
        
        # 1. Sync ToC
        toc_data = data.get('toc')
        if toc_data:
            try:
                ingestor_service.sync_chapters(book_id, toc_data, page_offset=data.get('page_offset', 0))
            except Exception as e: print(f"ToC Sync Error: {e}")
            
        # 2. Sync Bibliography (New for Universal Pipeline)
        bib_data = data.get('bibliography')
        if bib_data and isinstance(bib_data, list):
            try:
                with db.get_connection() as conn:
                    conn.execute("DELETE FROM bib_entries WHERE book_id = ?", (book_id,))
                    for entry in bib_data:
                        if isinstance(entry, dict):
                            conn.execute("""
                                INSERT INTO bib_entries (book_id, raw_text, title, author)
                                VALUES (?, ?, ?, ?)
                            """, (book_id, entry.get('raw_text', ''), entry.get('title', ''), entry.get('author', '')))
            except Exception as e: print(f"Bib Sync Error: {e}")

        return jsonify({'success': True, 'message': message})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- 3. Content & Bookmarks ---

@api_v1.route('/bookmarks', methods=['GET'])
def list_bookmarks():
    try:
        book_id = request.args.get('book_id', type=int)
        tags = request.args.get('tags')
        
        query = """
            SELECT bkm.*, b.title as book_title 
            FROM bookmarks bkm
            JOIN books b ON bkm.book_id = b.id
        """
        params = []
        if book_id:
            query += " WHERE bkm.book_id = ?"
            params.append(book_id)
        if tags:
            query += (" AND" if book_id else " WHERE") + " bkm.tags LIKE ?"
            params.append(f"%{tags}%")
            
        with db.get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/bookmarks', methods=['POST'])
def create_bookmark():
    try:
        data = request.json
        book_id = data.get('book_id')
        if not book_id: return jsonify({'error': 'book_id is required'}), 400
        
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO bookmarks (book_id, page_range, tags, notes)
                VALUES (?, ?, ?, ?)
            """, (book_id, data.get('page_range'), data.get('tags'), data.get('notes')))
            new_id = cursor.lastrowid
        return jsonify({'success': True, 'id': new_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/bookmarks/<int:bookmark_id>', methods=['DELETE'])
def delete_bookmark(bookmark_id):
    try:
        with db.get_connection() as conn:
            conn.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- 4. Structured Notes & Transcriptions ---

@api_v1.route('/notes', methods=['GET'])
def list_notes_endpoint():
    """Returns a list of structured notes from the DB."""
    source_type = request.args.get('type')
    book_id = request.args.get('book_id', type=int)
    limit = request.args.get('limit', 50, type=int)
    try:
        notes = note_service.list_notes(source_type=source_type, book_id=book_id, limit=limit)
        return jsonify(notes)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/notes/search', methods=['GET'])
def search_notes_endpoint():
    """Performs FTS search over notes."""
    query = request.args.get('q', '')
    limit = request.args.get('limit', 50, type=int)
    if not query: return list_notes_endpoint()
    try:
        results = note_service.search_notes(query, limit=limit)
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/notes/<int:note_id>', methods=['GET'])
def get_note_by_id_endpoint(note_id):
    """Returns detailed metadata and paths for a specific note."""
    try:
        note = note_service.get_note(note_id)
        if not note: return jsonify({'error': 'Note not found'}), 404
        return jsonify(note)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/notes/<int:note_id>/content', methods=['GET'])
def get_note_content_endpoint(note_id):
    """Returns the markdown and latex content of a note."""
    try:
        note = note_service.get_note(note_id)
        if not note: return jsonify({'error': 'Note not found'}), 404
        
        result = {}
        if note.get('markdown_path') and os.path.exists(note['markdown_path']):
            with open(note['markdown_path'], 'r', encoding='utf-8') as f:
                result['markdown'] = f.read()
        
        if note.get('latex_path') and os.path.exists(note['latex_path']):
            with open(note['latex_path'], 'r', encoding='utf-8') as f:
                result['latex'] = f.read()
                
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/notes/<int:note_id>/content', methods=['PATCH'])
def update_note_content_endpoint(note_id):
    """Updates the markdown and/or latex content of a note."""
    try:
        data = request.json
        if note_service.update_note_content(note_id, 
                                          markdown_content=data.get('markdown'),
                                          latex_content=data.get('latex')):
            return jsonify({'success': True})
        return jsonify({'error': 'Update failed'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/notes/<int:note_id>/metadata', methods=['PATCH'])
def update_note_metadata_endpoint(note_id):
    """Updates note metadata (title, tags, msc)."""
    try:
        data = request.json
        if note_service.update_note_metadata(note_id, data):
            return jsonify({'success': True})
        return jsonify({'error': 'Update failed'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/notes/tags/suggestions', methods=['GET'])
def get_tag_suggestions_endpoint():
    """Returns tag/keyword suggestions based on prefix."""
    q = request.args.get('q', '')
    if not q: return jsonify([])
    try:
        suggestions = note_service.get_tag_suggestions(q)
        return jsonify(suggestions)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/notes/<int:note_id>/relations', methods=['POST'])
def add_note_relation_endpoint(note_id):
    """Connects this note to another note."""
    try:
        target_id = request.json.get('target_id')
        rel_type = request.json.get('type', 'related')
        if not target_id: return jsonify({'error': 'target_id required'}), 400
        if note_service.add_relation(note_id, target_id, rel_type):
            return jsonify({'success': True})
        return jsonify({'error': 'Failed to add relation'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/notes/<int:note_id>/relations/<int:target_id>', methods=['DELETE'])
def delete_note_relation_endpoint(note_id, target_id):
    """Removes connection between two notes."""
    try:
        note_service.delete_relation(note_id, target_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/notes/<int:note_id>/books', methods=['POST'])
def add_note_book_relation_endpoint(note_id):
    """Associates a note with a book and optional page."""
    try:
        data = request.json
        book_id = data.get('book_id')
        page = data.get('page')
        if not book_id: return jsonify({'error': 'book_id required'}), 400
        
        if note_service.add_book_relation(note_id, book_id, page):
            return jsonify({'success': True})
        return jsonify({'error': 'Failed to add book relation'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/notes/<int:note_id>/books/<int:book_id>', methods=['DELETE'])
@api_v1.route('/notes/<int:note_id>/books/<int:book_id>/<int:page>', methods=['DELETE'])
def delete_note_book_relation_endpoint(note_id, book_id, page=None):
    """Removes association with a book/page."""
    try:
        note_service.delete_book_relation(note_id, book_id, page)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/notes/<int:note_id>', methods=['DELETE'])
def delete_note_by_id_endpoint(note_id):
    """Deletes a note from the DB and FTS index."""
    try:
        success = note_service.delete_note(note_id)
        return jsonify({'success': success})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/notes/upload', methods=['POST'])
def upload_note_scan():
    """Handles image upload, transcribes via Vision LLM, and records in DB."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    try:
        image_data = file.read()
        # 1. Transcribe via Gemini Vision
        transcription = note_service.transcribe_note(image_data)
        if not transcription:
            return jsonify({'error': 'Transcription failed'}), 500
            
        # 2. Process, Save files and DB record
        note_id = note_service.process_uploaded_note(transcription, image_data)
        
        return jsonify({
            'success': True, 
            'id': note_id, 
            'transcription': transcription
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/notes/sync', methods=['POST'])
def sync_notes_endpoint():
    """Manually triggers a filesystem-to-DB synchronization for legacy notes."""
    try:
        count = note_service.sync_filesystem_to_db()
        return jsonify({'success': True, 'synced_count': count})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/notes/<int:note_id>/pdf', methods=['GET'])
def get_note_pdf_endpoint(note_id):
    """Serves the compiled PDF for a note."""
    try:
        note = note_service.get_note(note_id)
        if not note or not note['pdf_path']: return jsonify({'error': 'PDF not found'}), 404
        path = Path(note['pdf_path'])
        if not path.exists(): return jsonify({'error': 'File not found on disk'}), 404
        return send_from_directory(path.parent, path.name)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/notes/metadata', methods=['GET'])
def get_all_notes_metadata():
    """Returns metadata for all notes in a flat list (legacy compatibility)."""
    return list_notes_endpoint()

@api_v1.route('/books/<int:book_id>/download', methods=['GET'])
def download_book(book_id):
    try:
        file_path, error = library_service.get_file_for_serving(book_id)
        if error:
            return jsonify({'error': error}), 404 if "not found" in error else 400
        return send_from_directory(file_path.parent, file_path.name)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/notes/<filename>', methods=['DELETE'])
def delete_note_endpoint(filename):
    """Deletes a specific note file."""
    try:
        base_name = os.path.splitext(filename)[0]
        if note_service.delete_note(base_name):
            return jsonify({'success': True})
        return jsonify({'error': 'Note not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/notes/bulk-delete', methods=['POST'])
def delete_notes_bulk():
    """Deletes multiple notes at once."""
    try:
        data = request.get_json()
        deleted = sum(1 for f in data.get('filenames', []) if note_service.delete_note(os.path.splitext(f)[0]))
        return jsonify({'success': True, 'deleted': deleted})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/admin/ingest', methods=['POST'])
def admin_ingest():
    """Book Ingestion via Universal Pipeline."""
    data = request.json or {}
    execute = not data.get('dry_run', True)
    from core.config import UNSORTED_DIR
    files = list(UNSORTED_DIR.glob("*.pdf")) + list(UNSORTED_DIR.glob("*.djvu"))
    results = []
    for f in files:
        results.append(ingestor_service.process_file(f, execute=execute))
    return jsonify({'success': True, 'dry_run': not execute, 'results': results})

@api_v1.route('/admin/indexer', methods=['POST'])
def admin_rebuild_fts():
    """Rebuild the books_fts search index from the books table."""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            # Drop and recreate the FTS virtual table
            cursor.execute("DROP TABLE IF EXISTS books_fts")
            cursor.execute('''
                CREATE VIRTUAL TABLE books_fts USING fts5(
                    title, author, content, index_content,
                    content_rowid='id',
                    tokenize='porter unicode61 remove_diacritics 1'
                )
            ''')
            # Re-populate from books table
            cursor.execute('''
                INSERT INTO books_fts(rowid, title, author, content, index_content)
                SELECT id, 
                       COALESCE(title, ''), 
                       COALESCE(author, ''), 
                       COALESCE(summary, ''), 
                       COALESCE(index_text, '')
                FROM books
            ''')
            count = cursor.rowcount
            conn.commit()

        return jsonify({'success': True, 'indexed': count, 'message': f'FTS index rebuilt with {count} books'})
    except Exception as e:
        print(f"FTS Rebuild Error: {e}", file=sys.stderr)
        return jsonify({'success': False, 'error': str(e)}), 500

@api_v1.route('/admin/stats', methods=['GET'])
def admin_stats():
    """Returns general library statistics for the dashboard."""
    try:
        with db.get_connection() as conn:
            total = conn.execute("SELECT count(*) FROM books").fetchone()[0]
            doi_count = conn.execute("SELECT count(*) FROM books WHERE doi IS NOT NULL AND doi != '' AND doi != 'Unknown' AND doi != 'N/A'").fetchone()[0]
            zbl_count = conn.execute("SELECT count(*) FROM books WHERE zbl_id IS NOT NULL AND zbl_id != ''").fetchone()[0]
            
            # Metadata Status breakdown
            status_counts = conn.execute("SELECT metadata_status, count(*) FROM books GROUP BY metadata_status").fetchall()
            status_map = {row[0] or 'raw': row[1] for row in status_counts}

            categories = conn.execute("SELECT directory as name, count(*) as count FROM books GROUP BY directory ORDER BY count DESC").fetchall()
            publishers = conn.execute("SELECT publisher as name, count(*) as count FROM books WHERE publisher IS NOT NULL AND publisher != '' GROUP BY publisher ORDER BY count DESC LIMIT 5").fetchall()
            newest = conn.execute("SELECT id, title FROM books ORDER BY id DESC LIMIT 5").fetchall()

            # Estimate size
            total_size_bytes = conn.execute("SELECT sum(size_bytes) FROM books").fetchone()[0] or 0
            
        return jsonify({
            'total_books': total,
            'doi_count': doi_count,
            'zbl_count': zbl_count,
            'status_distribution': status_map,
            'total_size_gb': round(total_size_bytes / (1024**3), 2),
            'categories': [dict(c) for c in categories],
            'publishers': [dict(p) for p in publishers],
            'newest': [dict(n) for n in newest]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/admin/sanity/fix', methods=['POST'])
def admin_sanity_fix():
    try:
        results = library_service.check_sanity(fix=True)
        return jsonify({'success': True, 'results': results})
    except Exception as e: return jsonify({'error': str(e)}), 500

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
            res = conn.execute("SELECT path, page_count FROM books WHERE id = ?", (book_id,)).fetchone()
        
        if not res: return jsonify({'error': 'Book not found'}), 404
        abs_path = (LIBRARY_ROOT / res['path']).resolve()
        
        from core.utils import PDFHandler
        handler = PDFHandler(abs_path)
        
        # Determine target pages
        page_count = res['page_count'] or 1000 # Fallback
        target_pages = parse_page_range(str(pages_str), page_count)
        
        # Open source with targeted pages (handles DjVu conversion automatically)
        # indices are 0-based
        doc, t_path = handler._open_source(page_indices=[p-1 for p in target_pages])
        
        full_text = ""
        try:
            for p_idx in target_pages:
                # p_idx is 1-based, fitz is 0-based
                # We use the absolute index because for PDFs _open_source returns the full doc.
                # For DjVu, _open_source might return a sliced temp doc, but that's handled differently.
                # Actually, let's make it robust:
                actual_idx = p_idx - 1 if t_path is None else target_pages.index(p_idx)
                page_text = doc[actual_idx].get_text()
                full_text += f"\n--- Page {p_idx} ---\n{page_text}\n"
        finally:
            doc.close()
            if t_path and t_path.exists(): t_path.unlink()
                
        return jsonify({'success': True, 'text': full_text})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@api_v1.route('/tools/pdf-to-note', methods=['POST'])
def pdf_to_note_tool():
    """Converts PDF pages to LaTeX/Markdown (cached) and triggers KB proposals. Does NOT create a Note."""
    try:
        data = request.json
        book_id = data.get('book_id')
        pages_str = str(data.get('pages') or data.get('page'))
        
        if not book_id or not pages_str:
            return jsonify({'error': 'book_id and pages/page are required'}), 400
            
        with db.get_connection() as conn:
            row = conn.execute("SELECT page_count FROM books WHERE id = ?", (book_id,)).fetchone()
        
        if not row: return jsonify({'error': 'Book not found'}), 404
        
        target_pages = parse_page_range(pages_str, row['page_count'])
        if not target_pages: return jsonify({'error': 'Invalid page range'}), 400
        
        force_refresh = data.get('refresh', False)
        
        # Convert + cache + trigger proposals (no Note record created)
        results, convert_error = note_service.get_or_convert_pages(
            book_id, target_pages, force_refresh=force_refresh
        )
        
        if convert_error:
            return jsonify({'success': False, 'error': convert_error}), 500
        
        # Combine for display
        combined = ""
        for pr in results:
            page_num = pr.get('page')
            if pr.get('error'):
                combined += f"\n\n> [Error on page {page_num}: {pr['error']}]\n\n"
            elif pr.get('markdown'):
                combined += f"\n## Page {page_num}\n\n{pr['markdown']}"
            elif pr.get('raw_text'):
                combined += f"\n## Page {page_num} (raw text)\n\n{pr['raw_text']}"
        
        return jsonify({
            'success': True,
            'content': combined.strip(),
            'pages_converted': len([r for r in results if not r.get('error')])
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@api_v1.route('/wishlist', methods=['POST'])
def add_to_wishlist():
    """Adds a new item to the wishlist."""
    try:
        data = request.json
        if not data.get('title'): return jsonify({'error': 'title is required'}), 400
        
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO wishlist (title, author, doi, source_book_id, status)
                VALUES (?, ?, ?, ?, 'pending')
            """, (data['title'], data.get('author'), data.get('doi'), data.get('source_book_id')))
            new_id = cursor.lastrowid
        return jsonify({'success': True, 'id': new_id})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'DOI already in wishlist'}), 409
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/books/<int:book_id>/ignore', methods=['POST'])
def ignore_book(book_id):
    """Marks a book as ignored/script so it's skipped by background processes."""
    try:
        with db.get_connection() as conn:
            conn.execute("UPDATE books SET metadata_status = 'ignored' WHERE id = ?", (book_id,))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/admin/conflicts', methods=['GET'])
def get_conflicts():
    """Returns a list of books currently in conflict status with their zbMATH counterparts."""
    try:
        with db.get_connection() as conn:
            rows = conn.execute("""
                SELECT b.id, b.title as local_title, b.author as local_author, b.path,
                       z.title as zb_title, z.authors as zb_authors, b.zbl_id
                FROM books b
                LEFT JOIN zbmath_cache z ON b.zbl_id = z.zbl_id
                WHERE b.metadata_status = 'conflict'
            """).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/admin/conflicts/resolve', methods=['POST'])
def resolve_conflict():
    """Accepts or rejects zbMATH metadata for a book."""
    try:
        data = request.json
        book_id = data.get('book_id')
        action = data.get('action') # 'accept' or 'reject'
        
        if not book_id or action not in ['accept', 'reject']:
            return jsonify({'error': 'Invalid request'}), 400
            
        with db.get_connection() as conn:
            if action == 'accept':
                # Master title from zbmath
                row = conn.execute("SELECT title FROM zbmath_cache WHERE zbl_id = (SELECT zbl_id FROM books WHERE id = ?)", (book_id,)).fetchone()
                if row:
                    conn.execute("UPDATE books SET metadata_status = 'verified', title = ? WHERE id = ?", (row['title'], book_id))
            else:
                # Nuke the bad link and set back to raw
                conn.execute("UPDATE books SET metadata_status = 'raw', zbl_id = NULL, trust_score = 0 WHERE id = ?", (book_id,))
                
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/admin/logs', methods=['GET'])
def get_admin_logs():
    """Returns the last lines of the enrichment logs."""
    log_file = request.args.get('file', 'enrichment_full_run.log')
    # Prevent path traversal
    if log_file not in ['enrichment_full_run.log', 'enrichment_batch.log']:
        return jsonify({'error': 'Access denied'}), 403
        
    try:
        if not os.path.exists(log_file):
            return jsonify({'logs': 'Log file not found yet.'})
            
        with open(log_file, 'r') as f:
            # Get last 100 lines
            lines = f.readlines()[-100:]
            return jsonify({'logs': "".join(lines)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_v1.route('/tools/open-external', methods=['GET'])
def open_external_tool():
    """Opens a file path using the system's default handler (Desktop mode)."""
    try:
        rel_path = request.args.get('path')
        if not rel_path: return jsonify({'error': 'path is required'}), 400
        
        abs_path = (LIBRARY_ROOT / rel_path).resolve()
        if LIBRARY_ROOT.resolve() not in abs_path.parents:
            return jsonify({'error': 'Access denied'}), 403
            
        if not abs_path.exists():
            return jsonify({'error': 'File not found'}), 404
            
        import subprocess
        import platform
        if platform.system() == 'Darwin':       # macOS
            subprocess.call(('open', str(abs_path)))
        elif platform.system() == 'Windows':    # Windows
            os.startfile(str(abs_path))
        else:                                   # linux variants
            subprocess.call(('xdg-open', str(abs_path)))
            
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- 4. Knowledge Base ---

@api_v1.route('/kb/concepts', methods=['GET'])
def kb_browse_concepts():
    """Browse concepts with letter filter and sorting."""
    letter = request.args.get('letter')
    sort = request.args.get('sort', 'alpha')
    kind = request.args.get('kind')
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)
    result = knowledge_service.browse_concepts(letter=letter, sort=sort, kind=kind,
                                                limit=limit, offset=offset)
    return jsonify(result)

@api_v1.route('/kb/concepts', methods=['POST'])
def kb_add_concept():
    data = request.json
    if not data.get('name') or not data.get('kind'):
        return jsonify({'error': 'name and kind are required'}), 400
    result = knowledge_service.add_concept(
        name=data['name'], kind=data['kind'],
        domain=data.get('domain'), aliases=data.get('aliases'))
    return jsonify(result), 200 if result.get('success') else 409

@api_v1.route('/kb/concepts/<int:concept_id>', methods=['GET'])
def kb_get_concept(concept_id):
    result = knowledge_service.get_concept(concept_id)
    if not result: return jsonify({'error': 'Not found'}), 404
    return jsonify(result)

@api_v1.route('/kb/concepts/<int:concept_id>', methods=['PATCH'])
def kb_update_concept(concept_id):
    result = knowledge_service.update_concept(concept_id, **request.json)
    return jsonify(result), 200 if result.get('success') else 400

@api_v1.route('/kb/concepts/<int:concept_id>', methods=['DELETE'])
def kb_delete_concept(concept_id):
    result = knowledge_service.delete_concept(concept_id)
    return jsonify(result), 200 if result.get('success') else 400

@api_v1.route('/kb/concepts/search', methods=['GET'])
def kb_search_concepts():
    query = request.args.get('q', '')
    if not query: return jsonify({'error': 'q is required'}), 400
    results = knowledge_service.search_concepts(
        query, kind=request.args.get('kind'),
        limit=request.args.get('limit', 20, type=int))
    return jsonify(results)

@api_v1.route('/kb/add-location', methods=['POST'])
def kb_add_location():
    """Register where a theorem/definition appears in a book."""
    data = request.json
    if not data.get('concept_name') or not data.get('book_id') or not data.get('page'):
        return jsonify({'error': 'concept_name, book_id, and page are required'}), 400
    result = knowledge_service.add_location(
        concept_name=data['concept_name'],
        kind=data.get('kind', 'theorem'),
        book_id=data['book_id'],
        page=data['page'],
        statement_preview=data.get('statement_preview'))
    return jsonify(result), 200 if result.get('success') else 400

@api_v1.route('/kb/entries', methods=['POST'])
def kb_add_entry():
    data = request.json
    if not data.get('concept_id'):
        return jsonify({'error': 'concept_id is required'}), 400
    result = knowledge_service.add_entry(
        concept_id=data['concept_id'],
        book_id=data.get('book_id'),
        page_start=data.get('page_start'),
        page_end=data.get('page_end'),
        statement=data.get('statement'),
        is_canonical=data.get('is_canonical'))
    return jsonify(result), 200 if result.get('success') else 400

@api_v1.route('/kb/entries/<int:entry_id>', methods=['DELETE'])
def kb_delete_entry(entry_id):
    result = knowledge_service.delete_entry(entry_id)
    return jsonify(result), 200 if result.get('success') else 400

@api_v1.route('/kb/schema', methods=['GET'])
def kb_get_schema():
    return jsonify(knowledge_service.get_kb_schema_info())

# --- KB Proposals (auto-discovery approval) ---

@api_v1.route('/kb/proposals', methods=['GET'])
def kb_list_proposals():
    status = request.args.get('status', 'pending')
    limit = request.args.get('limit', 50, type=int)
    return jsonify(knowledge_service.list_proposals(status, limit))

@api_v1.route('/kb/proposals/count', methods=['GET'])
def kb_proposal_count():
    return jsonify({'count': knowledge_service.get_proposal_count()})

@api_v1.route('/kb/proposals/<int:proposal_id>', methods=['GET'])
def kb_get_proposal(proposal_id):
    result = knowledge_service.get_proposal(proposal_id)
    if not result: return jsonify({'error': 'Not found'}), 404
    return jsonify(result)

@api_v1.route('/kb/proposals/<int:proposal_id>/approve', methods=['POST'])
def kb_approve_proposal(proposal_id):
    result = knowledge_service.approve_proposal(proposal_id)
    return jsonify(result), 200 if result.get('success') else 400

@api_v1.route('/kb/proposals/<int:proposal_id>/merge', methods=['POST'])
def kb_merge_proposal(proposal_id):
    data = request.json or {}
    target_id = data.get('target_concept_id')
    if not target_id:
        return jsonify({'error': 'target_concept_id is required'}), 400
    result = knowledge_service.merge_proposal(proposal_id, target_id)
    return jsonify(result), 200 if result.get('success') else 400

@api_v1.route('/kb/proposals/<int:proposal_id>/reject', methods=['POST'])
def kb_reject_proposal(proposal_id):
    result = knowledge_service.reject_proposal(proposal_id)
    return jsonify(result), 200 if result.get('success') else 400

# --- 5. Analytics ---

@api_v1.route('/analytics/coauthors', methods=['GET'])
def get_coauthor_network():
    return jsonify(analytics_service.get_coauthor_network())

@api_v1.route('/analytics/timeline', methods=['GET'])
def get_msc_timeline():
    return jsonify(analytics_service.get_msc_timeline())

@api_v1.route('/analytics/cross-pollination', methods=['GET'])
def get_cross_pollination():
    return jsonify(analytics_service.get_cross_pollination())

@api_v1.route('/analytics/export/canvas', methods=['POST'])
def export_analytics_canvas():
    return jsonify(analytics_service.export_coauthor_canvas())
