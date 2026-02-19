import os
import json
import shutil
import time
from pathlib import Path
from core.database import db
from core.ai import ai
from core.config import LIBRARY_ROOT, UNSORTED_DIR
from services.library import library_service
from services.universal_processor import universal_processor

class IngestorService:
    def __init__(self):
        self.db = db
        self.ai = ai

    def refresh_metadata(self, book_id, ai_care=True):
        """Standard method for UI and manual refresh using the new pipeline."""
        print(f"Triggering Universal Pipeline for Book ID {book_id}...")
        result = universal_processor.process_book(book_id)
        return result

    def process_file(self, file_path: Path, execute=False):
        """Processes a new file from Unsorted into the library using the Universal Pipeline."""
        file_hash = library_service.calculate_hash(file_path)
        
        # 1. Duplicate check
        dup_type, dup_match = library_service.check_duplicate(file_hash)
        if dup_type == "HASH":
            return {"status": "duplicate", "type": "HASH", "match": dup_match}

        if not execute:
            # For dry-run, we use a lightweight scan to show a plan
            # (We don't want to run the full expensive pipeline for a preview)
            return {"status": "plan", "target": f"Auto-Rename based on AI", "file": file_path.name}

        # 2. Create Shell Entry to get an ID
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO books (filename, path, file_hash, last_modified)
                VALUES (?, ?, ?, unixepoch())
            """, (file_path.name, f"TEMP_INGEST/{file_path.name}", file_hash))
            book_id = cursor.lastrowid

        # 3. Run Universal Pipeline
        pipeline_result = universal_processor.process_book(book_id)
        
        if not pipeline_result['success']:
            # Cleanup shell entry on failure
            with self.db.get_connection() as conn:
                conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
            return {"status": "error", "message": pipeline_result.get('error')}

        # 4. Final Routing based on AI metadata
        data = pipeline_result['data']['metadata']
        target_folder = data.get('target_path') or "99_General_and_Diverse/Unsorted"
        
        safe_title = "".join(c for c in data['title'] if c.isalnum() or c in " -_").strip()[:100]
        safe_author = "".join(c for c in data.get('author', 'Unknown') if c.isalnum() or c in " -_").strip()[:50]
        dest_name = f"{safe_author} - {safe_title}{file_path.suffix.lower()}"
        
        target_rel_path = Path(target_folder) / dest_name
        target_abs = LIBRARY_ROOT / target_rel_path
        
        # Ensure directory exists
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        
        # 5. Physical Move
        shutil.move(file_path, target_abs)
        
        # 6. Final DB Update with correct path
        with self.db.get_connection() as conn:
            conn.execute("UPDATE books SET path = ?, directory = ?, filename = ? WHERE id = ?", 
                         (str(target_rel_path), str(target_rel_path.parent), dest_name, book_id))

        return {"status": "success", "path": str(target_rel_path), "metadata": data}

ingestor_service = IngestorService()
