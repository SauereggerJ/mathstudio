#!/usr/bin/env python3
import json
import sqlite3
import requests
import sys
import os
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.database import db
from core.config import ELASTICSEARCH_URL

def get_sqlite_stats():
    try:
        with db.get_connection() as conn:
            total_terms = conn.execute("SELECT COUNT(*) FROM knowledge_terms").fetchone()[0]
            linked_terms = conn.execute("SELECT COUNT(concept_id) FROM knowledge_terms").fetchone()[0]
            active_scans = conn.execute("SELECT COUNT(*) FROM book_scans WHERE status NOT IN ('completed', 'failed', 'cancelled')").fetchone()[0]
            queued_scans = conn.execute("SELECT COUNT(*) FROM book_scans WHERE status = 'queued'").fetchone()[0]
        return {
            "sqlite_total_terms": total_terms,
            "sqlite_linked_terms": linked_terms,
            "sqlite_active_scans": active_scans,
            "sqlite_queued_scans": queued_scans
        }
    except Exception as e:
        return {"error_sqlite": str(e)}

def get_es_stats():
    try:
        count_url = f"{ELASTICSEARCH_URL}/mathstudio_terms/_count"
        
        # Total count
        r_total = requests.get(count_url)
        total_es = r_total.json().get('count', 0)
        
        # Embedding count
        payload = {"query": {"exists": {"field": "embedding"}}}
        r_emb = requests.get(count_url, json=payload)
        embedded_es = r_emb.json().get('count', 0)
        
        return {
            "es_total_terms": total_es,
            "es_embedded_terms": embedded_es
        }
    except Exception as e:
        return {"error_es": str(e)}

def run_report():
    print("═══ MathStudio System Audit ═══")
    sqlite = get_sqlite_stats()
    es = get_es_stats()
    
    # 1. Synchronization
    print("\n[1] Synchronization Status")
    total = sqlite.get("sqlite_total_terms", 0)
    linked = sqlite.get("sqlite_linked_terms", 0)
    es_total = es.get("es_total_terms", 0)
    es_embedded = es.get("es_embedded_terms", 0)
    
    sync_ok = (total == linked == es_total == es_embedded)
    status = "✅ PERFECT" if sync_ok else "⚠️ DISCREPANCY"
    
    print(f"Status: {status}")
    print(f"- SQLite Total Terms: {total}")
    print(f"- SQLite Linked:      {linked}")
    print(f"- ES Total Terms:     {es_total}")
    print(f"- ES Embedded:        {es_embedded}")
    
    # 2. Pipeline Activity
    print("\n[2] Pipeline Activity")
    active = sqlite.get("sqlite_active_scans", 0)
    queued = sqlite.get("sqlite_queued_scans", 0)
    
    if active > 0:
        print(f"Status: 🏃 RUNNING ({active} active)")
    elif queued > 0:
        print(f"Status: 📥 QUEUED ({queued} in line)")
    else:
        print("Status: 💤 IDLE")
        
    print(f"- Active Scans: {active}")
    print(f"- Queued Scans: {queued}")
    
    if not sync_ok:
        print("\n[!] Recommendations:")
        if linked < total:
            print("- Run 'scripts/batch_anchor_terms.py' to link remaining terms.")
        if es_total < total:
            print("- Run 'scripts/backfill_concept_ids.py' to sync missing terms to ES.")
        if es_embedded < es_total:
            print("- Run 'scripts/batch_embed_terms.py' to generate missing embeddings.")

if __name__ == "__main__":
    run_report()
