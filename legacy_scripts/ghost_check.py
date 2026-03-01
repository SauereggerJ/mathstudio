import hashlib
import os
import sqlite3
import glob
from pathlib import Path

DB_FILE = "library.db"
UNSORTED_DIR = Path("../99_General_and_Diverse/Unsorted")

def get_hash(p):
    h = hashlib.sha256()
    try:
        with open(p, 'rb') as f:
            while chunk := f.read(8192):
                h.update(chunk)
        return h.hexdigest()
    except:
        return None

def check_ghosts():
    if not os.path.exists(DB_FILE):
        print("DB not found")
        return
        
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    
    files = glob.glob(str(UNSORTED_DIR / "*.*"))
    print(f"Checking {len(files)} files in Unsorted...")
    
    for fpath in files:
        fname = os.path.basename(fpath)
        fhash = get_hash(fpath)
        
        if not fhash:
            continue
            
        cur.execute("SELECT path FROM books WHERE file_hash = ?", (fhash,))
        match = cur.fetchone()
        
        if match:
            db_path = match[0]
            # Check if the DB path is the same as the current path (relative)
            # current_rel = "99_General_and_Diverse/Unsorted/" + fname
            if db_path in fpath:
                 print(f"[INDEXED] {fname} (Already points here)")
            else:
                 print(f"[REDUNDANT GHOST] {fname} -> Match in DB at: {db_path}")
        else:
            print(f"[UNIQUE] {fname}")
            
    conn.close()

if __name__ == "__main__":
    check_ghosts()
