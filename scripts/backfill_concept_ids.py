import sqlite3
import sys
from elasticsearch import Elasticsearch, helpers
import os

from core.database import db
from core.search_engine import es_client

def backfill():
    # 1. Update mapping
    try:
        es_client.indices.put_mapping(
            index="mathstudio_terms",
            body={"properties": {"concept_id": {"type": "integer"}}}
        )
        print("Successfully updated mathstudio_terms mapping.")
    except Exception as e:
        print(f"Error updating mapping: {e}")
        return

    # 2. Fetch data
    with db.get_connection() as conn:
        rows = conn.execute("SELECT id, concept_id FROM knowledge_terms WHERE concept_id IS NOT NULL").fetchall()

    if not rows:
        print("No concept IDs found to backfill.")
        return

    # 3. Bulk update
    actions = []
    for r in rows:
        actions.append({
            "_op_type": "update",
            "_index": "mathstudio_terms",
            "_id": r['id'],
            "doc": {"concept_id": r['concept_id']}
        })

    print(f"Backfilling {len(actions)} documents...")
    try:
        success, _ = helpers.bulk(es_client, actions, chunk_size=500, ignore_status=(404,))
        print(f"Successfully backfilled {success} documents.")
    except Exception as e:
        print(f"Error during bulk backfill: {e}")

if __name__ == "__main__":
    backfill()
