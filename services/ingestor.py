import os
import json
import shutil
import time
import subprocess
from pathlib import Path
import fitz  # PyMuPDF
from core.database import db
from core.ai import ai
from core.config import LIBRARY_ROOT, GEMINI_MODEL, UNSORTED_DIR, DUPLICATES_DIR, IGNORED_FOLDERS
from services.library import library_service

class IngestorService:
    def __init__(self):
        self.db = db
        self.ai = ai

    def extract_structure(self, file_path):
        """Extracts text sample and page count."""
        try:
            if file_path.suffix.lower() == '.pdf':
                doc = fitz.open(file_path)
                page_count = doc.page_count
                head_text = "".join(doc[i].get_text() for i in range(min(20, page_count)))
                toc = doc.get_toc()
                doc.close()
                return {'page_count': page_count, 'text_sample': head_text[:50000], 'toc': toc}
            
            elif file_path.suffix.lower() == '.djvu':
                result = subprocess.run(['djvutxt', str(file_path)], capture_output=True, text=True, check=True)
                pages = result.stdout.split('\f')
                return {
                    'page_count': len(pages), 
                    'text_sample': "".join(pages[:20])[:50000], 
                    'toc': []
                }
        except Exception as e:
            print(f"[Ingestor] Extraction error for {file_path.name}: {e}")
        return None

    def analyze_content(self, structure, existing_folders=None, ai_care=False):
        """Uses AI to determine metadata and target path."""
        care_instruction = "CRITICAL: The previous metadata was poor, be extremely thorough." if ai_care else ""
        
        prompt = (
            "You are a mathematical librarian. Analyze this book fragment (ToC + Start).\n"
            f"{care_instruction}\n"
            "Return a strictly valid JSON object with these keys:\n"
            "- 'title', 'author', 'publisher', 'year' (int), 'isbn', 'msc_class' (e.g. 14A05),\n"
            "- 'target_path': Relative folder path from library root,\n"
            "- 'audience': ['Undergrad', 'Grad', 'Research', 'Popular'],\n"
            "- 'has_exercises', 'has_solutions' (booleans),\n"
            "- 'summary': One sentence summary,\n"
            "- 'description': Richer description,\n"
            "- 'toc': List of objects [{'title': '...', 'page': ...}],\n"
            "- 'page_offset': int (PDF page - Printed page)\n\n"
            f"TOC: {json.dumps(structure.get('toc', [])[:50])}\n"
            f"TEXT: {structure.get('text_sample', '')[:5000]}"
        )
        
        return self.ai.generate_json(prompt)

    def process_file(self, file_path, execute=False, dry_run=True):
        """Processes a single file from ingestion source."""
        print(f"Ingesting: {file_path.name}")
        file_hash = library_service.calculate_hash(file_path)
        
        # Duplicate check
        dup_type, dup_match = library_service.check_duplicate(file_hash)
        if dup_type == "HASH":
            return {"status": "duplicate", "type": "HASH", "match": dup_match}

        structure = self.extract_structure(file_path)
        if not structure:
            return {"status": "error", "message": "Structure extraction failed"}

        ai_data = self.analyze_content(structure)
        if not ai_data:
            return {"status": "error", "message": "AI analysis failed"}

        # Routing logic (Simplified for service)
        target_folder = ai_data.get('target_path') or "99_General_and_Diverse"
        safe_title = "".join(c for c in ai_data['title'] if c.isalnum() or c in " -_").strip()
        safe_author = "".join(c for c in ai_data.get('author', '') if c.isalnum() or c in " -_").strip()
        dest_name = f"{safe_author} - {safe_title}{file_path.suffix.lower()}"
        
        target_rel_path = Path(target_folder) / dest_name
        
        if execute:
            target_abs = LIBRARY_ROOT / target_rel_path
            target_abs.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(file_path, target_abs)
            
            # Save to DB
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO books (
                        filename, path, directory, author, title, publisher, year, isbn,
                        file_hash, toc_json, msc_class, audience, 
                        has_exercises, has_solutions, page_count, summary, description,
                        index_version, last_modified
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    dest_name, str(target_rel_path), str(target_rel_path.parent),
                    ai_data.get('author'), ai_data['title'], ai_data.get('publisher'),
                    ai_data.get('year'), ai_data.get('isbn'), file_hash,
                    json.dumps(ai_data.get('toc', [])), ai_data.get('msc_class'),
                    ai_data.get('audience'), ai_data.get('has_exercises', False),
                    ai_data.get('has_solutions', False), structure['page_count'],
                    ai_data.get('summary'), ai_data.get('description'),
                    1, time.time()
                ))
            return {"status": "success", "path": str(target_rel_path)}
        
        return {"status": "plan", "target": str(target_rel_path), "metadata": ai_data}

# Global instance
ingestor_service = IngestorService()
