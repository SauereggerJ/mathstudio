from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for, flash, abort
import os
import json
import subprocess
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
import threading
import time

app = Flask(__name__)
app.secret_key = 'supersecretkey'

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
        from services.fuzzy_matcher import FuzzyBookMatcher
        from rapidfuzz import fuzz
        
        with db.get_connection() as conn:
            # 1. Wishlist Cleanup (Check for acquired books)
            wishlist = conn.execute('SELECT id, title, author FROM wishlist WHERE status = "missing"').fetchall()
            library = conn.execute('SELECT id, title, author FROM books').fetchall()
            
            cleaned = 0
            for w in wishlist:
                for b in library:
                    # High intelligence match
                    if fuzz.token_set_ratio(w['title'], b['title']) > 85:
                        conn.execute('UPDATE wishlist SET status = "acquired" WHERE id = ?', (w['id'],))
                        cleaned += 1
                        break
            app.logger.info(f"HOUSEKEEPING: Wishlist cleaned. {cleaned} items marked as acquired.")

            # 2. DOI to Zbl Bridge Refresher
            dois_without_zbl = conn.execute('SELECT id, doi FROM books WHERE doi IS NOT NULL AND (arxiv_id IS NULL OR arxiv_id = "") LIMIT 50').fetchall()
            zbl_found = 0
            for row in dois_without_zbl:
                zbl = zbmath_service.get_zbl_id_from_doi(row['doi'])
                if zbl:
                    conn.execute('UPDATE books SET arxiv_id = ? WHERE id = ?', (zbl, row['id']))
                    zbl_found += 1
            app.logger.info(f"HOUSEKEEPING: Zbl-Bridge refreshed. {zbl_found} new IDs mapped.")

    except Exception as e:
        app.logger.error(f"HOUSEKEEPING: Error during maintenance: {e}")

def enrichment_worker():
    """Background thread to process bibliography and check book metadata (v6-HOUSEKEEPING)."""
    time.sleep(15)
    app.logger.info("Starting MathStudio Enrichment Worker (v6-HOUSEKEEPING)...")
    
    last_housekeeping = 0
    
    while True:
        try:
            now = time.time()
            # Run housekeeping every 12 hours (43200 seconds)
            if now - last_housekeeping > 43200:
                run_housekeeping()
                last_housekeeping = now

            # Regular task: Process a small batch of bibliography entries
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, book_id, raw_text FROM bib_entries 
                    WHERE resolved_zbl_id IS NULL AND confidence IS NULL
                    LIMIT 3
                ''')
                entries = [dict(row) for row in cursor.fetchall()]
            
            for row in entries:
                res = zbmath_service.resolve_citation(row['raw_text'])
                if res and res.get('doi'):
                    with db.get_connection() as conn:
                        conn.execute('UPDATE bib_entries SET resolved_zbl_id = ?, confidence = 1.0 WHERE id = ?', (res['doi'], row['id']))
                else:
                    with db.get_connection() as conn:
                        conn.execute('UPDATE bib_entries SET confidence = -1.0 WHERE id = ?', (row['id'],))

            # Regular task: Propose metadata for one book
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, title, author FROM books 
                    WHERE id NOT IN (SELECT book_id FROM metadata_proposals)
                    AND (doi IS NULL OR doi = '')
                    LIMIT 1
                ''')
                book = cursor.fetchone()
            
            if book:
                res = zbmath_service.resolve_citation(f"{book['title']} {book['author']}")
                if res and res.get('doi'):
                    with db.get_connection() as conn:
                        conn.execute('INSERT INTO metadata_proposals (book_id, field_name, proposed_value, source) VALUES (?, ?, ?, ?)', 
                                     (book['id'], 'doi', res['doi'], 'Background-Auto-Scan'))

            time.sleep(60) # Regular task interval
        except Exception as e:
            app.logger.error(f"Error in enrichment worker: {e}")
            time.sleep(120)

# Register API Blueprint
app.register_blueprint(api_v1, url_prefix='/api/v1')

