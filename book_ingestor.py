import os
import sys
import json
import shutil
import hashlib
import time
import re
import subprocess
from pathlib import Path
import sqlite3
import fitz  # PyMuPDF
from google import genai
from google.genai import types

# --- CONFIGURATION ---
LIBRARY_ROOT = Path("..")  # Relative to mathstudio/
DB_FILE = "library.db"
GEMINI_MODEL = "gemini-2.5-flash-lite-preview-09-2025"
UNSORTED_DIR = LIBRARY_ROOT / "99_General_and_Diverse" / "Unsorted"
DUPLICATES_DIR = LIBRARY_ROOT / "_Admin" / "Duplicates"

# Folders to completely ignore during structure scan
IGNORED_FOLDERS = {
    'mathstudio', '_Admin', 'gemini', '.gemini', '.git', '.venv', 
    'notes_output', 'archive', 'lost+found', '__pycache__'
}

# Admin Compatibility
BATCH_CSV = LIBRARY_ROOT / "_Admin" / "batch_import.csv"

# API Key Loader
def load_api_key():
    try:
        with open("credentials.json", "r") as f:
            creds = json.load(f)
            return creds.get("GEMINI_API_KEY")
    except FileNotFoundError:
        print("Error: credentials.json not found.")
        sys.exit(1)

GEMINI_API_KEY = load_api_key()
client = genai.Client(api_key=GEMINI_API_KEY)

