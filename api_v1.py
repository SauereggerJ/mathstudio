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
from services.ingestor import ingestor_service
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

@api_v1.route('/books/<int:book_id>/search', methods=['GET'])
def search_within_book_endpoint(book_id):
    query = request.args.get('q', '')
    limit = request.args.get('limit', 50, type=int)
    if not query: return jsonify({'error': 'Missing query parameter (q)'}), 400
    try:
        matches, is_deep = search_service.search_within_book(book_id, query, limit=limit)
        return jsonify({'book_id': book_id, 'query': query, 'matches': matches, 'is_deep_indexed': is_deep})
    except Exception as e: return jsonify({'error': str(e)}), 500

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

@api_v1.route('/tools/bib-scan', methods=['POST'])
def bib_scan_tool():
    """Scans bibliography using the Universal Pipeline."""
    try:
        data = request.json if request.is_json else request.form
        book_id = data.get('book_id')
        if not book_id: return jsonify({'error': 'book_id is required'}), 400
        
        result = ingestor_service.refresh_metadata(int(book_id))
        if not result.get('success'):
            return jsonify({'success': False, 'error': result.get('error')}), 500
        
        return render_template('bib_results.html',
            book_id=book_id,
            book_title=result['data']['metadata'].get('title', 'Book Details'),
            bib_pages="Extracted via Vision-Chunking",
            citations=result['data'].get('bibliography', []),
            stats={"total": len(result['data'].get('bibliography', [])), "owned": 0, "missing": len(result['data'].get('bibliography', []))}
        )
    except Exception as e:
         return jsonify({'success': False, 'error': str(e)}), 500

@api_v1.route('/books/<int:book_id>/metadata', methods=['PATCH'])
def update_book_metadata(book_id):
    """Manually updates book metadata and syncs ToC."""
    try:
        data = request.json
        success, message = library_service.update_metadata(book_id, data)
        if not success: return jsonify({'error': message}), 400
        
        toc_data = data.get('toc')
        if toc_data:
            try:
                ingestor_service.sync_chapters(book_id, toc_data, page_offset=data.get('page_offset', 0))
            except Exception as e: print(f"ToC Sync Error: {e}")
        return jsonify({'success': True, 'message': message})
    except Exception as e: return jsonify({'error': str(e)}), 500

# --- 3. Content & File Management ---

@api_v1.route('/books/<int:book_id>/download', methods=['GET'])
def download_book(book_id):
    try:
        with db.get_connection() as conn:
            res = conn.execute("SELECT path FROM books WHERE id = ?", (book_id,)).fetchone()
        if not res: return jsonify({'error': 'Book not found'}), 404
        abs_path = (LIBRARY_ROOT / res['path']).resolve()
        if abs_path.suffix.lower() == '.pdf': return send_from_directory(abs_path.parent, abs_path.name)
        if abs_path.suffix.lower() == '.djvu':
            cache_dir = Path(current_app.root_path) / "static/cache/pdf"
            cache_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = cache_dir / f"{book_id}.pdf"
            if not pdf_path.exists():
                subprocess.run(['ddjvu', '-format=pdf', str(abs_path), str(pdf_path)], check=True)
            return send_from_directory(cache_dir, f"{book_id}.pdf")
        return jsonify({'error': 'Unsupported format'}), 400
    except Exception as e: return jsonify({'error': str(e)}), 500

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
    try:
        with db.get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
            dois = conn.execute("SELECT COUNT(*) FROM books WHERE doi != ''").fetchone()[0]
            size = conn.execute("SELECT SUM(size_bytes) FROM books").fetchone()[0] or 0
        return jsonify({'total_books': total, 'doi_count': dois, 'total_size_gb': round(size / (1024**3), 2)})
    except Exception as e: return jsonify({'error': str(e)}), 500

@api_v1.route('/admin/sanity/fix', methods=['POST'])
def admin_sanity_fix():
    try:
        results = library_service.check_sanity(fix=True)
        return jsonify({'success': True, 'results': results})
    except Exception as e: return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    pass
