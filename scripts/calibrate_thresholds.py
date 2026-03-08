import os
import sys
import sqlite3
import numpy as np

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.search_engine import es_client
from core.database import db

def run_calibration():
    with db.get_connection() as conn:
        conn.row_factory = sqlite3.Row
        terms = conn.execute("SELECT id, name FROM knowledge_terms ORDER BY RANDOM() LIMIT 200").fetchall()
        
    print(f"Loaded {len(terms)} random terms for calibration.")
    
    scores = []
    
    for idx, term in enumerate(terms):
        t_id = term['id']
        try:
            res = es_client.get(index="mathstudio_terms", id=str(t_id), _source=["embedding"])
            if 'embedding' not in res['_source']:
                continue
                
            emb = res['_source']['embedding']
            
            # Search concepts
            query = {
                "knn": {
                    "field": "embedding",
                    "query_vector": emb,
                    "k": 1,
                    "num_candidates": 100
                },
                "_source": ["id", "name"]
            }
            
            search_res = es_client.search(index="mathstudio_concepts", body=query)
            hits = search_res['hits']['hits']
            if hits:
                top_score = hits[0]['_score']
                scores.append(top_score)
                # Print sample output heavily to see the actual semantic match visually
                if idx < 10:
                    print(f"Term: {term['name']:<30} | Top Match: {hits[0]['_source']['name']:<30} | Score: {top_score:.4f}")
        except Exception as e:
            pass
            
    if not scores:
        print("No scores calculated.")
        return
        
    scores = np.array(scores)
    print("\n--- Calibration Results (Top Match Scores) ---")
    print(f"Total Evaluated: {len(scores)}")
    print(f"Mean Score: {np.mean(scores):.4f}")
    print(f"Median Score: {np.median(scores):.4f}")
    print(f"Min Score: {np.min(scores):.4f}")
    print(f"Max Score: {np.max(scores):.4f}")
    print(f"90th Percentile: {np.percentile(scores, 90):.4f}")
    print(f"75th Percentile: {np.percentile(scores, 75):.4f}")
    print(f"25th Percentile: {np.percentile(scores, 25):.4f}")
    
    print("\nRecommended Thresholds based on distribution:")
    print(f"MAX_THRESHOLD (Explicit Link): ~ {np.percentile(scores, 90):.4f} (Top 10% highly confident)")
    print(f"MIN_THRESHOLD (Ambiguous): ~ {np.percentile(scores, 60):.4f} (Mid-range need LLM logic)")

if __name__ == '__main__':
    run_calibration()
