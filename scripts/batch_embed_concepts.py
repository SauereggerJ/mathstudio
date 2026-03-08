import os
import sys
import sqlite3
import concurrent.futures
import numpy as np
from elasticsearch.helpers import bulk

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import db
from core.search_engine import es_client
from core.config import EMBEDDING_MODEL
from core.ai import ai

def build_embedding_string(concept: dict) -> str:
    name = concept['name']
    subject_area = concept['subject_area']
    summary = concept['summary'] or ""
    
    # {name} (Subject: {subject_area}). Summary: {summary}.
    final_string = f"{name} (Subject: {subject_area}). Summary: {summary}"
    return final_string

def get_embedding_with_retry(text: str, retries: int = 5) -> list:
    import time
    for i in range(retries):
        try:
            result = ai.client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=[text],
                config={"task_type": "RETRIEVAL_QUERY", "output_dimensionality": 768}
            )
            val = result.embeddings[0].values
            if val:
                return val
            break
        except Exception as e:
            if '429' in str(e) or 'Quota' in str(e) or '503' in str(e):
                time.sleep(2 ** i)
            else:
                print(f"[Embedding Error] {e}", file=sys.stderr)
                break
    return None

def process_batch():
    with db.get_connection() as conn:
        conn.row_factory = sqlite3.Row
        # We index all concepts
        concepts = conn.execute("SELECT id, name, subject_area, summary FROM mathematical_concepts").fetchall()
        
    print(f"Loaded {len(concepts)} concepts from database.")
    if not concepts:
        print("No concepts found to embed.")
        return
        
    actions = []
    success = 0
    failed = 0
    update_queries = []
    
    def process_concept(concept):
        text_to_embed = build_embedding_string(concept)
        emb = get_embedding_with_retry(text_to_embed)
        return concept, emb

    # Using max_workers=5 for balanced processing, respect limits
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(process_concept, dict(c)): dict(c) for c in concepts}
        
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            original_c = futures[future]
            try:
                c, emb = future.result()
                if emb:
                    # Elasticsearch action
                    actions.append({
                        "_op_type": "update",
                        "_index": "mathstudio_concepts",
                        "_id": str(c["id"]),
                        "doc_as_upsert": True,
                        "doc": {
                            "id": c["id"],
                            "name": c["name"],
                            "subject_area": c["subject_area"],
                            "summary": c["summary"],
                            "embedding": list(emb)
                        }
                    })
                    
                    # SQLite update
                    emb_bytes = np.array(emb, dtype=np.float32).tobytes()
                    update_queries.append((emb_bytes, c["id"]))
                    
                    success += 1
                else:
                    failed += 1
            except Exception as e:
                print(f"Thread Error on Concept ID {original_c['id']}: {e}")
                failed += 1
                
            if len(actions) >= 50:
                try:
                    bulk(es_client, actions)
                    with db.get_connection() as conn:
                        conn.executemany("UPDATE mathematical_concepts SET embedding = ? WHERE id = ?", update_queries)
                        conn.commit()
                    actions = []
                    update_queries = []
                    print(f"Processed {i+1}/{len(concepts)} concepts... (Success: {success}, Failed: {failed})")
                except Exception as e:
                    print(f"Bulk indexing Error: {e}")
    
    # Flush remaining
    if actions:
        try:
            bulk(es_client, actions)
            with db.get_connection() as conn:
                conn.executemany("UPDATE mathematical_concepts SET embedding = ? WHERE id = ?", update_queries)
                conn.commit()
            print(f"Final flush completed.")
        except Exception as e:
            print(f"Final Bulk indexing Error: {e}")
            
    # Force index refresh
    es_client.indices.refresh(index="mathstudio_concepts")
            
    print(f"\nBatch Concepts Embedding Complete! Successfully embedded {success} concepts. Failed: {failed}.")

if __name__ == '__main__':
    process_batch()
