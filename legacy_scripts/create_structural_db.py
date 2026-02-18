import sqlite3
import os

SOURCE_DB = "library.db"
DEST_DB = "library_structural.db"

if os.path.exists(DEST_DB):
    os.remove(DEST_DB)

source = sqlite3.connect(SOURCE_DB)
dest = sqlite3.connect(DEST_DB)

try:
    # 1. Create Tables in Destination
    print("Creating schema...")
    
    # Get schema for 'books' (it's a normal table)
    cursor = source.cursor()
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='books'")
    books_sql = cursor.fetchone()[0]
    dest.execute(books_sql)
    
    # Get schema for 'chapters'
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='chapters'")
    chapters_res = cursor.fetchone()
    if chapters_res:
        dest.execute(chapters_res[0])
    
    dest.commit()
    
    # 2. Copy Data
    print("Copying data...")
    
    # Copy Books
    # We need to explicitly list columns to match the source schema order if needed, 
    # but 'SELECT *' is usually fine if schemas are identical.
    # Let's be safe and select columns existing in source books table.
    cursor.execute("PRAGMA table_info(books)")
    columns = [row[1] for row in cursor.fetchall()]
    col_str = ", ".join(columns)
    
    print(f" - Copying {len(columns)} columns for books...")
    source_books = source.execute(f"SELECT {col_str} FROM books").fetchall()
    dest.executemany(f"INSERT INTO books ({col_str}) VALUES ({','.join(['?']*len(columns))})", source_books)
    print(f"   -> Copied {len(source_books)} books.")

    # Copy Chapters
    if chapters_res:
        cursor.execute("PRAGMA table_info(chapters)")
        chap_cols = [row[1] for row in cursor.fetchall()]
        chap_col_str = ", ".join(chap_cols)
        
        print(f" - Copying {len(chap_cols)} columns for chapters...")
        source_chaps = source.execute(f"SELECT {chap_col_str} FROM chapters").fetchall()
        dest.executemany(f"INSERT INTO chapters ({chap_col_str}) VALUES ({','.join(['?']*len(chap_cols))})", source_chaps)
        print(f"   -> Copied {len(source_chaps)} chapters.")

    dest.commit()
    print("Vacuuming...")
    dest.execute("VACUUM")
    
except Exception as e:
    print(f"Error: {e}")
finally:
    source.close()
    dest.close()

size = os.path.getsize(DEST_DB)
print(f"\nCreated {DEST_DB} ({size/1024/1024:.2f} MB)")
