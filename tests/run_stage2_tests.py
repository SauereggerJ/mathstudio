import sys
import os
import json
import logging
from pathlib import Path

# Setup path to import MathStudio core logic
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import db
from core.ai import ai
from services.pipeline import pipeline_service

logger = logging.getLogger(__name__)

TESTSUITE_DIR = Path("/library/mathstudio/tests/stage2_dataset")
MANIFEST_PATH = TESTSUITE_DIR / "manifest.json"
RESULTS_PATH = TESTSUITE_DIR / "results.json"

def run_tests():
    if not MANIFEST_PATH.exists():
        print("Manifest not found")
        return
        
    manifest = json.loads(MANIFEST_PATH.read_text())
    
    # We duplicate the exact prompt from pipeline.py for isolated execution.
    prompt_tmpl = """You are a mathematical knowledge extraction agent.
BOOK: "{title}" by {author}

Below are 3 consecutive pages of raw LaTeX. Identify terms (Definition, Theorem, Lemma, etc.) that BEGIN on PAGE {p}.
Pages {p1} and {p2} are overflow context.

CRITICAL RULES:
1. ONLY extract items that legitimately BEGIN on PAGE {p}.
2. Theorems usually have Proofs. A Proof MUST be captured together with its Theorem as a SINGLE combined body.
   - If the Theorem begins on PAGE {p}, extract the Theorem AND its entire Proof, even if the Proof spills over onto PAGE {p1} or {p2}.
   - If the Theorem began on a PREVIOUS page (before PAGE {p}) and only its Proof spills over onto PAGE {p}, DO NOT extract the Proof here. It was already securely captured when the previous page was processed.
3. Therefore: NEVER extract an isolated "Proof" as its own term.
4. NAMING: If a term has an explicitly written name (e.g. "Cauchy-Schwarz Inequality"), use it. If the term is unnamed (e.g. just "Lemma 1.7", "Theorem 2.13", or "Example"), YOU MUST formulate a concise, descriptive name based on its mathematical content (e.g., "Lemma 1.7: Continuity of Stronger Norms" or "Example: Incomplete L^2 Sequence"). Do not output generic names like "Lemma 2.14" without adding descriptive context.

Format:
### [Name] ([Type])
Keywords: kw1, kw2
[LaTeX Body]

---

Return exactly the string NO_TERMS_FOUND if no valid terms begin on PAGE {p}."""

    # Fetch books for prompt substitution
    books = {}
    with db.get_connection() as conn:
        for row in conn.execute("SELECT id, title, author FROM books").fetchall():
            books[row['id']] = row
            
    results = []
    
    for tc in manifest:
        print(f"Testing {tc['name']}...")
        book_id = tc['context_files'][0]['book_id']
        p = tc['context_files'][0]['page_number']
        
        book = books.get(book_id, {'title': 'Test Book', 'author': 'Test Author'})
        
        texts = []
        for cf in tc['context_files']:
            f_path = TESTSUITE_DIR / tc['name'] / cf['file']
            texts.append(f_path.read_text(encoding='utf-8') if f_path.exists() else "")
            
        text_n  = texts[0]
        text_n1 = texts[1] if len(texts) > 1 else ""
        text_n2 = texts[2] if len(texts) > 2 else ""
        
        prompt = prompt_tmpl.format(
            title=book['title'], author=book['author'], 
            p=p, p1=p+1, p2=p+2
        ) + f"\n\n=== PAGE {p} ===\n{text_n}\n\n=== PAGE {p+1} ===\n{text_n1}\n\n=== PAGE {p+2} ===\n{text_n2}"
        
        try:
            # Send text request which will be routed to DeepSeek
            response = ai.generate_text(prompt)
            # Parse it the exact same way the app does
            parsed_terms = pipeline_service._parse_extraction_output(response, p)
            
            # Analyze for errors
            isolated_proofs = []
            if parsed_terms:
                isolated_proofs = [t for t in parsed_terms if 'proof' in t['name'].lower() or 'proof' in t['type'].lower()]
            
            results.append({
                "name": tc['name'],
                "description": tc['description'],
                "raw_response": response,
                "parsed_terms": parsed_terms,
                "isolated_proofs_count": len(isolated_proofs),
                "total_extracted": len(parsed_terms) if parsed_terms else 0
            })
            
            print(f"  -> Extracted {len(parsed_terms) if parsed_terms else 0} terms. Isolated proofs found: {len(isolated_proofs)}")
        except Exception as e:
            print(f"  -> Error: {e}")
            
    RESULTS_PATH.write_text(json.dumps(results, indent=2))
    print(f"\nFinished! Full analysis written to {RESULTS_PATH}")

if __name__ == '__main__':
    run_tests()
