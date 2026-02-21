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
            for i, p_idx in enumerate(target_pages):
                # doc contains only the sliced pages in order
                page_text = doc[i].get_text()
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
    """Converts PDF pages to structured Markdown/LaTeX notes using AI."""
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
        
        result, error = note_service.create_note_from_pdf(book_id, target_pages)
        
        if error:
            return jsonify({'success': False, 'error': error}), 500
            
        return jsonify({
            'success': True, 
            'filename': result['filename'],
            'content': result['content']
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
