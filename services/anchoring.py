import os
import sys
import json
import sqlite3
import numpy as np
import concurrent.futures
from typing import List, Dict, Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import db
from core.search_engine import es_client
from core.ai import ai
from scripts.batch_embed_terms import build_embedding_string as build_term_emb_string, get_embedding_with_retry
from scripts.batch_embed_concepts import build_embedding_string as build_concept_emb_string

# Empirically observed thresholds
MAX_THRESHOLD = 0.885
MIN_THRESHOLD = 0.850

class AnchoringService:
    def __init__(self):
        # We assume MathStudio uses deepseek via ai.deepseek.client
        if not hasattr(ai, 'deepseek') or not ai.deepseek:
            raise ValueError("DeepSeek provider must be enabled for Anchoring.")
            
    def vector_search_concepts(self, embedding: list, k: int=3) -> List[Dict]:
        query = {
            "knn": {
                "field": "embedding",
                "query_vector": embedding,
                "k": k,
                "num_candidates": 100
            },
            "_source": ["id", "name", "subject_area", "summary"]
        }
        
        try:
            res = es_client.search(index="mathstudio_concepts", body=query)
            hits = res['hits']['hits']
            return [{"score": h['_score'], "doc": h['_source']} for h in hits]
        except Exception as e:
            print(f"ES Search Error: {e}")
            return []

    def tier_b_librarian(self, term: dict, candidates: List[Dict]) -> Optional[int]:
        """Uses DeepSeek to decisively choose the correct concept_id, or NONE."""
        raw_latex = term['latex_content'] or ""
        term_context = f"Name: {term['name']}\nType: {term['term_type']}\nConcepts: {term['used_terms']}\nStatement: {raw_latex}"
        
        candidates_text = ""
        for c in candidates:
            candidates_text += f"ID: {c['doc']['id']} | Name: {c['doc']['name']} | Subject: {c['doc'].get('subject_area', '')}\nSummary: {c['doc'].get('summary', '')}\n\n"
            
        prompt = f"""You are an advanced mathematical ontology classifier.
        
Term to classify:
{term_context}

Candidate Canonical Concepts:
{candidates_text}

Task: Determine which Candidate Concept ID precisely matches the Term.
Return ONLY the integer ID of the matching concept. If NONE of the candidates are a correct canonical match, return exactly "NONE". Do not include any other text or formatting.
"""    
        try:
            response = ai.deepseek.client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0
            )
            answer = response.choices[0].message.content.strip()
            if answer == "NONE" or "none" in answer.lower():
                return None
            
            # Extract digits in case it wrapped
            digits = ''.join(filter(str.isdigit, answer))
            if digits:
                return int(digits)
            return None
        except Exception as e:
            print(f"Tier B LLM Error: {e}")
            return None

    def tier_c_fallback(self, term: dict) -> Optional[int]:
        """Creates a new Concept via DeepSeek generating a summary."""
        raw_latex = term['latex_content'] or ""
        term_context = f"Name: {term['name']}\nType: {term['term_type']}\nConcepts: {term['used_terms']}\nStatement: {raw_latex}"
        
        prompt = f"""You are an expert mathematical ontologist. 
We have a mathematical term that does not match any existing concepts:
{term_context}

Task: Create a concise, 1-2 sentence dense semantic summary for this concept to act as its general canonical definition. 
Also, determine a broad 'subject_area' (e.g., General Topology, Linear Algebra, Real Analysis).
Finally, provide a 'canonical_name' for this concept. 

CRITICAL RULES for 'canonical_name':
1. Remove ALL book-specific prefixes like 'Theorem 4.1:', 'Lemma 2:', 'Corollary:', 'Proposition 3.2.1:', 'Example:', 'Remark:'.
2. Remove ALL numbering (e.g. '1.1 Cauchy Schwarz' -> 'Cauchy-Schwarz Inequality').
3. Ensure the name is the standard global name for this concept if one exists.
4. Capitalize correctly (Title Case).
5. If the term is titled something generic like 'Theorem' or 'Lemma', use the statement content to derive a descriptive canonical name.

Return a JSON object strictly in this format:
{{
    "canonical_name": "Clean Concept Name",
    "subject_area": "Subject Name",
    "summary": "The 1-2 sentence dense abstract summary."
}}
IMPORTANT: Since the output is JSON, you MUST double-escape any LaTeX backslashes (e.g., write \\\\mathbb{{R}} instead of \\mathbb{{R}}).
Do NOT use markdown code blocks like ```json.
"""
        try:
            response = ai.deepseek.client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.2
            )
            data_str = response.choices[0].message.content.strip()
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                import re
                data_str = re.sub(r'(?<!\\)\\(?!["\\/bfnrt])', r'\\\\', data_str)
                data = json.loads(data_str)
            
            # Mint new concept
            name = data.get('canonical_name', term['name'])
            subject_area = data.get('subject_area', 'General Mathematics')
            summary = data.get('summary', '')
            
            # Save to SQLite
            concept_id = None
            with db.get_connection() as conn:
                try:
                    cursor = conn.execute(
                        "INSERT INTO mathematical_concepts (name, subject_area, summary, source) VALUES (?, ?, ?, ?)",
                        (name, subject_area, summary, "DeepSeek Auto-Generated")
                    )
                    concept_id = cursor.lastrowid
                    conn.commit()
                except sqlite3.IntegrityError:
                    # In case of exact name/subject collision
                    existing = conn.execute("SELECT id FROM mathematical_concepts WHERE name=? AND subject_area=?", (name, subject_area)).fetchone()
                    if existing:
                        concept_id = existing[0]
                    else:
                        raise
                
            # Get its embedding and sync
            concept_dict = {'id': concept_id, 'name': name, 'subject_area': subject_area, 'summary': summary}
            text_to_embed = build_concept_emb_string(concept_dict)
            emb = get_embedding_with_retry(text_to_embed)
            
            if emb:
                emb_bytes = np.array(emb, dtype=np.float32).tobytes()
                with db.get_connection() as conn:
                    conn.execute("UPDATE mathematical_concepts SET embedding = ? WHERE id = ?", (emb_bytes, concept_id))
                    conn.commit()
                    
                # Upsert to ES
                es_client.index(
                    index="mathstudio_concepts",
                    id=str(concept_id),
                    document={
                        "id": concept_id,
                        "name": name,
                        "subject_area": subject_area,
                        "summary": summary,
                        "embedding": list(emb)
                    }
                )
                es_client.indices.refresh(index="mathstudio_concepts")
                
            return concept_id
        except Exception as e:
            print(f"Tier C Error: {e}")
            return None

    def _process_tier_a(self, term: dict) -> tuple:
        """Parallel worker for Tier A."""
        t_id = term['id']
        try:
            # We get the term's embedding from ES
            res = es_client.get(index="mathstudio_terms", id=str(t_id), _source=["embedding"])
            if 'embedding' not in res['_source']:
                return t_id, "NONE", None
            
            emb = res['_source']['embedding']
            candidates = self.vector_search_concepts(emb, k=3)
            
            if not candidates:
                return t_id, "NONE", None
                
            top_score = candidates[0]['score']
            if top_score >= MAX_THRESHOLD:
                # Tentative exact link
                return t_id, "LINKED", candidates[0]['doc']['id']
            elif top_score >= MIN_THRESHOLD:
                # Ambiguous
                return t_id, "AMBIGUOUS", candidates
            else:
                return t_id, "NONE", None
        except Exception as e:
            # Document missing or error
            return t_id, "NONE", None

    def run_clustering(self):
        with db.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            terms = conn.execute("SELECT * FROM knowledge_terms WHERE concept_id IS NULL").fetchall()
            
        print(f"Found {len(terms)} unlinked terms to process.")
        if not terms:
            return
            
        # 1. Tier A - Massive Parallel Vectors
        print("Starting Tier A (Vector Matching)...")
        tier_a_results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(self._process_tier_a, dict(t)): dict(t) for t in terms}
            for i, future in enumerate(concurrent.futures.as_completed(futures)):
                term = futures[future]
                res = future.result()
                tier_a_results.append((term, res))
                if (i+1) % 100 == 0:
                    print(f"Tier A Processed {i+1}/{len(terms)} terms.")
                    
        linked_to_update = []
        ambiguous_queue = []
        none_queue = []
        
        for term, (t_id, status, data) in tier_a_results:
            if status == "LINKED":
                linked_to_update.append((data, t_id))
            elif status == "AMBIGUOUS":
                ambiguous_queue.append((term, data))
            else:
                none_queue.append((term, None))
                
        # Bulk commit Tier A Links
        if linked_to_update:
            with db.get_connection() as conn:
                conn.executemany("UPDATE knowledge_terms SET concept_id = ? WHERE id = ?", linked_to_update)
                conn.commit()
            print(f"Tier A firmly linked {len(linked_to_update)} terms.")
            
        # 2. Sequential Queue for Tiers B and C
        sequential_queue = ambiguous_queue + none_queue
        print(f"Starting Tiers B and C for {len(sequential_queue)} terms sequentially...")
        
        b_linked = 0
        c_minted = 0
        
        for idx, (term, _) in enumerate(sequential_queue):
            # Re-evaluate Tier A to catch any newly minted Concepts
            _, status, new_data = self._process_tier_a(term)
            
            concept_id = None
            if status == "LINKED":
                concept_id = new_data
                # Update DB immediately
                with db.get_connection() as conn:
                    conn.execute("UPDATE knowledge_terms SET concept_id = ? WHERE id = ?", (concept_id, term['id']))
                    conn.commit()
                if (idx+1) % 10 == 0:
                    print(f"Tiers B/C Processed {idx+1}/{len(sequential_queue)}... (Tier A Linked: {idx+1-b_linked-c_minted}, Tier B: {b_linked}, Tier C: {c_minted})")
                continue
                
            cands = new_data if status == "AMBIGUOUS" else None
            
            # Tier B
            if cands:
                concept_id = self.tier_b_librarian(term, cands)
                if concept_id:
                    b_linked += 1
                    
            # Tier C
            if not concept_id:
                concept_id = self.tier_c_fallback(term)
                if concept_id:
                    c_minted += 1
                    
            if concept_id:
                with db.get_connection() as conn:
                    conn.execute("UPDATE knowledge_terms SET concept_id = ? WHERE id = ?", (concept_id, term['id']))
                    conn.commit()
                    
            if (idx+1) % 10 == 0:
                print(f"Tiers B/C Processed {idx+1}/{len(sequential_queue)}... (Tier B: {b_linked}, Tier C: {c_minted})")

        print(f"\nAnchoring Complete! Total newly linked: Tier A={len(linked_to_update)}, Tier B={b_linked}, Tier C newly minted={c_minted}")

if __name__ == '__main__':
    service = AnchoringService()
    service.run_clustering()
