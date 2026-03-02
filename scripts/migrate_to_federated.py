import sqlite3
import numpy as np
import json
import subprocess
import requests
import sys
import os
from elasticsearch import Elasticsearch, helpers

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import DB_FILE, ELASTICSEARCH_URL, MWS_URL

# Configuration
BATCH_SIZE = 100
ES_CLIENT = Elasticsearch(ELASTICSEARCH_URL)

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def convert_latex_to_mathml(latex_str):
    """Invokes latexmlmath to convert LaTeX to Content MathML."""
    try:
        # We use latexmlmath with --cmml for Content MathML
        result = subprocess.run(
            ["latexmlmath", "--cmml", "-", "-"],
            input=latex_str,
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        return result.stdout
    except Exception as e:
        return None, str(e)

def safe_bulk(client, actions):
    """Performs bulk ingestion and ignores individual errors."""
    try:
        success, failed = 0, 0
        for ok, item in helpers.streaming_bulk(client, actions, raise_on_error=False):
            if ok:
                success += 1
            else:
                failed += 1
                print(f"  [ERROR] Document failed: {item['index']['_id']} - {item['index'].get('error')}")
        return success, failed
    except Exception as e:
        print(f"  [CRITICAL ERROR] Bulk operation failed: {e}")
        return 0, len(actions)

def migrate_books():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM books")
    total = cursor.fetchone()[0]
    
    print(f"Migrating {total} books...")
    
    migrated_count = 0
    failed_count = 0
    offset = 0
    
    while True:
        cursor.execute(f"""
            SELECT b.*, 
                   (SELECT group_concat(title, '\n') FROM chapters WHERE book_id = b.id) as toc_text
            FROM books b 
            LIMIT ? OFFSET ?
        """, (BATCH_SIZE, offset))
        rows = cursor.fetchall()
        if not rows:
            break
            
        actions = []
        for row in rows:
            # Prepare vector
            vector = None
            if row['embedding']:
                try:
                    vector = list(np.frombuffer(row['embedding'], dtype=np.float32))
                    if len(vector) != 768:
                        vector = None # Skip invalid vectors
                except:
                    vector = None

            # Handle possible None values for strictly typed fields
            doc = {
                "_index": "mathstudio_books",
                "_id": row['id'],
                "_source": {
                    "id": row['id'],
                    "title": row['title'] or "",
                    "author": row['author'] or "",
                    "summary": row['summary'] or "",
                    "description": row['description'] or "",
                    "msc_class": row['msc_class'] or "",
                    "tags": row['tags'] or "",
                    "zbl_id": row['zbl_id'] or "",
                    "doi": row['doi'] or "",
                    "isbn": row['isbn'] or "",
                    "year": row['year'] if isinstance(row['year'], int) else None,
                    "publisher": row['publisher'] or "",
                    "toc": row['toc_text'] or "",
                    "index_text": row['index_text'] or "",
                    "zb_review": row['zb_review'] or "",
                    "embedding": vector
                }
            }
            actions.append(doc)
            
        if actions:
            s, f = safe_bulk(ES_CLIENT, actions)
            migrated_count += s
            failed_count += f
            print(f"  Processed {migrated_count + failed_count}/{total} books (Success: {migrated_count}, Fail: {failed_count})...")
            
        offset += BATCH_SIZE
        
    conn.close()
    return migrated_count, failed_count

def migrate_pages():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pages_fts'")
    if not cursor.fetchone():
        print("No pages_fts table found. Skipping.")
        return 0, 0

    cursor.execute("SELECT COUNT(*) FROM pages_fts")
    total = cursor.fetchone()[0]
    
    print(f"Migrating {total} deep-indexed pages...")
    
    migrated_count = 0
    failed_count = 0
    offset = 0
    
    while True:
        cursor.execute("SELECT book_id, page_number, content FROM pages_fts LIMIT ? OFFSET ?", (BATCH_SIZE, offset))
        rows = cursor.fetchall()
        if not rows:
            break
            
        actions = []
        for row in rows:
            doc = {
                "_index": "mathstudio_pages",
                "_source": {
                    "book_id": row['book_id'],
                    "page_number": row['page_number'],
                    "content": row['content'] or ""
                }
            }
            actions.append(doc)
            
        if actions:
            s, f = safe_bulk(ES_CLIENT, actions)
            migrated_count += s
            failed_count += f
            if (migrated_count + failed_count) % 1000 == 0:
                print(f"  Processed {migrated_count + failed_count}/{total} pages...")
            
        offset += BATCH_SIZE
        
    conn.close()
    return migrated_count, failed_count

def migrate_knowledge_base():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM knowledge_terms")
    total = cursor.fetchone()[0]
    
    print(f"Migrating {total} knowledge terms...")
    
    migrated_count = 0
    failed_es = 0
    mws_harvested = 0
    failed_conversions = []
    
    offset = 0
    while True:
        cursor.execute("SELECT * FROM knowledge_terms LIMIT ? OFFSET ?", (BATCH_SIZE, offset))
        rows = cursor.fetchall()
        if not rows:
            break
            
        es_actions = []
        for row in rows:
            term_id = row['id']
            # 1. Prepare Elasticsearch doc
            doc = {
                "_index": "mathstudio_terms",
                "_id": term_id,
                "_source": {
                    "id": term_id,
                    "book_id": row['book_id'],
                    "page_start": row['page_start'],
                    "name": row['name'] or "",
                    "term_type": row['term_type'] or "",
                    "latex_content": row['latex_content'] or "",
                    "used_terms": row['used_terms'] or "",
                    "status": row['status'] or "draft"
                }
            }
            es_actions.append(doc)
            
            # 2. MathWebSearch Harvest
            latex = row['latex_content']
            if latex:
                res_conv = convert_latex_to_mathml(latex)
                if isinstance(res_conv, str):
                    try:
                        # MWS Harvest Payload
                        payload = f"""
                        <mws:harvest xmlns:mws="http://search.mathweb.org/ns">
                          <mws:entry id="{term_id}">
                            {res_conv}
                          </mws:entry>
                        </mws:harvest>
                        """
                        res = requests.post(f"{MWS_URL}/harvest", data=payload, headers={'Content-Type': 'application/xml'}, timeout=5)
                        if res.status_code == 200:
                            mws_harvested += 1
                        else:
                            failed_conversions.append({"id": term_id, "error": f"MWS HTTP {res.status_code}"})
                    except Exception as e:
                        failed_conversions.append({"id": term_id, "error": f"MWS Post Error: {str(e)}"})
                else:
                    # Conversion failed
                    failed_conversions.append({"id": term_id, "error": "latexmlmath failed"})
        
        if es_actions:
            s, f = safe_bulk(ES_CLIENT, es_actions)
            migrated_count += s
            failed_es += f
            print(f"  Processed {migrated_count + failed_es}/{total} terms...")
            
        offset += BATCH_SIZE
        
    conn.close()
    return migrated_count, failed_es, mws_harvested, failed_conversions

if __name__ == "__main__":
    print("--- Starting Great Migration ---")
    
    stats = {}
    try:
        b_s, b_f = migrate_books()
        stats['books'] = b_s
        stats['books_failed'] = b_f
        
        p_s, p_f = migrate_pages()
        stats['pages'] = p_s
        stats['pages_failed'] = p_f
        
        kb_migrated, kb_f, mws_harvested, failed_conv = migrate_knowledge_base()
        stats['kb_terms'] = kb_migrated
        stats['kb_failed'] = kb_f
        stats['mws_harvests'] = mws_harvested
        stats['failed_conversions'] = len(failed_conv)
        
        print("\n--- Migration Summary ---")
        print(f"Books Migrated:      {stats['books']} (Failed: {stats['books_failed']})")
        print(f"Pages Migrated:      {stats['pages']} (Failed: {stats['pages_failed']})")
        print(f"KB Terms Migrated:   {stats['kb_terms']} (Failed: {stats['kb_failed']})")
        print(f"MWS Harvests:        {stats['mws_harvests']}")
        print(f"Failed Conversions:  {stats['failed_conversions']}")
        
        if failed_conv:
            print("\nTop 10 Failed Conversions:")
            for f in failed_conv[:10]:
                print(f"  ID {f['id']}: {f['error']}")
                
    except Exception as e:
        print(f"\nCRITICAL MIGRATION ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
