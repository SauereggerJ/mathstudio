import sqlite3
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.database import db
from core.search_engine import es_client

def cleanup():
    # Get all SQLite IDs
    with db.get_connection() as conn:
        rows = conn.execute("SELECT id FROM knowledge_terms").fetchall()
    sqlite_ids = {str(row['id']) for row in rows}

    # Scroll all ES IDs
    es_ids = set()
    res = es_client.search(
        index="mathstudio_terms",
        scroll="1m",
        size=1000,
        body={"query": {"match_all": {}}, "_source": False}
    )
    sid = res['_scroll_id']
    scroll_size = len(res['hits']['hits'])
    
    while scroll_size > 0:
        for doc in res['hits']['hits']:
            es_ids.add(str(doc['_id']))
        res = es_client.scroll(scroll_id=sid, scroll='1m')
        sid = res['_scroll_id']
        scroll_size = len(res['hits']['hits'])

    es_client.clear_scroll(scroll_id=sid)

    orphans = es_ids - sqlite_ids
    print(f"Found {len(orphans)} orphaned terms in Elasticsearch.")

    for orphan_id in orphans:
        try:
            es_client.delete(index="mathstudio_terms", id=orphan_id)
            print(f"Deleted {orphan_id}")
        except Exception as e:
            print(f"Failed to delete {orphan_id}: {e}")

if __name__ == '__main__':
    cleanup()
