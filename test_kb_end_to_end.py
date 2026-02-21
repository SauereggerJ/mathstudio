from services.knowledge import knowledge_service
import json

def test_kb():
    print("Testing Knowledge Base...")
    
    # 1. Add Concept
    res = knowledge_service.add_concept(
        name="Compactness",
        kind="definition",
        domain="54D30",
        aliases=["kompakt", "folgenkompakt"]
    )
    print(f"Add Concept: {res}")
    if not res.get('success') and 'already exists' not in res.get('error', ''):
        return
    
    concept_id = res.get('id') or 1
    
    # 2. Add Entry
    res = knowledge_service.add_entry(
        concept_id=concept_id,
        statement="A topological space X is called compact if every open cover of X has a finite subcover.",
        notes="Classical Borel-Lebesgue definition.",
        scope="undergraduate",
        style="topological"
    )
    print(f"Add Entry: {res}")
    
    # 3. Render Vault Note
    res = knowledge_service.write_obsidian_note(concept_id)
    print(f"Render Note: {res}")
    
    # 4. Search
    res = knowledge_service.search_concepts("compact")
    print(f"Search Results: {len(res)}")
    for r in res:
        print(f" - {r.get('name', r.get('concept_name'))} ({r.get('kind')})")

if __name__ == "__main__":
    test_kb()
