import sys
import os
import json
import time
from pathlib import Path

# Add project root to sys.path
sys.path.append(os.getcwd())

from core.database import db
from core.ai import ai
from core.config import LIBRARY_ROOT, PROJECT_ROOT
from experimental_mac_llm.mlx_client import MLXClient

def run_benchmark(limit=None):
    print("Starting M2 vs Gemini Comparative Pipeline Test Suite...")
    
    # 1. Fetch High Quality Gemini Samples
    # We use samples with quality_score >= 0.7 as our "ground truth"
    query = "SELECT book_id, page_number, latex_path FROM extracted_pages WHERE quality_score >= 0.7 ORDER BY created_at DESC"
    if limit:
        query += f" LIMIT {limit}"
        
    with db.get_connection() as conn:
        samples = [dict(r) for r in conn.execute(query).fetchall()]
        
    if not samples:
        print("ERROR: No high-quality Gemini samples found in database to compare against.")
        return

    print(f"Targeting {len(samples)} high-quality samples for benchmarking.")
    
    results = []
    client = MLXClient()
    
    # Updated prompt to match typesetter expectations
    extraction_prompt = (
        "You are a master mathematical typesetter. Convert this image of a book page into high-quality LaTeX. "
        "Focus on structural correctness, preserving all formulas, and ignore headers/footers. Return ONLY the LaTeX."
    )

    for i, sample in enumerate(samples):
        book_id = sample['book_id']
        page_num = sample['page_number']
        gemini_tex_rel = sample['latex_path']
        
        print(f"\n[{i+1}/{len(samples)}] Benchmarking Book {book_id} Page {page_num}...")
        
        # Read Ground Truth (Gemini LaTeX)
        gemini_tex_abs = PROJECT_ROOT / gemini_tex_rel
        if not gemini_tex_abs.exists():
            print(f"  !! Skipping: Gemini TeX file missing at {gemini_tex_abs}")
            continue
            
        with open(gemini_tex_abs, 'r', encoding='utf-8') as f:
            gemini_latex = f.read()

        # Check if M2 already has a result in llm_tasks (to save time/resources)
        # Note: We now FORCE a fresh extraction if we want to test the new prompt
        m2_latex = None
        
        print("  Triggering fresh M2 extraction on Mac Node...")
        
        # Get physical book path
        with db.get_connection() as conn:
            book = conn.execute("SELECT path FROM books WHERE id = ?", (book_id,)).fetchone()
        
        if not book:
            print(f"  !! Error: Book ID {book_id} record missing.")
            continue
            
        abs_book_file = LIBRARY_ROOT / book['path']
        if not abs_book_file.exists():
            print(f"  !! Error: Physical PDF missing at {abs_book_file}")
            continue
        
        # Render page to temporary PNG
        import fitz
        try:
            doc = fitz.open(str(abs_book_file))
            page = doc[page_num - 1]
            tmp_img = f"/tmp/bench_b{book_id}_p{page_num}.png"
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            pix.save(tmp_img)
            doc.close()
            
            # Call M2 Node
            m2_latex = client.generate_vision(tmp_img, extraction_prompt)
            
            # Cleanup
            if os.path.exists(tmp_img):
                os.remove(tmp_img)
                
        except Exception as e:
            print(f"  !! PyMuPDF / Network Error: {e}")
            continue
            
        if not m2_latex or len(m2_latex) < 50:
            print("  !! Error: M2 generation returned empty or insufficient content.")
            continue
            
        # 3. Objective Comparison via Gemini LLM Judge
        print("  Evaluating quality vs Ground Truth...")
        comparison_prompt = f"""Compare these two LaTeX transcriptions of a mathematical book page.
GROUND TRUTH (Gold standard from Gemini 2.0):
{gemini_latex}

EXPERIMENTAL CANDIDATE (M2 Node - Qwen2.5-VL):
{m2_latex}

Evaluate the M2 candidate based on:
1. Mathematical precision (hallucinations, sign errors).
2. Completeness (missing paragraphs, truncated lists).
3. LaTeX formatting (AMS environments, proper nesting).

Return a JSON object:
{{
  "verdict": "better" | "equal" | "very_similar" | "worse",
  "similarity_score": 0.0 to 1.0,
  "justification": "Detailed technical analysis of differences"
}}
"""
        try:
            comparison = ai.generate_json(comparison_prompt)
            if comparison:
                comparison['book_id'] = book_id
                comparison['page_num'] = page_num
                comparison['m2_length'] = len(m2_latex)
                comparison['gemini_length'] = len(gemini_latex)
                results.append(comparison)
                print(f"  Verdict: [{comparison['verdict'].upper()}] - Score: {comparison['similarity_score']}")
                print(f"  Justification: {comparison['justification']}")
                if comparison['similarity_score'] < 0.7:
                     print("--- M2 RAW OUTPUT (FIRST 300 CHARS) ---")
                     print(m2_latex[:300])
                     print("-----------------------------------------")
            else:
                print("  !! Comparison judging failed.")
        except Exception as e:
            print(f"  !! Judge Error: {e}")

    # --- Final Analysis ---
    if not results:
        print("\nBenchmark failed: No results collected.")
        return

    # User defined passing criteria: "better", "very_similar", or "equal"
    pass_count = sum(1 for r in results if r['verdict'] in ['better', 'very_similar', 'equal'])
    total = len(results)
    pass_rate = (pass_count / total * 100)
    
    # Store report
    report = {
        "timestamp": int(time.time()),
        "total_passed": pass_count,
        "total_tested": total,
        "pass_rate_percent": round(pass_rate, 2),
        "target_threshold": 70.0,
        "success": pass_rate >= 70.0,
        "detailed_results": results
    }
    
    print("\n" + "="*40)
    print("      M2 PIPELINE BENCHMARK REPORT")
    print("="*40)
    print(f"  STATUS:      {'PASSED' if report['success'] else 'FAILED'}")
    print(f"  PASS RATE:   {report['pass_rate_percent']}% (Target: 70%)")
    print(f"  SAMPLE SIZE: {total}")
    print("="*40)
    
    out_path = Path("m2_benchmark_summary.json")
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)
    print(f"\nSaved detailed JSON report to: {out_path.absolute()}")
    
    # Save a human-readable snippet
    txt_path = Path("m2_benchmark_report.txt")
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(f"M2 PIPELINE BENCHMARK REPORT\n")
        f.write(f"Timestamp: {time.ctime()}\n")
        f.write(f"Result: {'PASS' if report['success'] else 'FAIL'}\n")
        f.write(f"Score: {report['pass_rate_percent']}% against 70% threshold\n\n")
        for r in results:
            f.write(f"[{r['verdict'].upper()}] B{r['book_id']} P{r['page_num']} (Score: {r['similarity_score']})\n")
            f.write(f"Note: {r['justification'][:200]}...\n\n")
            
    print(f"Saved human-readable summary to: {txt_path.absolute()}")

if __name__ == "__main__":
    # Run comparison against the 27 identified high-quality samples
    run_benchmark(limit=None)
