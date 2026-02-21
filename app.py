from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for, flash, abort
import os
import json
import subprocess
import threading
import time
from pathlib import Path
from datetime import datetime

from core.config import DB_FILE, LIBRARY_ROOT, OBSIDIAN_INBOX, NOTES_OUTPUT_DIR, CONVERTED_NOTES_DIR
from core.database import db
from api_v1 import api_v1
from services.search import search_service
from services.library import library_service
from services.note import note_service
from services.zbmath import zbmath_service
from core.ai import ai

app = Flask(__name__)
app.secret_key = 'supersecretkey'

@app.template_filter('from_json')
def from_json_filter(value):
    try:
        return json.loads(value)
    except:
        return []

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

def enrichment_worker():
    """Background thread for automated tasks (temporarily idling for batch operations)."""
    time.sleep(15)
    app.logger.info("Enrichment Worker started (IDLE MODE).")
    while True:
        # Idle loop to prevent DB locking during massive manual batch enrichment
        time.sleep(60)

# Register API
app.register_blueprint(api_v1, url_prefix='/api/v1')

# Start Worker
threading.Thread(target=enrichment_worker, daemon=True).start()

# --- Frontend Routes ---

@app.route('/')
def index(): return render_template('index.html')

@app.route('/admin')
def admin_dashboard(): return render_template('admin.html')

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
                   msc_class AS msc_code, tags, description, toc_json, audience, page_count 
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

    update_state("view_book", book_id=book_id, extra={"title": book_dict['title'], "path": str(book_dict['path'])})
    return render_template('book.html', **book_dict, query=query, similar_books=similar_books, chapters=chapters, matches=matches, index_matches=index_matches, bibliography=bibliography, cover_url=f'/static/thumbnails/{book_id}/page_1.png', zb_extra=zb_extra)

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
    notes = note_service.list_notes()
    return render_template('notes.html', notes=[n['filename'] for n in notes])

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
def delete_note(filename):
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

@app.route('/wishlist')
def wishlist_view():
    with db.get_connection() as conn:
        items = [dict(r) for r in conn.execute("SELECT w.*, b.title as source_title FROM wishlist w LEFT JOIN books b ON w.source_book_id = b.id ORDER BY w.created_at DESC").fetchall()]
    return render_template('wishlist.html', items=items)

@app.route('/wishlist-check')
def wishlist_check():
    return render_template('wishlist_check.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5001)
