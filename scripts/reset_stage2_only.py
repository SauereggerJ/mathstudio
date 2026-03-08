import sqlite3
import requests
import json
from pathlib import Path
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import db
from core.search_engine import create_mathstudio_indices

def reset_stage2():
    print("Purging Stage 2 outputs...")
    with db.get_connection() as conn:
        conn.execute("DELETE FROM knowledge_terms")
        conn.execute("DELETE FROM knowledge_terms_fts")
        # Set all actively converting/completed books to queued so they resume.
        conn.execute("UPDATE book_scans SET status='queued' WHERE status IN ('paused', 'completed')")
        
    print("Clearing MathWebSearch Harvest file...")
    Path("/library/mathstudio/mathstudio.harvest").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<mws:harvest xmlns:mws="http://search.mathweb.org/ns">\n</mws:harvest>\n')
    
    print("Purging Elasticsearch terms index...")
    try:
        requests.delete("http://elasticsearch:9200/mathstudio_terms")
        create_mathstudio_indices()
    except Exception as e:
        print(f"Error resetting ES: {e}")

    print("Stage 2 outputs have been purged! We are ready to re-ingest the LaTeX pages.")

if __name__ == '__main__':
    reset_stage2()
