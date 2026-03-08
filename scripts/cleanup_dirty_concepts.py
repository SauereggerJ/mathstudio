import sqlite3
import json
import os
import sys
import re
from typing import List, Dict, Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import db
from core.ai import ai
from core.config import GEMINI_MODEL

def clean_concept_names_batch(names: List[str]) -> Dict[str, str]:
    """Uses Gemini to strip book-specific prefixes for a batch of names."""
    if not names: return {}
    
    names_list_str = "\n".join([f"- {n}" for n in names])
    prompt = f"""You are a mathematical ontologist. 
Your task is to take a list of mathematical concept names and remove any book-specific prefixes, numbering, or labels (e.g., 'Theorem 1.1:', 'Lemma 4.2:', 'Proposition:', 'Exercise 5:').
The goal is to get the pure, canonical name of the mathematical concept.

List of names:
{names_list_str}

Return a JSON object where keys are original names and values are cleanedNames. 
Example Output: {{"Theorem 1.1: Cauchy Schwarz": "Cauchy Schwarz"}}
If a name is already canonical, keep it as is.
"""

    try:
        response = ai.generate_json(prompt)
        if isinstance(response, dict):
            return response
        return {n: n for n in names}
    except Exception as e:
        print(f"Error in batch cleaning: {e}")
        return {n: n for n in names}

def run_cleanup(apply=False):
    # Simplified query for now to avoid REGEXP dependency issues in current db manager
    with db.get_connection() as conn:
        conn.row_factory = sqlite3.Row
        concepts = conn.execute("""
            SELECT id, name, subject_area FROM mathematical_concepts 
            WHERE name LIKE '%:%' 
               OR name LIKE 'Theorem %'
               OR name LIKE 'Lemma %'
               OR name LIKE 'Proposition %'
               OR name LIKE 'Corollary %'
               OR name LIKE 'Definition %'
               OR name LIKE 'Example %'
               OR name LIKE 'Remark %'
               OR name LIKE '1.%' OR name LIKE '2.%' OR name LIKE '3.%' OR name LIKE '4.%' 
               OR name LIKE '5.%' OR name LIKE '6.%' OR name LIKE '7.%' OR name LIKE '8.%' OR name LIKE '9.%'
        """).fetchall()
        
    print(f"Checking {len(concepts)} concepts for cleaning...")
    
    # Track clean names to detect collisions early
    # (name, subject_area) -> [list of IDs]
    canonical_clusters = {}
    
    # 1. First Pass: Identify intended clean names in batches
    id_to_clean_map = {}
    batch_size = 50
    for i in range(0, len(concepts), batch_size):
        batch = concepts[i:i+batch_size]
        batch_names = [c['name'] for c in batch]
        
        print(f"Cleaning batch {i//batch_size + 1}/{(len(concepts)-1)//batch_size + 1}...")
        cleaned_batch = clean_concept_names_batch(batch_names)
        
        for c in batch:
            original_name = c['name']
            original_id = c['id']
            subject = c['subject_area']
            
            clean_name = cleaned_batch.get(original_name, original_name)
            
            if clean_name != original_name:
                print(f"CLEAN: '{original_name}' -> '{clean_name}'")
                id_to_clean_map[original_id] = clean_name
                key = (clean_name.lower().strip(), subject)
                if key not in canonical_clusters:
                    canonical_clusters[key] = []
                canonical_clusters[key].append(original_id)
            else:
                # Also track existing "clean" ones to check against them for merges
                key = (original_name.lower().strip(), subject)
                if key not in canonical_clusters:
                    canonical_clusters[key] = []
                canonical_clusters[key].append(original_id)

    # 2. Second Pass: Find external clean concepts already in database that we might collide with
    # (not captured by the initial prefix query)
    with db.get_connection() as conn:
        all_concepts = conn.execute("SELECT id, name, subject_area FROM mathematical_concepts").fetchall()
        for c in all_concepts:
            key = (c['name'].lower().strip(), c['subject_area'])
            cid = c['id']
            if key in canonical_clusters and cid not in canonical_clusters[key]:
                canonical_clusters[key].append(cid)

    # 3. Third Pass: Consolidate updates and merges
    updates = [] # (new_name, id)
    merges = []  # (survivor_id, list_of_deletable_ids)
    
    for key, ids in canonical_clusters.items():
        if not ids: continue
        
        # Pick a survivor. Preference:
        # 1. An existing concept that already has EXACTLY the target name (no case change needed)
        # 2. Lowest ID
        target_name_normalized = key[0]
        subject = key[1]
        
        survivor_id = None
        # Try to find one that already has the target name exactly (case-sensitive)
        with db.get_connection() as conn:
            # We need to check the database because 'ids' might have come from different passes
            for cid in ids:
                row = conn.execute("SELECT id, name FROM mathematical_concepts WHERE id = ?", [cid]).fetchone()
                if row and row['name'] == id_to_clean_map.get(cid, row['name']): # If its current or intended name matches
                    pass
                # Actually, let's just pick one that is already in the DB with the right name to avoid updates
                row = conn.execute("SELECT id FROM mathematical_concepts WHERE id = ? AND name = ?", [cid, target_name_normalized]).fetchone()
                if row:
                    survivor_id = cid
                    break
        
        if survivor_id is None:
            survivor_id = min(ids)
            
        ids_to_merge = [i for i in ids if i != survivor_id]
        if ids_to_merge:
            merges.append((survivor_id, ids_to_merge))
        
        # Prepare name update for the survivor if its CURRENT name doesn't match the intended clean name
        intended_name = id_to_clean_map.get(survivor_id)
        if intended_name:
             with db.get_connection() as conn:
                 current = conn.execute("SELECT name FROM mathematical_concepts WHERE id = ?", [survivor_id]).fetchone()
                 if current and current['name'] != intended_name:
                     updates.append((intended_name, survivor_id))

    if apply:
        print(f"\nAPPLYING CHANGES:")
        print(f"- {len(merges)} Concept merges")
        print(f"- {len(updates)} Name updates")
        
        with db.get_connection() as conn:
            # 1. Handle merges FIRST (this frees up names)
            for survivor_id, deletables in merges:
                placeholders = ','.join(['?'] * len(deletables))
                # Update knowledge_terms
                conn.execute(f"UPDATE knowledge_terms SET concept_id = ? WHERE concept_id IN ({placeholders})", [survivor_id] + deletables)
                # Delete redundant concepts
                conn.execute(f"DELETE FROM mathematical_concepts WHERE id IN ({placeholders})", deletables)
                # Remove from ES
                try:
                    from core.search_engine import es_client
                    for rid in deletables:
                        es_client.delete(index="mathstudio_concepts", id=str(rid), ignore=[404])
                except Exception:
                    pass
            
            # 2. Handle name updates NEXT
            conn.executemany("UPDATE mathematical_concepts SET name = ? WHERE id = ?", updates)
            conn.commit()
        print("Database synchronized.")
    else:
        print(f"\nDry Run Results:")
        print(f"- Found {len(updates)} names to clean.")
        print(f"- Found {len(merges)} groups of concepts to merge.")
        print("Use --apply to commit.")

if __name__ == "__main__":
    apply_flag = len(sys.argv) > 1 and sys.argv[1] == "--apply"
    run_cleanup(apply=apply_flag)
