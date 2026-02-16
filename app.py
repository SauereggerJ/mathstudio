from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for, flash
import sys
import os
import json
import sqlite3
import subprocess
from pathlib import Path

from config import DB_FILE, LIBRARY_ROOT, OBSIDIAN_INBOX, NOTES_OUTPUT_DIR, parent_dir
from api_v1 import api_v1
from search import get_book_details, get_book_matches, get_similar_books, get_chapters

app = Flask(__name__)
app.secret_key = 'supersecretkey'

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

@app.route('/book/<int:book_id>')
def book_details(book_id):
    query = request.args.get('q', '')
    book = get_book_details(book_id, query=query)
    if not book:
        return "Book not found", 404
        
    title, author, path, isbn, publisher, year, summary, level, exercises, solutions, ref_url, msc_code, tags, index_text, index_matches = book
    
    matches = []
    if query:
        matches = get_book_matches(book_id, query)
    
    similar_books = get_similar_books(book_id)
    chapters = get_chapters(book_id)
        
    return render_template('book.html', 
        id=book_id,
        title=title, 
        author=author, 
        path=path, 
        isbn=isbn, 
        publisher=publisher, 
        year=year,
        summary=summary,
        level=level,
        exercises=exercises,
        solutions=solutions,
        reference_url=ref_url,
        msc_code=msc_code,
        tags=tags,
        matches=matches,
        query=query,
        similar_books=similar_books,
        chapters=chapters,
        cover_url=f'/static/thumbnails/{book_id}/page_1.png',
        index_matches=index_matches
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
    if not NOTES_OUTPUT_DIR.exists():
        NOTES_OUTPUT_DIR.mkdir()
    
    files = sorted([f.name for f in NOTES_OUTPUT_DIR.glob("*.tex")])
    return render_template('notes.html', notes=files)

@app.route('/wishlist-check')
def wishlist_check():
    return render_template('wishlist_check.html')

@app.route('/api/notes/metadata')
def notes_metadata():
    """Return metadata for all notes from both directories."""
    notes_data = []
    
    # Get converted notes directory
    try:
        from config import parent_dir
        CONVERTED_NOTES_DIR = parent_dir / "converted_notes"
    except:
        from web.config import parent_dir
        CONVERTED_NOTES_DIR = parent_dir / "converted_notes"
    
    # Scan both directories
    directories = []
    if NOTES_OUTPUT_DIR.exists():
        directories.append(NOTES_OUTPUT_DIR)
    if CONVERTED_NOTES_DIR.exists():
        directories.append(CONVERTED_NOTES_DIR)
    
    for notes_dir in directories:
        for tex_file in notes_dir.glob("*.tex"):
            base_name = tex_file.stem
            
            # Get file stats
            stat = tex_file.stat()
            
            # Load metadata from JSON if available
            json_file = notes_dir / f"{base_name}.json"
            metadata = {}
            if json_file.exists():
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        loaded_data = json.load(f)
                        # Ensure metadata is a dict (old files might have arrays)
                        if isinstance(loaded_data, dict):
                            metadata = loaded_data
                        else:
                            # Old format with recommendations array
                            metadata = {}
                except Exception as e:
                    print(f"Error loading metadata for {base_name}: {e}")
                    metadata = {}
            
            # Check for associated files
            pdf_file = notes_dir / f"{base_name}.pdf"
            md_file = notes_dir / f"{base_name}.md"
            
            notes_data.append({
                'filename': tex_file.name,
                'base_name': base_name,
                'title': metadata.get('title', base_name) if isinstance(metadata, dict) else base_name,
            'original_filename': metadata.get('original_filename', '') if isinstance(metadata, dict) else '',
            'created': metadata.get('created', '') if isinstance(metadata, dict) else '',
            'tags': metadata.get('tags', []) if isinstance(metadata, dict) else [],
            'size': stat.st_size,
            'modified': stat.st_mtime,
            'has_pdf': pdf_file.exists(),
            'has_md': md_file.exists(),
            'has_json': json_file.exists()
        })
    
    # Sort by modification time, newest first
    notes_data.sort(key=lambda x: x['modified'], reverse=True)
    
    return jsonify(notes_data)

@app.route('/view-note/<filename>')
def view_note(filename):
    # Check both directories
    file_path = NOTES_OUTPUT_DIR / filename
    notes_dir = NOTES_OUTPUT_DIR
    
    if not file_path.exists():
        # Try converted notes directory
        try:
            from config import parent_dir
            CONVERTED_NOTES_DIR = parent_dir / "converted_notes"
        except:
            from web.config import parent_dir
            CONVERTED_NOTES_DIR = parent_dir / "converted_notes"
        
        file_path = CONVERTED_NOTES_DIR / filename
        notes_dir = CONVERTED_NOTES_DIR
        if not file_path.exists():
            return "Note not found", 404
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    pdf_filename = filename.replace('.tex', '.pdf')
    pdf_path = notes_dir / pdf_filename
    has_pdf = pdf_path.exists()
    
    # Load metadata from sidecar JSON if available
    json_filename = filename.replace('.tex', '.json')
    json_path = notes_dir / json_filename
    recommendations = []
    
    if json_path.exists():
        try:
            with open(json_path, 'r', encoding='utf-8') as jf:
                metadata = json.load(jf)
                # Extract recommendations from metadata dict
                if isinstance(metadata, dict):
                    recommendations = metadata.get('recommendations', [])
                elif isinstance(metadata, list):
                    # Old format: JSON file was just the recommendations array
                    recommendations = metadata
        except Exception as e:
            print(f"Error loading JSON metadata: {e}")
    
    return render_template('view_note.html', 
        filename=filename, 
        content=content, 
        has_pdf=has_pdf, 
        pdf_filename=pdf_filename,
        has_markdown=(notes_dir / filename.replace('.tex', '.md')).exists(),
        markdown_filename=filename.replace('.tex', '.md'),
        recommendations=recommendations
    )

@app.route('/notes/<filename>')
def serve_note(filename):
    """Serve notes from both output directories."""
    # Try NOTES_OUTPUT_DIR first
    if (NOTES_OUTPUT_DIR / filename).exists():
        return send_from_directory(NOTES_OUTPUT_DIR, filename)
    
    # Try CONVERTED_NOTES_DIR
    try:
        from config import parent_dir
        CONVERTED_NOTES_DIR = parent_dir / "converted_notes"
    except:
        from web.config import parent_dir
        CONVERTED_NOTES_DIR = parent_dir / "converted_notes"
    
    if (CONVERTED_NOTES_DIR / filename).exists():
        return send_from_directory(CONVERTED_NOTES_DIR, filename)
    
    # File not found in either directory
    abort(404)

@app.route('/delete-note/<filename>', methods=['POST'])
def delete_note(filename):
    # Base name without extension
    base_name = os.path.splitext(filename)[0]
    
    # Files to try deleting
    files_to_delete = [
        base_name + ".tex",
        base_name + ".pdf",
        base_name + ".json",
        base_name + ".md"
    ]
    
    # Import CONVERTED_NOTES_DIR
    try:
        from config import parent_dir
        CONVERTED_NOTES_DIR = parent_dir / "converted_notes"
    except:
        from web.config import parent_dir
        CONVERTED_NOTES_DIR = parent_dir / "converted_notes"

    deleted = False
    
    # Check both directories
    for notes_dir in [NOTES_OUTPUT_DIR, CONVERTED_NOTES_DIR]:
        for f in files_to_delete:
            try:
                file_path = notes_dir / f
                if file_path.exists():
                    os.remove(file_path)
                    deleted = True
            except Exception as e:
                print(f"Error deleting {f}: {e}")
    
    if deleted:
        flash(f"Note {base_name} deleted successfully.", "success")
    else:
        flash(f"Could not find files to delete for {base_name}.", "warning")
        
    return redirect(url_for('list_notes'))

@app.route('/delete-notes', methods=['POST'])
def delete_notes_bulk():
    """Bulk delete multiple notes at once."""
    data = request.get_json()
    filenames = data.get('filenames', [])
    
    if not filenames:
        return jsonify({'error': 'No filenames provided'}), 400
    
    deleted_count = 0
    failed_count = 0
    errors = []
    
    # Import CONVERTED_NOTES_DIR
    try:
        from config import parent_dir
        CONVERTED_NOTES_DIR = parent_dir / "converted_notes"
    except:
        from web.config import parent_dir
        CONVERTED_NOTES_DIR = parent_dir / "converted_notes"
    
    for filename in filenames:
        try:
            base_name = os.path.splitext(filename)[0]
            files_to_delete = [
                base_name + ".tex",
                base_name + ".pdf",
                base_name + ".json",
                base_name + ".md"
            ]
            
            file_deleted = False
            # Check both directories
            for notes_dir in [NOTES_OUTPUT_DIR, CONVERTED_NOTES_DIR]:
                for f in files_to_delete:
                    file_path = notes_dir / f
                    if file_path.exists():
                        os.remove(file_path)
                        file_deleted = True
            
            if file_deleted:
                deleted_count += 1
            else:
                failed_count += 1
                errors.append(f"No files found for {filename}")
                
        except Exception as e:
            failed_count += 1
            errors.append(f"Error deleting {filename}: {str(e)}")
    
    return jsonify({
        'success': True,
        'deleted': deleted_count,
        'failed': failed_count,
        'errors': errors
    })

@app.route('/rename-note/<filename>', methods=['POST'])
def rename_note(filename):
    new_name = request.form.get('new_name')
    if not new_name:
        flash("New name is required.", "error")
        return redirect(url_for('view_note', filename=filename))
        
    # Sanitize new name (simple check)
    new_name = "".join(x for x in new_name if (x.isalnum() or x in "._- "))
    if not new_name:
        flash("Invalid filename.", "error")
        return redirect(url_for('view_note', filename=filename))
    
    base_old = os.path.splitext(filename)[0]
    
    # Files to rename
    extensions = ['.tex', '.pdf', '.json', '.md']
    
    success = True
    for ext in extensions:
        old_file = NOTES_OUTPUT_DIR / (base_old + ext)
        new_file = NOTES_OUTPUT_DIR / (new_name + ext)
        
        if old_file.exists():
            try:
                os.rename(old_file, new_file)
            except Exception as e:
                print(f"Error renaming {old_file}: {e}")
                success = False
    
    if success:
        flash(f"Renamed to {new_name}", "success")
        return redirect(url_for('view_note', filename=new_name + ".tex"))
    else:
        flash("Some files could not be renamed.", "error")
        return redirect(url_for('list_notes'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5002)