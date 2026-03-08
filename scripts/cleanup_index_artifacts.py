import sqlite3
import requests
import sys

DB_PATH = "library.db"
ES_BASE = "http://localhost:9200/mathstudio_terms"

def cleanup(dry_run=True):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    patterns = [
        '%(Subject Index)%',
        '%(Name Index)%',
        '%(Symbol Index)%',
        '%(Index)%',
        '%, Page %',
        '%(Page %'
    ]
    
    all_to_delete = []
    for p in patterns:
        rows = cursor.execute("SELECT id, name FROM knowledge_terms WHERE name LIKE ?", (p,)).fetchall()
        all_to_delete.extend(rows)

    if not all_to_delete:
        print("No index artifacts found.")
        return

    print(f"Found {len(all_to_delete)} potential index artifacts.")
    
    if dry_run:
        print("\n--- DRY RUN (Top 20) ---")
        for row in all_to_delete[:20]:
            print(f"  [ID: {row['id']}] {row['name']}")
        print(f"\nTotal to delete: {len(all_to_delete)}")
        print("\nRun with --execute to perform deletion.")
    else:
        print("\n--- EXECUTING DELETION ---")
        ids = [str(r['id']) for r in all_to_delete]
        
        # 1. Delete from SQLite
        cursor.execute(f"DELETE FROM knowledge_terms WHERE id IN ({','.join(ids)})")
        cursor.execute(f"DELETE FROM knowledge_terms_fts WHERE rowid IN ({','.join(ids)})")
        
        # 2. Delete from Elasticsearch
        try:
            payload = {
                "query": {
                    "ids": {
                        "values": ids
                    }
                }
            }
            resp = requests.post(f"{ES_BASE}/_delete_by_query?refresh=true", json=payload)
            print(f"Elasticsearch cleanup: {resp.json().get('deleted', 0)} docs deleted.")
        except Exception as e:
            print(f"Error cleaning up Elasticsearch: {e}")

        conn.commit()
        print(f"SQLite cleanup: {len(all_to_delete)} rows deleted.")

    conn.close()

if __name__ == "__main__":
    is_execute = "--execute" in sys.argv
    cleanup(dry_run=not is_execute)
