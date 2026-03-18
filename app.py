from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for, flash, abort, send_file
import os
import json
import subprocess
import threading
import time
from pathlib import Path
from datetime import datetime

from core.config import DB_FILE, LIBRARY_ROOT, NOTES_OUTPUT_DIR, CONVERTED_NOTES_DIR
from core.database import db
from api_v1 import api_v1
from services.search import search_service
from services.library import library_service
from services.note import note_service
from services.zbmath import zbmath_service
from core.ai import ai
from flask_cors import CORS

app = Flask(__name__)
CORS(app) # Enable CORS for all routes
app.secret_key = 'supersecretkey'

# Configure logging to file
import logging
log_file = os.path.join(os.path.dirname(__file__), 'app.log')
file_handler = logging.FileHandler(log_file)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
))
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)
# Also add it to our service loggers if they don't have one
logging.getLogger('services').addHandler(file_handler)
logging.getLogger('services').setLevel(logging.INFO)
logging.getLogger('core').addHandler(file_handler)
logging.getLogger('core').setLevel(logging.INFO)
logging.getLogger('converter').addHandler(file_handler)
logging.getLogger('converter').setLevel(logging.INFO)

app.logger.info(f"=== MathStudio App Starting. Log: {log_file} ===")


@app.template_filter('from_json')
def from_json_filter(value):
    try:
        return json.loads(value)
    except:
        return []

@app.template_filter('from_unix_timestamp')
def from_unix_timestamp_filter(value):
    if not value: return "N/A"
    return datetime.fromtimestamp(value).strftime('%d. %b %Y, %H:%M')

@app.template_filter('read_file_content')
def read_file_content_filter(filepath):
    if not filepath: return ""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except:
        return f"[Error reading file: {filepath}]"

