import sqlite3
import os

DB_FILE = "library.db"

def list_files():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, path FROM books WHERE id IN (899, 486)")
    rows = cursor.fetchall()
    conn.close()
    
    print("Paths in DB:")
    for r in rows:
        print(f"[{r[0]}] {r[1]}")
        if os.path.exists(r[1]):
            print("  -> EXISTS on disk")
        else:
            print("  -> MISSING on disk")

if __name__ == "__main__":
    list_files()
