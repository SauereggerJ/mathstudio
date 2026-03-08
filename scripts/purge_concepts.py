import sqlite3
import requests
import sys

db_path = "/srv/data/math/New_Research_Library/mathstudio/library.db"
conn = sqlite3.connect(db_path, timeout=10.0)

try:
    rows = conn.execute("SELECT id FROM mathematical_concepts WHERE source = 'DeepSeek Auto-Generated'").fetchall()
    ids_to_delete = [r[0] for r in rows]
    print(f"Purging {len(ids_to_delete)} concepts...")
    
    # 1. Unlink terms
    conn.execute("UPDATE knowledge_terms SET concept_id = NULL WHERE concept_id IN (SELECT id FROM mathematical_concepts WHERE source = 'DeepSeek Auto-Generated')")
    
    # 2. Delete from DB
    conn.execute("DELETE FROM mathematical_concepts WHERE source = 'DeepSeek Auto-Generated'")
    conn.commit()

    # 3. Delete from ES
    for cid in ids_to_delete:
        try:
            requests.delete(f"http://localhost:9200/mathstudio_concepts/_doc/{cid}")
        except Exception as e:
            print(f"Error purging ES ID {cid}: {e}", file=sys.stderr)

    print(f"Successfully purged badly named concepts.")
except Exception as e:
    print(f"Purge Error: {e}")
finally:
    conn.close()
