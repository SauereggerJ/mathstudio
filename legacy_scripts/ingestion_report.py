import os
import sqlite3
import hashlib
from pathlib import Path

# --- CONFIGURATION ---
LIBRARY_ROOT = Path("..")
DB_FILE = "library.db"
UNSORTED_DIR = LIBRARY_ROOT / "99_General_and_Diverse" / "Unsorted"

def calculate_hash(file_path):
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def generate_report():
    if not UNSORTED_DIR.exists():
        print(f"Error: Unsorted directory not found at {UNSORTED_DIR}")
        return

    # Database connection
    db_path = Path(DB_FILE)
    if not db_path.exists():
        print(f"Error: Database file not found at {db_path.resolve()}")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    files = list(UNSORTED_DIR.glob("*.pdf")) + list(UNSORTED_DIR.glob("*.djvu"))
    
    print("\n" + "="*80)
    print(" MATHSTUDIO INGESTION REPORT")
    print(f" Scanning: {UNSORTED_DIR}")
    print(f" Found: {len(files)} files")
    print("="*80 + "\n")

    report = []
    
    for f in files:
        f_hash = calculate_hash(f)
        
        # Check by Hash
        cursor.execute("SELECT id, path, title FROM books WHERE file_hash = ?", (f_hash,))
        hash_match = cursor.fetchone()
        
        # Check by Path (if it was already indexed but not moved)
        # Note: In the DB, paths are usually relative to LIBRARY_ROOT
        try:
            rel_path = str(f.relative_to(LIBRARY_ROOT))
        except ValueError:
            rel_path = str(f)

        cursor.execute("SELECT id, path, title FROM books WHERE path = ?", (rel_path,))
        path_match = cursor.fetchone()
        
        status = "UNKNOWN"
        details = ""
        
        if hash_match:
            status = "DUPLICATE (HASH)"
            details = f"Already in DB at: {hash_match[1]} (Title: {hash_match[2]})"
        elif path_match:
            status = "INDEXED (STAYED)"
            details = f"Indexed in DB but still in Unsorted. Title: {path_match[2]}"
        else:
            status = "NEW / PENDING"
            details = "Not found in database."

        report.append({
            "name": f.name,
            "status": status,
            "details": details
        })

    # Output report
    for item in report:
        print(f"FILE:   {item['name']}")
        print(f"STATUS: [{item['status']}]")
        if item['details']:
            print(f"INFO:   {item['details']}")
        print("-" * 40)

    # Summary
    print("\nSUMMARY:")
    status_counts = {}
    for item in report:
        s = item['status']
        status_counts[s] = status_counts.get(s, 0) + 1
    
    if not status_counts:
        print("  No files found in Unsorted.")
    else:
        for s, count in status_counts.items():
            print(f"  {s}: {count}")
    
    print("\n" + "="*80 + "\n")
    conn.close()

if __name__ == "__main__":
    generate_report()
