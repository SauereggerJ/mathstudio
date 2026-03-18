import os
import json
import shutil
import time
from pathlib import Path
from typing import Dict, Any
from core.database import db
from core.ai import ai
from core.config import LIBRARY_ROOT, UNSORTED_DIR
from services.library import library_service
from services.universal_processor import universal_processor
from services.zbmath import zbmath_service
from services.search import search_service
from services.indexer import indexer_service

class IngestorService:
    def __init__(self):
        self.db = db
        self.ai = ai

    def refresh_metadata(self, book_id, ai_care=True):
        """Standard method for UI and manual refresh using the new pipeline."""
        print(f"Triggering Universal Pipeline for Book ID {book_id}...")
        result = universal_processor.process_book(book_id, save_to_db=True)
        # Deep Enrichment
        try:
            zbmath_service.enrich_book(book_id)
            # Vectorize and Deep Index
            search_service.vectorize_book(book_id)
            indexer_service.deep_index_book(book_id)
        except Exception as e:
            print(f"Post-Enrichment Warning (zbMATH/Vector/FTS): {e}")
        return result

    def preview_metadata_update(self, book_id, ai_care=True):
        """Runs the Universal Pipeline in PREVIEW mode (no DB changes)."""
        print(f"Generating Metadata Preview for Book ID {book_id}...")
        result = universal_processor.process_book(book_id, save_to_db=False)
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
        # Calculate relative path from LIBRARY_ROOT for the DB
        rel_src_path = file_path.relative_to(LIBRARY_ROOT)
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO books (filename, path, file_hash, last_modified)
                VALUES (?, ?, ?, unixepoch())
            """, (file_path.name, str(rel_src_path), file_hash))
            book_id = cursor.lastrowid

        # 3. Run Universal Pipeline
        pipeline_result = universal_processor.process_book(book_id)
        
        if not pipeline_result['success']:
            # Cleanup shell entry on failure
            with self.db.get_connection() as conn:
                conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
            return {"status": "error", "message": pipeline_result.get('error')}

        # 3b. Deep Enrichment (zbMATH)
        try:
            zbmath_service.enrich_book(book_id)
        except Exception as e:
            print(f"Post-Enrichment Warning (zbMATH): {e}")

        # 4. Final Routing based on Enriched Metadata
        with self.db.get_connection() as conn:
            db_data = conn.execute("SELECT title, author, msc_class FROM books WHERE id = ?", (book_id,)).fetchone()
        
        # Merge AI data with DB data for routing
        data = pipeline_result['data']['metadata']
        title = db_data['title'] or data.get('title')
        author = db_data['author'] or data.get('author', 'Unknown')
        
        target_folder = data.get('target_path') or "99_General_and_Diverse/Unsorted"
        
        safe_title = "".join(c for c in title if c.isalnum() or c in " -_").strip()[:100]
        safe_author = "".join(c for c in author if c.isalnum() or c in " -_").strip()[:50]
        dest_name = f"{safe_author} - {safe_title}{file_path.suffix.lower()}"
        
        target_rel_path = Path(target_folder) / dest_name
        target_abs = LIBRARY_ROOT / target_rel_path
        
        # Ensure directory exists
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        
        # 5. Physical Move
        shutil.move(file_path, target_abs)
        
        # 6. Final DB Update and Heavy Indexing
        try:
            # Update path first so indexer can find it
            with self.db.get_connection() as conn:
                conn.execute("UPDATE books SET path = ?, directory = ?, filename = ? WHERE id = ?", 
                             (str(target_rel_path), str(target_rel_path.parent), dest_name, book_id))
            
            # Now run the heavy indexing (FTS and Vector)
            print(f"Starting Deep Indexing and Vectorization for Book {book_id}...")
            indexer_service.deep_index_book(book_id)
            search_service.vectorize_book(book_id)
        except Exception as e:
            print(f"Post-Move Indexing Warning (FTS/Vector): {e}")

        return {"status": "success", "path": str(target_rel_path), "metadata": data}

    def run_review_round(self, time_window_seconds=3600) -> Dict[str, Any]:
        """
        Performs a verification round on recently ingested/updated books.
        Checks for missing MSC, low trust scores, and zbMATH status.
        """
        with self.db.get_connection() as conn:
            recent_books = conn.execute("""
                SELECT id, title, author, msc_class, metadata_status, trust_score, zbl_id 
                FROM books 
                WHERE last_metadata_refresh > (unixepoch() - ?)
            """, (time_window_seconds,)).fetchall()
        
        report = {
            "total_reviewed": len(recent_books),
            "perfect_count": 0,
            "perfect_books": [],
            "issues": []
        }
        
        for book in recent_books:
            book_issues = []
            if not book['zbl_id']:
                book_issues.append("Missing Zbl ID (zbMATH link failed)")
            if not book['msc_class']:
                book_issues.append("Missing MSC Classification")
            if book['trust_score'] and book['trust_score'] < 0.8:
                book_issues.append(f"Low Trust Score ({book['trust_score']:.2f})")
            if book['metadata_status'] == 'conflict':
                book_issues.append("Metadata Conflict (AI vs zbMATH mismatch)")
                
            if not book_issues:
                report["perfect_count"] += 1
                report["perfect_books"].append({
                    "id": book['id'],
                    "title": book['title'],
                    "msc": book['msc_class']
                })
            else:
                report["issues"].append({
                    "id": book['id'],
                    "title": book['title'],
                    "errors": book_issues
                })
        
        return report

ingestor_service = IngestorService()
