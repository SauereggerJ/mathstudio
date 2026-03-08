
import json
import requests
import sqlite3

API_BASE = "http://localhost:5002/api/v1"

def benchmark():
    queries = [
        "Uniform Continuity",
        "Fundamental Theorem of Calculus",
        "Cauchy Sequence",
        "Compact Set",
        "Lipschitz Continuity"
    ]
    
    print(f"{'Query':<35} | {'KB Hits':<8} | {'FTS Hits':<8} | {'Overlap'}")
    print("-" * 70)
    
    for q in queries:
        # 1. Search KB
        kb_res = requests.get(f"{API_BASE}/kb/terms/search", params={"q": q, "limit": 50}).json()
        kb_ids = set(item['id'] for item in kb_res)
        
        # 2. Search Full Library (FTS)
        fts_res = requests.get(f"{API_BASE}/search", params={"q": q, "limit": 50, "fts": "true", "vec": "false"}).json()
        # FTS returns book results, but we want to see if KB terms are high-quality matches
        
        # 3. Check how many KB terms are actually "High Value" (not placeholders)
        placeholders = sum(1 for item in kb_res if "% Term:" in (item.get('latex_content') or ""))
        quality_hits = len(kb_res) - placeholders
        
        print(f"{q:<35} | {len(kb_res):<8} | {fts_res.get('total_count', 0):<8} | Quality KB: {quality_hits}")

if __name__ == "__main__":
    try:
        benchmark()
    except Exception as e:
        print(f"Error during benchmark: {e}")
