import sqlite3
import os
import sys
import argparse
from pathlib import Path

# Config (matching book_ingestor.py or Docker defaults)
DB_FILE = "library.db"
LIBRARY_ROOT = Path("..") 

def check_sanity(fix=False):
    if not os.path.exists(DB_FILE):
        print(f"Error: Database file {DB_FILE} not found.")
        return

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row # Use dict-like access
    cursor = conn.cursor()

    print(f"--- 1. File Existence Check (Fix: {fix}) ---")
    cursor.execute("SELECT id, path, title FROM books")
    rows = cursor.fetchall()
    
    missing_ids = []
    for row in rows:
        db_id, rel_path, title = row['id'], row['path'], row['title']
        full_path = (LIBRARY_ROOT / rel_path).resolve()
        
        # Safe check for long paths
        try:
            exists = full_path.exists()
        except OSError:
            exists = False

        if not exists:
            print(f"  [MISSING] ID {db_id}: {rel_path} ({title})")
            missing_ids.append(db_id)
            
    if missing_ids:
        if fix:
            print(f"  -> DELETING {len(missing_ids)} stale database records...")
            cursor.execute(f"DELETE FROM books WHERE id IN ({','.join(map(str, missing_ids))})")
            conn.commit()
            print("  [DONE] Stale records removed.")
        else:
            print(f"  Found {len(missing_ids)} missing files. Use --fix to remove these stale DB records.")
    else:
        print("All files in database exist on disk.")

    print("\n--- 2. Path Duplicate Check ---")
    cursor.execute("SELECT path, COUNT(*) as count FROM books GROUP BY path HAVING count > 1")
    path_dups = cursor.fetchall()
    if path_dups:
        print(f"Found {len(path_dups)} paths with multiple entries (CRITICAL):")
        for row in path_dups:
            path, count = row['path'], row['count']
            print(f"  [DUP PATH] {path}: {count} entries")
            cursor.execute("SELECT id, title FROM books WHERE path = ?", (path,))
            entries = cursor.fetchall()
            for erow in entries:
                 print(f"    -> ID {erow['id']}: {erow['title']}")
    else:
        print("No duplicate paths found in database.")

    print(f"\n--- 3. Content Duplicate Check (Fix: {fix}) ---")
    cursor.execute("SELECT file_hash, COUNT(*) as count FROM books WHERE file_hash IS NOT NULL AND file_hash != '' GROUP BY file_hash HAVING count > 1")
    hash_dups = cursor.fetchall()
    
    if hash_dups:
        print(f"Found {len(hash_dups)} content duplicates (shared hash):")
        for row in hash_dups:
            file_hash, count = row['file_hash'], row['count']
            print(f"\n  [HASH DUP] {file_hash}: {count} candidate files")
            
            cursor.execute("SELECT id, path, title FROM books WHERE file_hash = ?", (file_hash,))
            candidates = [dict(r) for r in cursor.fetchall()]
            
            # Ranking logic to pick the "best" one to keep
            # 1. Prefer ones NOT in Unsorted
            # 2. Prefer shorter paths (usually more specific)
            
            def rank_candidate(c):
                score = 0
                if "99_General_and_Diverse/Unsorted" in c['path']:
                    score += 1000 # Higher is worse
                score += len(c['path'])
                return score

            candidates.sort(key=rank_candidate)
            best = candidates[0]
            to_delete = candidates[1:]
            
            print(f"    [KEEP] ID {best['id']}: {best['path']}")
            
            for item in to_delete:
                print(f"    [REDUNDANT] ID {item['id']}: {item['path']}")
                if fix:
                    # Physical Delete
                    phys_path = LIBRARY_ROOT / item['path']
                    if phys_path.exists():
                        print(f"      -> DELETING File: {item['path']}")
                        os.remove(phys_path)
                    
                    # DB Delete
                    print(f"      -> DELETING DB Record: ID {item['id']}")
                    cursor.execute("DELETE FROM books WHERE id = ?", (item['id'],))
                    conn.commit()
    else:
        print("No content duplicates found via hash.")

    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Library Database Sanity Check & Cleanup")
    parser.add_argument("--fix", action="store_true", help="Automatically delete stale entries and redundant duplicates.")
    args = parser.parse_args()
    
    check_sanity(fix=args.fix)