# Start Background Worker
threading.Thread(target=enrichment_worker, daemon=True).start()

# --- Frontend Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin')
def admin_dashboard():
    return render_template('admin.html')

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
        cursor.execute("""
            SELECT id, filename, path, directory, author, title, publisher, year, isbn, doi, arxiv_id,
                   summary, level, exercises, solutions, msc_code, tags, description, 
                   toc_json, msc_class, audience, has_exercises, has_solutions, page_count 
            FROM books WHERE id = ?
        """, (book_id,))
        book = cursor.fetchone()
        if not book: return "Book not found", 404
        book_dict = dict(book)
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
            SELECT b.*, z.title as zb_title, z.authors as zb_authors, z.msc_code
            FROM bib_entries b
            LEFT JOIN zbmath_cache z ON b.resolved_zbl_id = z.zbl_id
            WHERE b.book_id = ?
            ORDER BY b.id ASC
            LIMIT 50
        """, (book_id,))
        bibliography = [dict(row) for row in cursor.fetchall()]
    update_state("view_book", book_id=book_id, extra={"title": book_dict['title'], "path": str(book_dict['path'])})
    return render_template('book.html', **book_dict, query=query, similar_books=similar_books, chapters=chapters, matches=matches, index_matches=index_matches, bibliography=bibliography, cover_url=f'/static/thumbnails/{book_id}/page_1.png')

@app.route('/view-pdf/<int:book_id>')
def view_as_pdf(book_id):
    return redirect(url_for('api_v1.download_book', book_id=book_id))

@app.route('/open/<path:filepath>')
def open_file(filepath):
    """
    Frontend helper to serve files.
    Prefers book_id-based serving if it can resolve the path.
    """
    try:
        # Try to find the book_id for this path to use consistent cache
        book = library_service.get_book_by_path(filepath)
        if book:
            file_path, error = library_service.get_file_for_serving(book['id'])
            if not error:
                return send_from_directory(file_path.parent, file_path.name)

        # Fallback to direct serving (legacy/direct links)
        abs_path = (LIBRARY_ROOT / filepath).resolve()
        if LIBRARY_ROOT.resolve() not in abs_path.parents and abs_path != LIBRARY_ROOT.resolve():
            return "Access denied", 403
        if not abs_path.exists(): return "File not found", 404
        
        if abs_path.suffix.lower() == '.pdf':
            return send_from_directory(abs_path.parent, abs_path.name)
        
        if abs_path.suffix.lower() == '.djvu':
            # Redirect to the canonical ID-based serving if possible, 
            # or use path-based hash as absolute fallback
            cache_dir = Path(app.root_path) / "static/cache/pdf"
            cache_dir.mkdir(parents=True, exist_ok=True)
            import hashlib
            file_hash = hashlib.md5(str(abs_path).encode()).hexdigest()
            pdf_path = cache_dir / f"legacy_{file_hash}.pdf"
            if not pdf_path.exists():
                subprocess.run(['ddjvu', '-format=pdf', str(abs_path), str(pdf_path)], check=True)
            return send_from_directory(cache_dir, pdf_path.name)
            
        return "Unsupported type", 400
    except Exception as e: return str(e), 500

@app.route('/notes')
def list_notes():
    notes = note_service.list_notes()
    return render_template('notes.html', notes=[n['filename'] for n in notes])

@app.route('/wishlist')
def wishlist_view():
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT w.*, b.title as source_title 
            FROM wishlist w 
            LEFT JOIN books b ON w.source_book_id = b.id 
            ORDER BY w.created_at DESC
        """)
        items = [dict(row) for row in cursor.fetchall()]
    return render_template('wishlist.html', items=items)

@app.route('/wishlist-check')
def wishlist_check():
    return render_template('wishlist_check.html')

@app.route('/delete-note/<filename>', methods=['POST'])
def delete_note(filename):
    base_name = os.path.splitext(filename)[0]
    note_service.delete_note(base_name)
    return redirect(url_for('list_notes'))

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
    app.run(host='0.0.0.0', debug=True, port=5001)

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5001)
