import sqlite3
import sys

print("Python version:", sys.version)
print("SQLite version:", sqlite3.sqlite_version)

conn = sqlite3.connect('library.db')
cursor = conn.cursor()

print("\nTables:")
try:
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    for t in tables:
        print(f" - {t[0]}")
except Exception as e:
    print("Error listing tables:", e)

print("\nFTS5 Support:")
try:
    cursor.execute("CREATE VIRTUAL TABLE IF NOT EXISTS test_fts USING fts5(content);")
    print(" - FTS5 tables creation succeeded.")
    cursor.execute("DROP TABLE test_fts;")
except Exception as e:
    print(" - FTS5 creation failed:", e)

print("\nCompile Options:")
try:
    cursor.execute("PRAGMA compile_options;")
    options = [row[0] for row in cursor.fetchall()]
    fts_opts = [opt for opt in options if 'FTS' in opt]
    print(" - FTS Options:", fts_opts)
except Exception as e:
    print(" - Error getting options:", e)

conn.close()
