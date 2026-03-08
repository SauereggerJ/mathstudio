import os
import sys
import sqlite3
import json
import re
import concurrent.futures
from elasticsearch.helpers import bulk

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import db
from core.search_engine import es_client
from core.config import EMBEDDING_MODEL
from core.ai import ai

def replace_latex_env(text: str, env_name: str, replacement: str = "") -> str:
    """Uses a stack-based parser to safely remove or replace nested LaTeX environments."""
    begin_str = f"\\begin{{{env_name}}}"
    end_str = f"\\end{{{env_name}}}"
    
    while begin_str in text:
        start_idx = text.find(begin_str)
        if start_idx == -1:
            break
            
        stack = 1
        curr_idx = start_idx + len(begin_str)
        match_end = -1
        
        while curr_idx < len(text) and stack > 0:
            next_begin = text.find(begin_str, curr_idx)
            next_end = text.find(end_str, curr_idx)
            
            if next_end == -1:
                # Malformed LaTeX without matching end
                match_end = len(text)
                break
                
            if next_begin != -1 and next_begin < next_end:
                stack += 1
                curr_idx = next_begin + len(begin_str)
            else:
                stack -= 1
                curr_idx = next_end + len(end_str)
                if stack == 0:
                    match_end = curr_idx
                    
        if match_end != -1:
            text = text[:start_idx] + replacement + text[match_end:]
        else:
            text = text[:start_idx] + replacement
            
    return text

def preprocess_latex(raw_latex: str) -> str:
    """Implements the 4-step masking formula for semantic clustering."""
    if not raw_latex:
        return ""
        
    text = raw_latex
    
    # 1. Eradicate Proofs
    text = replace_latex_env(text, "proof", "")
    text = re.sub(r'Proof\..*?\\blacksquare', '', text, flags=re.DOTALL)
    
    # 2. Mask Display Mathematics
    text = re.sub(r'\$\$.*?\$\$', ' [EQUATION] ', text, flags=re.DOTALL)
    text = re.sub(r'\\\[.*?\\\]', ' [EQUATION] ', text, flags=re.DOTALL)
    
    display_envs = ["equation", "equation*", "align", "align*", "aligned", "gather", "gather*"]
    for env in display_envs:
        text = replace_latex_env(text, env, " [EQUATION] ")
        
    # 3. Retain Inline Mathematics: Done implicitly by not stripping single $...$ regions
    
    # Clean up excessive whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def build_embedding_string(term: dict) -> str:
    name = term['name']
    term_type = term['term_type']
    raw_latex = term['latex_content'] or ""
    
    used_terms_str = term['used_terms']
    if used_terms_str:
        try:
            used_terms_list = json.loads(used_terms_str)
            if isinstance(used_terms_list, list):
                concepts = ", ".join(used_terms_list)
            else:
                concepts = str(used_terms_str)
        except Exception:
            concepts = str(used_terms_str)
    else:
        concepts = ""
        
    cleaned_statement = preprocess_latex(raw_latex)
    
    # 4. Structured Concatenation
    final_string = f"{name} (Type: {term_type}). Concepts: {concepts}. Statement: {cleaned_statement}"
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
        terms = conn.execute("SELECT id, name, term_type, latex_content, used_terms FROM knowledge_terms").fetchall()
        
    print(f"Loaded {len(terms)} terms from database.")
    
    # Skip terms that already have embeddings in ES
    try:
        already_embedded = set()
        res = es_client.search(
            index="mathstudio_terms",
            body={"query": {"exists": {"field": "embedding"}}, "_source": False, "size": 10000}
        )
        already_embedded = {int(hit['_id']) for hit in res['hits']['hits']}
        terms = [t for t in terms if t['id'] not in already_embedded]
        print(f"Skipping {len(already_embedded)} already-embedded terms. Processing {len(terms)} new terms.")
    except Exception as e:
        print(f"Could not check existing embeddings, processing all: {e}")
    
    if not terms:
        print("No new terms to embed.")
        return
    
    actions = []
    success = 0
    failed = 0
    
    def process_term(term):
        text_to_embed = build_embedding_string(term)
        emb = get_embedding_with_retry(text_to_embed)
        return term['id'], emb

    # Using max_workers=5 for balanced processing
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(process_term, dict(t)): t['id'] for t in terms}
        
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            term_id = futures[future]
            try:
                t_id, emb = future.result()
                if emb:
                    actions.append({
                        "_op_type": "update",
                        "_index": "mathstudio_terms",
                        "_id": str(t_id),
                        "doc": {
                            "embedding": list(emb)
                        }
                    })
                    success += 1
                else:
                    failed += 1
            except Exception as e:
                print(f"Thread Error on Term ID {term_id}: {e}")
                failed += 1
                
            if len(actions) >= 50:
                try:
                    bulk(es_client, actions)
                    actions = []
                    print(f"Processed {i+1}/{len(terms)} terms... (Success: {success}, Failed: {failed})")
                except Exception as e:
                    print(f"Bulk indexing Error: {e}")
    
    # Flush remaining
    if actions:
        try:
            bulk(es_client, actions)
            print(f"Final flush completed.")
        except Exception as e:
            print(f"Final Bulk indexing Error: {e}")
            
    # Force index refresh
    es_client.indices.refresh(index="mathstudio_terms")
            
    print(f"\nBatch Embedding Complete! Successfully embedded {success} terms. Failed: {failed}.")

if __name__ == '__main__':
    process_batch()
