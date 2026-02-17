from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for, flash, abort
import sys
import os
import json
import sqlite3
import subprocess
from pathlib import Path

from core.config import DB_FILE, LIBRARY_ROOT, OBSIDIAN_INBOX, NOTES_OUTPUT_DIR, CONVERTED_NOTES_DIR
from core.database import db
from api_v1 import api_v1
from services.search import search_service
from services.library import library_service
from services.note import note_service

app = Flask(__name__)
app.secret_key = 'supersecretkey'

STATE_FILE = Path(__file__).parent / "current_state.json"

def update_state(action, book_id=None, extra=None):
    """Updates the global system state for Gemini CLI awareness."""
    state = {
        "action": action,
        "book_id": book_id,
        "timestamp": os.popen('date -Iseconds').read().strip(),
        "extra": extra or {}
    }
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        app.logger.error(f"Failed to update state: {e}")

# Register API Blueprint
app.register_blueprint(api_v1, url_prefix='/api/v1')

# --- Frontend Routes ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin')
def admin_dashboard():
    """Renders the Admin Dashboard."""
    return render_template('admin.html')

# Legacy redirects (Optional, for backward compatibility)
@app.route('/api/search')
def legacy_search():
    return redirect(url_for('api_v1.search_endpoint', **request.args))

@app.route('/book/<int:book_id>/edit')
def edit_book(book_id):
    """Renders the metadata editor for a book."""
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
        cursor.execute("SELECT * FROM books WHERE id = ?", (book_id,))
        book = cursor.fetchone()
        if not book: return "Book not found", 404
        
        book_dict = dict(book)
        
        # Similar & Chapters
        from search import get_similar_books, get_chapters, get_book_matches
        similar_books = get_similar_books(book_id)
        chapters = get_chapters(book_id)
        
        matches = []
        if query:
            matches = get_book_matches(book_id, query)
            
        index_matches = None
        if query and book_dict.get('index_text'):
            index_matches = search_service.extract_index_pages(book_dict['index_text'], query)

    # Update system state for Gemini CLI awareness
    update_state("view_book", book_id=book_id, extra={"title": book_dict['title'], "path": str(book_dict['path'])})
        
    return render_template('book.html', 
        **book_dict,
        query=query,
        similar_books=similar_books,
        chapters=chapters,
        matches=matches,
        index_matches=index_matches,
        cover_url=f'/static/thumbnails/{book_id}/page_1.png'
    )

@app.route('/view-pdf/<int:book_id>')
def view_as_pdf(book_id):
    """UI Helper to view PDF (Proxy to API download)."""
    return redirect(url_for('api_v1.download_book', book_id=book_id))

@app.route('/open/<path:filepath>')
def open_file(filepath):
    """Open a file directly by its library path."""
    try:
        # Resolve the full path
        abs_path = (LIBRARY_ROOT / filepath).resolve()
        
        # Security check: ensure the path is within LIBRARY_ROOT
        if LIBRARY_ROOT.resolve() not in abs_path.parents and abs_path != LIBRARY_ROOT.resolve():
            return "Access denied: Path outside library", 403
        
        if not abs_path.exists():
            return f"File not found: {filepath}", 404
        
        # For PDF files, serve directly
        if abs_path.suffix.lower() == '.pdf':
            return send_from_directory(abs_path.parent, abs_path.name)
        
        # For DjVu files, convert to PDF on the fly
        if abs_path.suffix.lower() == '.djvu':
            cache_dir = Path(app.root_path) / "static/cache/pdf"
            if not cache_dir.exists():
                cache_dir.mkdir(parents=True)
            
            # Use a hash of the filepath for the cache filename
            import hashlib
            file_hash = hashlib.md5(str(abs_path).encode()).hexdigest()
            pdf_filename = f"{file_hash}.pdf"
            pdf_path = cache_dir / pdf_filename
            
            # Convert if not already cached
            if not pdf_path.exists():
                subprocess.run(['ddjvu', '-format=pdf', str(abs_path), str(pdf_path)], check=True)
            
            return send_from_directory(cache_dir, pdf_filename)
        
        return f"Unsupported file type: {abs_path.suffix}", 400
        
    except Exception as e:
        return f"Error opening file: {str(e)}", 500

@app.route('/notes')
def list_notes():
    notes = note_service.list_notes()
    return render_template('notes.html', notes=[n['filename'] for n in notes])

@app.route('/wishlist-check')
def wishlist_check():
    return render_template('wishlist_check.html')

@app.route('/api/notes/metadata')
def notes_metadata():
    return jsonify(note_service.list_notes())

@app.route('/delete-note/<filename>', methods=['POST'])
def delete_note(filename):
    base_name = os.path.splitext(filename)[0]
    if note_service.delete_note(base_name):
        flash(f"Note {base_name} deleted.", "success")
    else:
        flash(f"Could not delete {base_name}.", "warning")
    return redirect(url_for('list_notes'))

@app.route('/view-note/<filename>')
def view_note(filename):
    base_name = os.path.splitext(filename)[0]
    
    # Search for the file
    content = None
    notes_dir = None
    for d in [NOTES_OUTPUT_DIR, CONVERTED_NOTES_DIR]:
        f = d / filename
        if f.exists():
            with open(f, 'r', encoding='utf-8') as f_obj:
                content = f_obj.read()
            notes_dir = d
            break
            
    if not content: return "Note not found", 404
    
    meta = note_service.get_note_metadata(base_name, notes_dir)
    
    return render_template('view_note.html', 
        filename=filename, 
        content=content, 
        has_pdf=(notes_dir / (base_name + ".pdf")).exists(),
        pdf_filename=base_name + ".pdf",
        has_markdown=(notes_dir / (base_name + ".md")).exists(),
        markdown_filename=base_name + ".md",
        recommendations=meta.get('recommendations', [])
    )

@app.route('/rename-note/<filename>', methods=['POST'])
def rename_note(filename):
    new_name = request.form.get('new_name')
    if not new_name:
        flash("New name is required.", "error")
        return redirect(url_for('view_note', filename=filename))
    
    old_base = os.path.splitext(filename)[0]
    new_base = "".join(x for x in new_name if (x.isalnum() or x in "._- "))
    
    if note_service.rename_note(old_base, new_base):
        flash(f"Renamed to {new_base}", "success")
        return redirect(url_for('view_note', filename=new_base + ".tex"))
    else:
        flash("Rename failed.", "error")
        return redirect(url_for('list_notes'))

@app.route('/delete-notes', methods=['POST'])
def delete_notes_bulk():
    data = request.get_json()
    filenames = data.get('filenames', [])
    deleted = 0
    for f in filenames:
        if note_service.delete_note(os.path.splitext(f)[0]):
            deleted += 1
    return jsonify({'success': True, 'deleted': deleted})

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5001)