import os
import sys
import time
import json
import traceback

# Add the parent directory to sys.path to import mathstudio modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import db
from experimental_mac_llm.mlx_client import MLXClient

class ExperimentalWorker:
    """
    Decoupled background worker for the Trickle-Feed Architecture.
    Polls the 'llm_tasks' table for 'extract_page_mlx' tasks.
    """
    def __init__(self):
        self.client = MLXClient(host="192.168.178.26")
        self.poll_interval = 5  # seconds
        
    def get_pending_task(self):
        with db.get_connection() as conn:
            # We look for specific experimental tasks to avoid touching prod queue
            task = conn.execute('''
                SELECT id, payload, retry_count
                FROM llm_tasks 
                WHERE status = 'pending' AND task_type = 'extract_page_mlx'
                ORDER BY priority DESC, id ASC
                LIMIT 1
            ''').fetchone()
            
            if task:
                # Mark as processing
                conn.execute("UPDATE llm_tasks SET status = 'processing' WHERE id = ?", (task['id'],))
                conn.commit()
                return dict(task)
            return None
            
    def validate_latex(self, text: str) -> bool:
        """Deterministic structural checks."""
        # Simple balanced begin/end environment check
        begins = text.count(r"\begin{")
        ends = text.count(r"\end{")
        return begins == ends and len(text.strip()) > 50

    def process_task(self, task: dict):
        task_id = task['id']
        payload = json.loads(task['payload'])
        retry_count = task['retry_count']
        
        book_id = payload.get('book_id')
        page_number = payload.get('page_number')
        
        print(f"\n--- Processing Task {task_id}: Book {book_id}, Page {page_number} (Retry {retry_count}) ---")
        
        try:
            # 1. Ensure page slice exists (using existing PDF handler)
            # Find the book path
            with db.get_connection() as conn:
                book = conn.execute("SELECT path FROM books WHERE id = ?", (book_id,)).fetchone()
                
            if not book:
                raise ValueError(f"Book {book_id} not found")
                
            temp_img_path = os.path.join("/tmp", f"mathstudio_temp_p{page_number}.png")
            
            print(f"Extracting page {page_number} to {temp_img_path}...")
            import fitz
            from core.config import LIBRARY_ROOT
            full_book_path = os.path.join(LIBRARY_ROOT, book['path'])
            doc = fitz.open(full_book_path)
            if page_number < 1 or page_number > len(doc):
                doc.close()
                raise ValueError(f"Page {page_number} out of range (max {len(doc)})")
            
            page = doc[page_number - 1]
            
            # Create a Pixmap with a white background so VLM doesn't hallucinate a blank page
            mat = fitz.Matrix(2, 2)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            
            # If the image was originally transparent, PyMuPDF might default it to black.
            # Convert to a PIL image and force a white background just in case
            from PIL import Image
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            # Check if it was transparent, and if so paste it onto white
            if page.get_pixmap(matrix=mat).alpha:
                pix_alpha = page.get_pixmap(matrix=mat, alpha=True)
                img_with_alpha = Image.frombytes("RGBA", [pix_alpha.width, pix_alpha.height], pix_alpha.samples)
                background = Image.new("RGB", img_with_alpha.size, (255, 255, 255))
                background.paste(img_with_alpha, mask=img_with_alpha.split()[3]) # 3 is the alpha channel
                img = background

            img.save(temp_img_path, format="PNG")
            doc.close()

            # 2. Dynamic Temperature based on retries
            # 0.0 for first try (deterministic), 0.3 for first retry, 0.6 for second
            temperature = min(0.0 + (retry_count * 0.3), 0.7)
            
            prompt = "Please transcribe the entire contents of this textbook page. Output all the prose text exactly as written, and format any mathematical equations or formulas using valid LaTeX within standard $...$ or $$...$$ delimiters. Do not summarize; maintain the exact wording, structure, and order of the original page. Output only the content, no markdown fences."
            
            # 3. Request MLX Inference Node
            raw_latex = self.client.generate_vision(temp_img_path, prompt, temperature=temperature)
            
            if not raw_latex:
                 raise RuntimeError("MLX Client returned None. Node might be down or busy.")
                 
            print("\n" + "="*40 + "\n--- MLX OUTPUT ---\n")
            print(raw_latex)
            print("\n" + "="*40 + "\n")
            
            output_file = f"/tmp/mlx_output_b{book_id}_p{page_number}.tex"
            with open(output_file, "w") as f:
                f.write(raw_latex)
            print(f"Saved raw LaTeX to {output_file}")
                 
            # 4. Deterministic Gating
            if self.validate_latex(raw_latex):
                print("Validation SUCCESS. Saving to cache...")
                # Save block to extracted_pages cache
                with db.get_connection() as conn:
                    # Mark successful processing status and output
                    conn.execute("UPDATE llm_tasks SET status = 'completed', result = ? WHERE id = ?", (raw_latex, task_id))
                    
                    # Store result (simplified for experiment)
                    # For prod, you'd save actual file paths here
                    print(f"Stashed successfully validated output for Book {book_id} Page {page_number}")
                    conn.commit()
            else:
                 print("Validation FAILED (mismatched tags or empty output). Requeuing...")
                 raise ValueError("LaTeX Structural Validation Failed.")

        except Exception as e:
            err_msg = str(e)
            print(f"Task Failed: {err_msg}")
            
            with db.get_connection() as conn:
                 if retry_count >= 3: # Max retries
                     conn.execute(
                         "UPDATE llm_tasks SET status = 'failed', error_log = ? WHERE id = ?", 
                         (json.dumps({"error": err_msg}), task_id)
                     )
                 else:
                     conn.execute(
                         "UPDATE llm_tasks SET status = 'pending', retry_count = retry_count + 1 WHERE id = ?", 
                         (task_id,)
                     )
                 conn.commit()

    def run(self):
        print("Starting Experimental MLX Trickle-Feed Worker...")
        print(f"Connected to Intel Queue, waiting for 'extract_page_mlx' tasks...")
        while True:
            task = self.get_pending_task()
            if task:
                self.process_task(task)
            else:
                time.sleep(self.poll_interval)

if __name__ == "__main__":
    worker = ExperimentalWorker()
    try:
        worker.run()
    except KeyboardInterrupt:
        print("\nWorker shutting down.")