class BookIngestor:
    def __init__(self, dry_run=False, execute=False, calibre_lib=None):
        self.dry_run = dry_run
        self.execute_mode = execute
        self.calibre_lib = calibre_lib
        # Execute implies NOT dry_run
        if self.execute_mode: self.dry_run = False
            
        self.conn = sqlite3.connect(DB_FILE)
        self.ensure_db_schema()

    def ensure_db_schema(self):
        """Ensures the new columns exist in the database."""
        # This acts as a secondary check to indexer.py
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(books)")
        columns = [info[1] for info in cursor.fetchall()]
        
        required_cols = {
            'file_hash': 'TEXT',
            'toc_json': 'TEXT',
            'msc_class': 'TEXT',
            'audience': 'TEXT',
            'has_exercises': 'BOOLEAN',
            'has_solutions': 'BOOLEAN',
            'page_count': 'INTEGER'
        }
        
        for col, dtype in required_cols.items():
            if col not in columns:
                try:
                    cursor.execute(f"ALTER TABLE books ADD COLUMN {col} {dtype}")
                    print(f"[DB] Added column: {col}")
                except Exception:
                    pass
        self.conn.commit()

    def calculate_hash(self, file_path):
        """Calculates SHA256 hash of a file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def check_duplicate(self, file_hash, title, author):
        """Checks for existing file via Hash or Semantic (Title/Author) match."""
        cursor = self.conn.cursor()
        
        # 1. Exact Hash Match
        cursor.execute("SELECT id, path FROM books WHERE file_hash = ?", (file_hash,))
        exact_match = cursor.fetchone()
        if exact_match:
            # Check if file actually exists
            db_id, db_path = exact_match
            full_path = LIBRARY_ROOT / db_path
            
            exists = False
            try:
                # Use os.path.exists as it might be safer or we can check length
                if len(str(full_path)) < 4096: # OS limit usually
                     exists = full_path.exists()
            except OSError as e:
                # [Errno 36] File name too long
                if e.errno == 36:
                    print(f"  [DB] Stale entry found with too long path: {db_path}")
                else:
                    print(f"  [DB] OSError checking path {db_path}: {e}")
            
            if exists:
                # SPECIAL CASE: If the duplicate is in Unsorted, it's not a real duplicate
                # It's a file that needs to be moved to its proper home.
                if "99_General_and_Diverse/Unsorted" in db_path:
                    print(f"  [DB] Hash match in Unsorted ({db_path}). Ignoring duplicate check to allow re-ingestion.")
                    return None, None
                return "HASH", exact_match
            else:
                print(f"  [DB] Hash match (ID {db_id}) but file missing or long-path stale at {db_path}. Cleaning up.")
                # Delete stale entry to avoid confusion
                cursor.execute("DELETE FROM books WHERE id = ?", (db_id,))
                self.conn.commit()
        
        # 2. Semantic Match (Simple fuzzy via SQL LIKE for speed, can be improved)
        if title:
             # Very basic normalization
             clean_title = title.lower().replace(":", "").split()[0] # First word match
             if len(clean_title) > 4:
                 cursor.execute("SELECT id, path, title FROM books WHERE title LIKE ? AND author LIKE ?", (f"%{clean_title}%", f"%{author}%" if author else "%"))
                 semantic_match = cursor.fetchone()
                 if semantic_match:
                     return "SEMANTIC", semantic_match
                     
        return None, None

    def get_all_folders(self, root_path, max_depth=3):
        """Scans for existing category folders, excluding system dirs."""
        folders = []
        root = Path(root_path).resolve()
        
        # We want relative paths from LIBRARY_ROOT
        # But root_path IS LIBRARY_ROOT usually.
        
        for dirpath, dirnames, filenames in os.walk(root):
            # Filtering in-place to prevent traversing ignored dirs
            dirnames[:] = [
                d for d in dirnames 
                if d not in IGNORED_FOLDERS 
                and not d.startswith('.') 
                and not d.startswith('_')
            ]
            
            rel_path = Path(dirpath).relative_to(root)
            depth = len(rel_path.parts)
            
            if depth >= max_depth:
                dirnames.clear() # Stop deeper traversal
                continue
                
            if str(rel_path) == ".": continue
            
            # Only include relevant category folders (starts with digit 0-9)
            # Top level checks
            if depth == 1:
                if not rel_path.name[0].isdigit():
                    continue

            folders.append(str(rel_path))
            
        return sorted(folders)

    def truncate_filename(self, filename, max_len=240):
        """Truncates filename while preserving extension."""
        if len(filename) <= max_len:
            return filename
            
        p = Path(filename)
        ext = p.suffix
        stem = p.stem
        
        # Calculate available space for stem
        available = max_len - len(ext)
        if available < 10: # Safety
             return filename[:max_len]
             
        return stem[:available] + ext

    def extract_structure(self, file_path):
        """Extracts structure (Text, ToC, Page Count) from PDF or DjVu."""
        try:
            if file_path.suffix.lower() == '.pdf':
                return self.extract_structure_pdf(file_path)
            elif file_path.suffix.lower() == '.djvu':
                return self.extract_structure_djvu(file_path)
            return None
        except Exception as e:
            print(f"Error extracting structure from {file_path.name}: {e}")
            return None

    def extract_structure_pdf(self, file_path):
        """Original PDF extraction logic using PyMuPDF."""
        try:
            doc = fitz.open(file_path)
            metadata = doc.metadata
            page_count = doc.page_count
            toc = doc.get_toc()
            
            # Extract first 20 pages for AI context (ToC detection)
            head_text = ""
            for i in range(min(20, page_count)):
                head_text += doc[i].get_text() + "\n"
                
            return {
                'page_count': page_count,
                'toc': toc,
                'text_sample': head_text[:50000],
                'metadata': metadata
            }
        except Exception as e:
            print(f"Error reading PDF {file_path.name}: {e}")
            return None

    def extract_structure_djvu(self, file_path):
        """Extracts text and page count from DjVu code using djvutxt."""
        try:
            result = subprocess.run(['djvutxt', str(file_path)], capture_output=True, text=True, check=True)
            full_text = result.stdout
            
            # Count pages by form feed character '\f'
            pages = full_text.split('\f')
            page_count = len(pages)
            
            # Take first 20 pages
            text_sample = ""
            for i in range(min(20, len(pages))):
                text_sample += pages[i] + "\n"
                
            return {
                "toc": [], # No easy ToC for DjVu
                "text_sample": text_sample[:50000],
                "page_count": page_count,
                "metadata": {}
            }
        except subprocess.CalledProcessError as e:
            print(f"Error running djvutxt on {file_path.name}: {e}")
            return None
        except Exception as e:
            print(f"Error extracting DjVu structure: {e}")
            return None

    def analyze_semantics(self, structure_data, existing_folders=[]):
        """Uses Gemini 2.5 to analyze the book content and select folder."""
        if not structure_data: return None
        
        prompt = (
            "You are a mathematical librarian. Analyze this book fragment (ToC + Start).\n"
            "Return a strictly valid JSON object with these keys:\n"
            "- 'title': Corrected Title\n"
            "- 'author': Corrected Author(s)\n"
            "- 'msc_class': Top-level MSC Code (e.g., 'Linear Algebra', 'Analysis', 'Logic')\n"
            "- 'target_path': The BEST relative folder path. Use existing folders or suggest a new specific one.\n"
            "- 'audience': One of ['Undergrad', 'Grad', 'Research', 'Popular']\n"
            "- 'has_exercises': boolean\n"
            "- 'has_solutions': boolean\n"
            "- 'summary': One sentence content summary.\n\n"
            "CRITICAL: Do NOT use '99_General_and_Diverse/Unsorted' as a target_path. "
            "If no specific category fits, use '99_General_and_Diverse' directly. "
            "If it is a broad subject like 'History of Mathematics', suggest a new specific folder (e.g. '00_History_and_Biography').\n\n"
            "EXISTING FOLDERS:\n"
            f"{json.dumps(existing_folders[:500])}\n\n"
            f"TOC: {structure_data['toc'][:50]}\n" # Limit ToC token usage
            f"TEXT: {structure_data['text_sample'][:5000]}" # Limit text sample
        )
        
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            return json.loads(response.text)
        except Exception as e:
            print(f"AI Analysis Error: {e}")
            return None

    def add_to_calibre(self, file_path, title, author, category):
        """Adds the book to Calibre library via calibredb."""
        if not self.calibre_lib: return

        tags = [category] if category else []
        cmd = [
            "calibredb", "add",
            "--library-path", self.calibre_lib,
            "--title", title,
            "--authors", author,
            "--tags", ",".join(tags),
            str(file_path)
        ]
        
        try:
            # Check if calibredb exists
            subprocess.run(["calibredb", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            
            print(f"  [Calibre] Importing...")
            subprocess.run(cmd, stdout=subprocess.DEVNULL, check=True)
            print(f"  [Calibre] Success.")
        except FileNotFoundError:
            print("  [Calibre Error] 'calibredb' executable not found.")
        except subprocess.CalledProcessError as e:
            print(f"  [Calibre Error] Import failed: {e}")
        except Exception as e:
            print(f"  [Calibre Error] Unexpected: {e}")

    def map_category_to_folder(self, msc_class):
        """Maps AI-detected category to existing folder structure."""
        # Simple mapping based on your directory list
        mapping = {
            'Mathematical Physics': '01_Mathematical_Physics',
            'Physics': '01_Mathematical_Physics',
            'Analysis': '02_Analysis_and_Operator_Theory',
            'Operator Theory': '02_Analysis_and_Operator_Theory',
            'Geometry': '03_Geometry_and_Topology',
            'Topology': '03_Geometry_and_Topology',
            'Algebra': '04_Algebra',
            'Number Theory': '04_Algebra',
            'Probability': '05_Probability_and_Stochastics',
            'Stochastics': '05_Probability_and_Stochastics',
            'Logic': '07_Logic_and_Foundations',
            'Foundations': '07_Logic_and_Foundations',
            'Set Theory': '07_Logic_and_Foundations',
            'Numerics': '08_Applied_Mathematics_and_Numerics',
            'Applied Mathematics': '08_Applied_Mathematics_and_Numerics'
        }
        
        if msc_class:
            for key, folder in mapping.items():
                if key.lower() in msc_class.lower():
                    return folder
        
        return "99_General_and_Diverse"

    def reprocess_book(self, book_id, ai_care=True):
        """
        Forces a re-ingestion of a specific book, optionally with 'AI Care' mode.
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT path, author, title FROM books WHERE id = ?", (book_id,))
        result = cursor.fetchone()
        
        if not result:
            return {"success": False, "error": f"Book ID {book_id} not found."}
            
        db_path, old_author, old_title = result
        
        # Handle relative paths from DB
        full_path = LIBRARY_ROOT / db_path
        if not full_path.exists():
             if Path(db_path).exists():
                 full_path = Path(db_path)
             else:
                 return {"success": False, "error": f"File not found on disk: {db_path}"}
                 
        print(f"Reprocessing book: {full_path.name} (AI Care: {ai_care})")
        
        try:
             # 1. Re-extract Structure
             structure = self.extract_structure(full_path)
             if not structure:
                 return {"success": False, "error": "Failed to extract structure from file (PyMuPDF error or corrupt file)."}
             
             # 2. Re-run AI Analysis
             text_sample = structure.get('text_sample', '')
             ai_data = None
             
             if text_sample and len(text_sample.strip()) > 100:
                 ai_data = self.analyze_book_content(text_sample, ai_care=ai_care)
             
             if not ai_data:
                 return {"success": False, "error": "AI Analysis failed (likely Rate Limit or Model overload). Please try again in a few minutes."}
                 # Fallback: Parse filename
                 # Try to extract Title - Author from "Title - Author.pdf"
                 p = full_path
                 stem = p.stem # "Analysis - Lieb & Loss"
                 
                 parts = stem.split(' - ')
                 if len(parts) >= 2:
                     fallback_title = parts[0].strip()
                     fallback_author = parts[1].strip()
                 else:
                     fallback_title = stem.replace('_', ' ')
                     fallback_author = "Unknown"
                     
                 ai_data = {
                     'title': fallback_title,
                     'author': fallback_author,
                     'description': 'Metadata extracted from filename (Scanned PDF/No Text).',
                     'summary': 'No content analysis available.',
                     'toc': [],
                     'page_offset': 0
                 }

             # 3. Update Database
             # Prepare ToC Data with Offset
             toc_data = ai_data.get('toc') or structure.get('toc', [])
             page_offset = ai_data.get('page_offset', 0)
            
             final_toc = []
             if isinstance(toc_data, list):
                 for item in toc_data:
                     if isinstance(item, dict):
                          try:
                              p = int(item.get('page', 0))
                              item['pdf_page'] = p + page_offset
                              item['level'] = 0 
                          except: pass
                          final_toc.append(item)
                     else:
                         final_toc.append(item)

             cursor.execute("""
                 UPDATE books SET 
                     author = ?, title = ?, 
                     description = ?, summary = ?, 
                     toc_json = ?, page_count = ?, 
                     msc_class = ?, audience = ?, 
                     has_exercises = ?, has_solutions = ?, 
                     last_modified = ? 
                 WHERE id = ?
             """, (
                 ai_data.get('author') or old_author, 
                 ai_data.get('title') or old_title,
                 ai_data.get('description') or '',
                 ai_data.get('summary') or '',
                 json.dumps(final_toc), # AI ToC with Offset
                 structure.get('page_count', 0),
                 ai_data.get('msc_class') or '',
                 ai_data.get('audience') or '',
                 ai_data.get('has_exercises') or 'Nein',
                 ai_data.get('has_solutions') or 'N/A',
                 time.time(),
                 book_id
             ))
             self.conn.commit()
             
             return {
                 "success": True, 
                 "message": f"Successfully re-indexed '{ai_data.get('title', old_title)}'",
                 "data": ai_data
             }
             
        except Exception as e:
            return {"success": False, "error": str(e)}

    def analyze_book_content(self, text_sample, ai_care=False):
        """
        Uses Gemini to analyze book content.
        ai_care=True triggers a more 'thoughtful' prompt.
        """
        care_instruction = ""
        if ai_care:
            care_instruction = """
            CRITICAL: This is a RE-INDEXING request. The previous metadata was poor.
            - CLEAN the Title: Remove 'edition', 'vol', file extensions, or garbage.
            - CLEAN the Author: Remove affiliations, 'edited by', and duplicates.
            - EXTRACT a rich, detailed description.
            """

        prompt = f"""You are a librarian. Analyze this text sample from the start of a math book.
        
        {care_instruction}

        Return a JSON object with:
        - title (string): Clean title.
        - author (string): Clean author list.
        - description (string): Short blurb.
        - summary (string): Key topics.
        - msc_class (string): Likely MSC 2020 code (e.g. 14A05).
        - audience (string): Undergraduate, Graduate, or Research.
        - has_exercises (boolean): True if exercises are mentioned/seen.
        - has_solutions (boolean): True if solutions are mentioned.
        - toc (list of objects): A detected table of contents.
           * Format: [{{"title": "Chapter Name", "page": 5}}, {{"title": "Section 1.2", "page": 12}}, ...]
           * "page" should be the *printed* page number as seen in the text.
           * CRITICAL: Extract meaningful Chapter/Section titles only.
        - page_offset (int): The difference between the PDF page index and the printed page number.
           * Look at the first few pages. If PDF Page 15 says "Page 1", the offset is 14.
           * If PDF Page 5 says "vii", ignore roman numerals and look for "1".

        Text Sample (first 50000 chars):
        {text_sample[:50000]}
        """
        
        try:
            retry_count = 0
            backoff = 5
            response = None
            while retry_count < 5:
                try:
                    print(f"[AI Debug] Sample Length: {len(text_sample)} (Attempt {retry_count+1})", file=sys.stderr)
                    response = client.models.generate_content(
                        model=GEMINI_MODEL,
                        contents=prompt
                    )
                    break
                except Exception as e:
                    if '429' in str(e):
                        print(f"  ⚠️ Rate Limit (429). Waiting {backoff}s...")
                        import time
                        time.sleep(backoff)
                        retry_count += 1
                        backoff *= 2
                        continue
                    raise e
            
            if not response:
                return None

            # Robust JSON extraction
            txt = response.text.strip()
            print(f"[AI Debug] Raw Response: {txt[:500]}...", file=sys.stderr)

            # Try to find JSON block
            match = re.search(r"```json\s*(\{.*?\})\s*```", txt, re.DOTALL)
            if match:
                txt = match.group(1)
            else:
                # Fallback: try to find just a code block
                match = re.search(r"```\s*(\{.*?\})\s*```", txt, re.DOTALL)
                if match:
                    txt = match.group(1)
                else:
                    # Fallback: try to find first { and last }
                    start = txt.find('{')
                    end = txt.rfind('}')
                    if start != -1 and end != -1:
                        txt = txt[start:end+1]
            
            return json.loads(txt)
        except json.JSONDecodeError as e:
            print(f"JSON Error: {e}", file=sys.stderr)
            print(f"Bad JSON Content: {txt}", file=sys.stderr)
            return None
        except Exception as e:
            import traceback
            print(f"AI Analysis Error: {e}", file=sys.stderr)
            traceback.print_exc()
            return None

    def process_folder(self, input_dir):
        """Main processing loop."""
        
        # Scan existing structure once
        print("Scanning existing library structure...")
        existing_folders = self.get_all_folders(LIBRARY_ROOT)
        print(f"Found {len(existing_folders)} existing content folders.")
        
        processed_files = [] 
        csv_rows = []
        
        # Check input directory exists
        path_input = Path(input_dir)
        if not path_input.exists():
             print(f"Input directory not found: {path_input}")
             return

        print(f"Scanning {path_input}...")
        if self.execute_mode:
            print("!!! EXECUTOR MODE ACTIVE: Files will be moved !!!")

        # Scan for both PDF and DjVu
        files = list(path_input.glob("*.pdf")) + list(path_input.glob("*.djvu"))
        print(f"DEBUG: Scanning path: {path_input.resolve()}")
        print(f"DEBUG: Found {len(files)} files (PDF+DjVu).")
        
        for file_path in files:
            print(f"\nProcessing: {file_path.name}")
            
            # 1. Hard Data (Hash & Structure)
            file_hash = self.calculate_hash(file_path)
            
            # OPTIMIZATION: Check Hash BEFORE potentially expensive AI
            dup_type, dup_match = self.check_duplicate(file_hash, None, None)
            
            if dup_type == "HASH":
                print(f"  -> DUPLICATE FOUND (HASH): {dup_match}")
                target_folder = "_Admin/Duplicates"
                dest_name = f"{file_path.stem}_hash{file_path.suffix.lower()}"
                final_target_rel = Path(target_folder) / dest_name
                
                # Calculate source relative path
                try:
                    src_rel = file_path.absolute().relative_to(LIBRARY_ROOT.absolute())
                except ValueError:
                    src_rel = str(file_path)
                    
                csv_rows.append([str(src_rel), str(final_target_rel)])
                continue 

            # If not a hash duplicate, extract structure and proceed
            structure = self.extract_structure(file_path)
            
            if not structure: 
                print("Skipping (Structure extraction failed)")
                continue
            
            # 2. Semantic Analysis
            ai_data = self.analyze_semantics(structure, existing_folders)
            if not ai_data:
                print("Skipping (AI Analysis Failed)")
                continue
                
            title = ai_data.get('title', file_path.stem)
            author = ai_data.get('author', 'Unknown')
            msc = ai_data.get('msc_class', 'General')
            
            print(f"  -> Title: {title}")
            print(f"  -> Category: {msc}")
            print(f"  -> AI Target Path: {ai_data.get('target_path')}")
            
            # 3. Semantic Deduplication Check
            # Only check semantic now, as hash was already checked
            dup_type, dup_match = self.check_duplicate(file_hash, title, author)
            
            final_target_rel = ""
            
            if dup_type:
                print(f"  -> DUPLICATE FOUND ({dup_type}): {dup_match}")
                # Logic: Relative to Library Root
                target_folder = str(DUPLICATES_DIR.relative_to(LIBRARY_ROOT))
                dest_name = f"{file_path.stem}_{dup_type}{file_path.suffix.lower()}"
                final_target_rel = Path(target_folder) / dest_name
            else:
                # 4. Routing
                # Priority: AI Target Path > Old Logic
                final_folder = ""
                ai_target = ai_data.get('target_path')
                
                if ai_target and ai_target != "None":
                     # Sanitize
                     clean_target = ai_target.strip().lstrip("/")
                     # Ensure it doesn't try to escape
                     if ".." not in clean_target:
                         final_folder = clean_target
                
                if not final_folder:
                     final_folder = self.map_category_to_folder(msc) or '99_General_and_Diverse'
                
                # ENFORCEMENT: Unsorted is never a final home
                if "Unsorted" in str(final_folder):
                    print(f"  [ROUTING] Overriding 'Unsorted' target with fallback '99_General_and_Diverse'")
                    final_folder = "99_General_and_Diverse"
                
                # Standardized Filename: Author - Year (if known) - Title
                safe_title = "".join(c for c in title if c.isalnum() or c in " -_").strip()
                safe_author = "".join(c for c in author if c.isalnum() or c in " -_").strip()
                ext = file_path.suffix.lower()
                dest_name = f"{safe_author} - {safe_title}{ext}" if safe_author else f"{safe_title}{ext}"
                
                # ENHANCEMENT: Final Truncation check
                dest_name = self.truncate_filename(dest_name)
                
                final_target_rel = Path(final_folder) / dest_name

                # 5. DB Insert (Metadata Persistence)
                # We always prepare the metadata. If executing, we perform full move+update.
                # If not executing/dry-run, we might still want to insert if not dry_run?
                # Logic: 
                # Dry Run -> No DB, No Move
                # Standard -> DB Insert (Unsorted path), CSV Gen, No Move
                # Execute -> DB Insert (Final path), Move, Calibre
                
                final_path_for_db = str(file_path.relative_to(LIBRARY_ROOT)) # Default: source path
                if self.execute_mode:
                     # If moving, future path is the final one
                     final_path_for_db = str(final_target_rel)

                if not self.dry_run:
                    try:
                        rel_path = final_path_for_db
                        
                        cursor = self.conn.cursor()
                        # Check if update or insert needed (simple insert/replace for now)
                        # We use filename/hash mainly
                        cursor.execute("""
                            INSERT INTO books (
                                filename, path, directory, author, title, 
                                file_hash, toc_json, msc_class, audience, 
                                has_exercises, has_solutions, page_count,
                                index_version, last_modified
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            dest_name if self.execute_mode else file_path.name, 
                            rel_path, 
                            str(Path(final_target_rel).parent) if self.execute_mode else str(file_path.parent.relative_to(LIBRARY_ROOT)),
                            author, 
                            title, 
                            file_hash,
                            json.dumps(structure['toc']),
                            msc,
                            ai_data.get('audience'),
                            ai_data.get('has_exercises', False),
                            ai_data.get('has_solutions', False),
                            structure['page_count'],
                            1, # index_version
                            file_path.stat().st_mtime
                        ))
                        self.conn.commit()
                        print(f"  [DB] Saved metadata for {file_path.name}")
                    except Exception as e:
                        print(f"  [DB Error] Could not insert metadata: {e}")
            
            # --- ACTION PHASE ---
            if self.execute_mode and final_target_rel:
                try:
                    target_abs = LIBRARY_ROOT / final_target_rel
                    
                    if not target_abs.parent.exists():
                        target_abs.parent.mkdir(parents=True, exist_ok=True)
                        
                    if target_abs.exists():
                        print(f"  [SKIP] Target exists: {target_abs}")
                    else:
                        print(f"  [MOVE] -> {target_abs}")
                        shutil.move(file_path, target_abs)
                        
                        # Post-Move: Calibre
                        if self.calibre_lib:
                            self.add_to_calibre(target_abs, title, author, msc)
                            
                except Exception as e:
                    print(f"  [ERROR] Move failed: {e}")
            else:
                 # Plan Mode: Calculate source relative path for CSV
                try:
                    src_rel = file_path.absolute().relative_to(LIBRARY_ROOT.absolute())
                except ValueError:
                    src_rel = str(file_path)

                csv_rows.append([str(src_rel), str(final_target_rel)])

        # 5. Generate CSV for Admin Tools (Only if NOT executing)
        if self.execute_mode:
            print("\nExecution Complete.")
            return

        if self.dry_run:
            print("\n--- DRY RUN PLAN ---")
            for src, dest in csv_rows:
                print(f"MOVE '{src}' \n  -> '{dest}'")
        else:
            if not csv_rows:
                print("No files processed.")
                return 

            # Ensure Admin dir exists
            csv_path = Path("..") / "_Admin" / "batch_import.csv"
            if not csv_path.parent.exists():
                csv_path.parent.mkdir(parents=True, exist_ok=True)
                
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["Source", "Destination"])
                writer.writerows(csv_rows)
            
            print(f"\nCreated batch plan at {csv_path.resolve()}")
            print(f"Run 'python3 ../_Admin/library_manager.py' to execute move.")

if __name__ == "__main__":
    import argparse
    import csv
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Simulate only")
    parser.add_argument("--execute", action="store_true", help="Move files and update DB (WARNING: Destructive)")
    parser.add_argument("--folder", type=str, default=str(UNSORTED_DIR), help="Input folder to scan")
    parser.add_argument("--calibre", type=str, default="/home/jure/Calibre Library", help="Path to Calibre Library")
    
    args = parser.parse_args()
    
    ingestor = BookIngestor(dry_run=args.dry_run, execute=args.execute, calibre_lib=args.calibre)
    ingestor.process_folder(args.folder)

        
        # 1. Re-extract Structure

