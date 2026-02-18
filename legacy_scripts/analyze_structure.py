import os
import random
from pathlib import Path
from pypdf import PdfReader

LIBRARY_ROOT = Path(".." ) 

def analyze_pdf_structure(sample_size=10):
    pdf_files = []
    for root, dirs, files in os.walk(LIBRARY_ROOT):
        if "mathstudio" in root: continue
        for file in files:
            if file.lower().endswith('.pdf'):
                pdf_files.append(Path(root) / file)
    
    if not pdf_files:
        print("No PDFs found.")
        return

    sample = random.sample(pdf_files, min(len(pdf_files), sample_size))
    
    print(f"Analyzing {len(sample)} random PDFs for structure...\n")
    
    stats = {
        'logical_toc': 0,
        'text_toc': 0,
        'index_found': 0
    }

    for pdf_path in sample:
        print(f"Checking: {pdf_path.name}")
        try:
            reader = PdfReader(pdf_path)
            
            # 1. Check Logical Outlines (Bookmarks)
            has_outline = False
            try:
                if reader.outline and len(reader.outline) > 0:
                    has_outline = True
                    stats['logical_toc'] += 1
            except Exception:
                pass
            
            # 2. Check Textual ToC (First 20 pages)
            has_text_toc = False
            num_pages = len(reader.pages)
            check_limit = min(num_pages, 20)
            
            for i in range(check_limit):
                try:
                    text = reader.pages[i].extract_text().lower()
                    if "contents" in text or "table of contents" in text:
                        has_text_toc = True
                        stats['text_toc'] += 1
                        break
                except: pass
                
            # 3. Check Index (Last 20 pages)
            has_index = False
            start_check = max(0, num_pages - 20)
            for i in range(start_check, num_pages):
                try:
                    text = reader.pages[i].extract_text().lower()
                    if "index" in text and len(text) < 3000: # Simple heuristic
                        # Check if it looks like an index (e.g., lots of numbers, or comma separated)
                        lines_with_nums = [l for l in text.splitlines() if any(c.isdigit() for c in l)]
                        if len(lines_with_nums) > 5: 
                            has_index = True
                            stats['index_found'] += 1
                            break
                except: pass
            
            print(f"  -> Outlines: {'YES' if has_outline else 'NO'} | 'Contents' Text: {'YES' if has_text_toc else 'NO'} | Index: {'YES' if has_index else 'NO'}")

        except Exception as e:
            print(f"  -> Error: {e}")

    print("\n--- Summary ---")
    print(f"Total Sampled: {len(sample)}")
    print(f"With Logical Outlines: {stats['logical_toc']} ({stats['logical_toc']/len(sample)*100:.1f}%)")
    print(f"With 'Contents' Text:  {stats['text_toc']} ({stats['text_toc']/len(sample)*100:.1f}%)")
    print(f"With 'Index' Text:     {stats['index_found']} ({stats['index_found']/len(sample)*100:.1f}%)")

if __name__ == "__main__":
    analyze_pdf_structure()