def update_state(action, **kwargs):
    """Updates the current_state.json file for agent awareness."""
    state_file = Path(app.root_path) / "current_state.json"
    state = {
        "last_action": action,
        "timestamp": datetime.now().isoformat(),
        **kwargs
    }
    try:
        with open(state_file, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        app.logger.error(f"Failed to update state: {e}")

def run_housekeeping():
    """Performs deep library maintenance (runs every 12 hours)."""
    app.logger.info("HOUSEKEEPING: Starting scheduled maintenance...")
    try:
        from rapidfuzz import fuzz
        with db.get_connection() as conn:
            # 1. Wishlist Cleanup
            wishlist = conn.execute('SELECT id, title, author FROM wishlist WHERE status = "pending"').fetchall()
            library = conn.execute('SELECT id, title, author FROM books').fetchall()
            cleaned = 0
            for w in wishlist:
                for b in library:
                    if fuzz.token_set_ratio(w['title'], b['title']) > 85:
                        conn.execute('UPDATE wishlist SET status = "acquired" WHERE id = ?', (w['id'],))
                        cleaned += 1
                        break
            app.logger.info(f"HOUSEKEEPING: Wishlist cleaned. {cleaned} items marked as acquired.")

            # 2. DOI to Zbl Bridge Refresher
            dois_without_zbl = conn.execute('SELECT id, doi FROM books WHERE doi IS NOT NULL AND (zbl_id IS NULL OR zbl_id = "") LIMIT 50').fetchall()
            zbl_found = 0
            for row in dois_without_zbl:
                zbl = zbmath_service.get_zbl_id_from_doi(row['doi'])
                if zbl:
                    conn.execute('UPDATE books SET zbl_id = ? WHERE id = ?', (zbl, row['id']))
                    zbl_found += 1
            app.logger.info(f"HOUSEKEEPING: Zbl-Bridge refreshed. {zbl_found} new IDs mapped.")
    except Exception as e:
        app.logger.error(f"HOUSEKEEPING Error: {e}")

# Register API
app.register_blueprint(api_v1, url_prefix='/api/v1')

# One-time backfill: populate LaTeX FTS from existing cached pages
def _run_fts_backfill():
    time.sleep(5)  # Let the app fully start
    try:
        db.initialize_schema()  # Ensure extracted_pages_fts exists
        count = note_service.backfill_latex_fts()
        if count > 0:
            app.logger.info(f"Startup: Backfilled {count} pages into extracted_pages_fts")
    except Exception as e:
        app.logger.warning(f"FTS backfill failed: {e}")

threading.Thread(target=_run_fts_backfill, daemon=True).start()

# Start scan worker (processes Full Book Scans one at a time)
def _run_scan_worker():
    time.sleep(15)  # Let everything else start first
    try:
        note_service.scan_worker()
    except Exception as e:
        app.logger.error(f"Scan worker crashed: {e}")

threading.Thread(target=_run_scan_worker, daemon=True).start()

# --- Frontend Routes ---

@app.route('/')
def index(): return render_template('index.html')

@app.route('/admin')
def admin_dashboard(): return render_template('admin.html')

@app.route('/msc')
def msc_browser(): return render_template('msc_browser.html')

@app.route('/analytics')
def analytics_dashboard(): return render_template('analytics.html')

@app.route('/knowledge')
def knowledge_browser(): return render_template('knowledge_browser.html')

@app.route('/book/<int:book_id>/edit')
def edit_book(book_id):
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM books WHERE id = ?", (book_id,))
        book = cursor.fetchone()
    if not book: return "Book not found", 404
    return render_template('edit_book.html', **dict(book))

@app.route('/book/<int:book_id>')
def book_details(book_id):
    query = request.args.get('q', '')
    with db.get_connection() as conn:
        cursor = conn.cursor()
        # Fetch book with potential new zbl_id from background process
        cursor.execute("""
            SELECT id, filename, path, directory, author, title, publisher, year, isbn, doi, zbl_id,
                   summary, level, has_exercises AS exercises, has_solutions AS solutions, 
                   msc_class AS msc_code, tags, description, toc_json, audience, page_count, index_text 
            FROM books WHERE id = ?
        """, (book_id,))
        book = cursor.fetchone()
        if not book: return "Book not found", 404
        book_dict = dict(book)
        
        # Freshly fetch extra zbmath cache for the book itself
        zb_extra = None
        if book_dict.get('zbl_id'):
            cursor.execute("SELECT * FROM zbmath_cache WHERE zbl_id = ?", (book_dict['zbl_id'],))
            row = cursor.fetchone()
            if row: zb_extra = dict(row)

        similar_books = search_service.get_similar_books(book_id)
        chapters = search_service.get_chapters(book_id)
        matches = []
        if query:
            matches = search_service.get_book_matches(book_id, query)[:20]
        
        index_matches = None
        if query and book_dict.get('index_text'):
            index_matches = search_service.extract_index_pages(book_dict['index_text'], query)
            if index_matches: index_matches = index_matches[:20]

        cursor.execute("""
            SELECT b.*, z.title as zb_title, z.authors as zb_authors, z.msc_code, 
                   z.keywords, z.links, z.review_markdown as zb_review
            FROM bib_entries b
            LEFT JOIN zbmath_cache z ON b.resolved_zbl_id = z.zbl_id
            WHERE b.book_id = ?
            ORDER BY b.id ASC LIMIT 50
        """, (book_id,))
        bibliography = [dict(row) for row in cursor.fetchall()]

        cursor.execute("""
            SELECT page_number, quality_score, created_at, latex_path, markdown_path
            FROM extracted_pages
            WHERE book_id = ?
            ORDER BY page_number ASC
        """, (book_id,))
        extracted_pages = [dict(row) for row in cursor.fetchall()]

    update_state("view_book", book_id=book_id, extra={"title": book_dict['title'], "path": str(book_dict['path'])})
    return render_template('book.html', **book_dict, query=query, similar_books=similar_books, chapters=chapters, matches=matches, index_matches=index_matches, bibliography=bibliography, extracted_pages=extracted_pages, cover_url=f'/static/thumbnails/{book_id}/page_1.png', zb_extra=zb_extra)

@app.route('/view-pdf/<int:book_id>')
def view_as_pdf(book_id):
    return redirect(url_for('api_v1.download_book', book_id=book_id))

@app.route('/open/<path:filepath>')
def open_file(filepath):
    try:
        book = library_service.get_book_by_path(filepath)
        if book:
            file_path, error = library_service.get_file_for_serving(book['id'])
            if not error: return send_from_directory(file_path.parent, file_path.name)
        
        abs_path = (LIBRARY_ROOT / filepath).resolve()
        if abs_path.suffix.lower() == '.pdf': return send_from_directory(abs_path.parent, abs_path.name)
        
        if abs_path.suffix.lower() == '.djvu':
            cache_dir = Path(app.root_path) / "static/cache/pdf"
            cache_dir.mkdir(parents=True, exist_ok=True)
            import hashlib
            file_hash = hashlib.md5(str(abs_path).encode()).hexdigest()
            pdf_path = cache_dir / f"legacy_{file_hash}.pdf"
            if not pdf_path.exists():
                subprocess.run(['ddjvu', '-format=pdf', str(abs_path), str(pdf_path)], check=True, stderr=subprocess.DEVNULL)
            return send_from_directory(cache_dir, pdf_path.name)
            
        return "Unsupported type or access denied", 400
    except Exception as e: return str(e), 500

@app.route('/notes')
def list_notes():
    source_type = request.args.get('type')
    query = request.args.get('q')
    sort = request.args.get('sort', 'newest')
    
    if query:
        notes = note_service.search_notes(query, limit=100)
    else:
        notes = note_service.list_notes(source_type=source_type, limit=100)
        
    # Apply manual sorting if needed (beyond DB default)
    if sort == 'alphabetical':
        notes.sort(key=lambda x: x['title'].lower())
    elif sort == 'oldest':
        notes.sort(key=lambda x: x['created_at'])
    
    return render_template('notes.html', notes=notes, current_type=source_type, current_sort=sort, query=query)

@app.route('/note/<int:note_id>/delete', methods=['POST'])
def delete_note(note_id):
    if note_service.delete_note(note_id):
        return jsonify({"success": True})
    return jsonify({"success": False}), 400

@app.route('/note/<int:note_id>/edit', methods=['POST'])
def edit_note(note_id):
    data = request.json
    if not data: return jsonify({"success": False}), 400
    
    # Update Metadata
    note_service.update_note_metadata(note_id, data)
    
    # Update Content if provided
    if 'content' in data:
        note_service.update_note_content(note_id, markdown_content=data['content'])
        
    return jsonify({"success": True})

@app.route('/pdf-note/<int:note_id>')
def serve_note_pdf(note_id):
    note = note_service.get_note(note_id)
    if not note or not note.get('pdf_path'):
        abort(404)
    
    pdf_path = Path(note['pdf_path'])
    if not pdf_path.exists():
        abort(404)
        
    return send_file(str(pdf_path), mimetype='application/pdf')

@app.route('/note/<int:note_id>/save', methods=['POST'])
def save_note_latex(note_id):
    data = request.json
    if not data or 'latex' not in data:
        return jsonify({"success": False, "error": "Missing LaTeX content"}), 400
    
    # 1. Update the .tex file on disk
    if note_service.update_note_content(note_id, latex_content=data['latex']):
        # 2. Trigger re-compilation
        from services.compilation import compilation_service
        res = compilation_service.compile_note(note_id)
        return jsonify(res)
    
    return jsonify({"success": False, "error": "Failed to save LaTeX file"}), 500

@app.route('/note/<int:note_id>/reprocess', methods=['POST'])
def reprocess_note_route(note_id):
    data = request.json
    if not data or 'mode' not in data:
        return jsonify({"success": False, "error": "Missing target mode"}), 400
        
    res = note_service.reprocess_note(note_id, data['mode'])
    return jsonify(res)

@app.route('/note/<int:note_id>/extract-solution', methods=['POST'])
def extract_solution_route(note_id):
    res = note_service.extract_master_solution(note_id)
    return jsonify(res)

@app.route('/note/<int:note_id>')
def view_note_by_id(note_id):
    note = note_service.get_note(note_id)
    if not note: abort(404)
    
    latex_content = ""
    if note.get('latex_path'):
        full_path = Path(note['latex_path'])
        if full_path.exists():
            with open(full_path, 'r', encoding='utf-8') as f:
                latex_content = f.read()
            
    return render_template('view_note.html', 
                           note=note, 
                           latex_content=latex_content,
                           has_pdf=note['pdf_path'] and os.path.exists(note['pdf_path']))

@app.route('/view-note/<filename>')
def view_note(filename):
    base_name = os.path.splitext(filename)[0]
    content, notes_dir = None, None
    for d in [NOTES_OUTPUT_DIR, CONVERTED_NOTES_DIR]:
        f = d / filename
        if f.exists():
            with open(f, 'r', encoding='utf-8') as f_obj: content = f_obj.read()
            notes_dir = d
            break
    if not content: return "Not found", 404
    meta = note_service.get_note_metadata(base_name, notes_dir)
    return render_template('view_note.html', filename=filename, content=content, has_pdf=(notes_dir / (base_name + ".pdf")).exists(), pdf_filename=base_name + ".pdf", has_markdown=(notes_dir / (base_name + ".md")).exists(), markdown_filename=base_name + ".md", recommendations=meta.get('recommendations', []))

@app.route('/delete-note/<filename>', methods=['POST'])
def delete_note_file(filename):
    base_name = os.path.splitext(filename)[0]
    note_service.delete_note(base_name)
    return redirect(url_for('list_notes'))

@app.route('/rename-note/<filename>', methods=['POST'])
def rename_note(filename):
    new_name = request.form.get('new_name')
    if not new_name: return redirect(url_for('view_note', filename=filename))
    old_base = os.path.splitext(filename)[0]
    new_base = "".join(x for x in new_name if (x.isalnum() or x in "._- "))
    if note_service.rename_note(old_base, new_base):
        return redirect(url_for('view_note', filename=new_base + ".tex"))
    return redirect(url_for('list_notes'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=False, port=5001)
