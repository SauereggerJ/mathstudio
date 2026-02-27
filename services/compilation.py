import os
import subprocess
import shutil
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from pypdf import PdfWriter, PdfReader
from core.config import NOTES_OUTPUT_DIR, CONVERTED_NOTES_DIR, COMPILED_NOTES_DIR

logger = logging.getLogger(__name__)

class CompilationService:
    def __init__(self):
        self.output_dir = COMPILED_NOTES_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def compile_tex(self, tex_path: Path) -> Optional[Path]:
        """Compiles a single .tex file using pdflatex."""
        if not tex_path.exists():
            return None
        
        pdf_path = tex_path.with_suffix('.pdf')
        
        # Optimization: only recompile if tex is newer than pdf
        if pdf_path.exists() and pdf_path.stat().st_mtime > tex_path.stat().st_mtime:
            return pdf_path

        try:
            # Run pdflatex twice for references/toc if needed
            # We use -interaction=nonstopmode to avoid hanging
            cmd = [
                'pdflatex', 
                '-interaction=nonstopmode', 
                f'-output-directory={tex_path.parent}', 
                str(tex_path)
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
            return pdf_path
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to compile {tex_path}: {e.stderr.decode()}")
            return None
        except Exception as e:
            logger.error(f"Error compiling {tex_path}: {str(e)}")
            return None

    def group_notes(self) -> Dict[str, List[Path]]:
        """Groups available PDFs by category heuristics."""
        categories = {}
        
        # Scan both directories
        sources = [NOTES_OUTPUT_DIR, CONVERTED_NOTES_DIR]
        for src in sources:
            for pdf in src.glob("*.pdf"):
                # Heuristic: try to extract category from filename
                # e.g. "Analysis 2_p123.pdf" -> "Analysis 2"
                # e.g. "20260210_131857.pdf" -> "Handwritten"
                
                name = pdf.stem
                category = "General"
                
                if "_p" in name:
                    category = name.split("_p")[0]
                elif name.startswith("202"): # Timestamp pattern
                    category = "Handwritten"
                
                if category not in categories:
                    categories[category] = []
                categories[category].append(pdf)
        
        return categories

    def compile_all(self):
        """Main entry point: compile all tex files and create category/master PDFs."""
        # 1. Compile all .tex files that don't have up-to-date PDFs
        sources = [NOTES_OUTPUT_DIR, CONVERTED_NOTES_DIR]
        for src in sources:
            for tex in src.glob("*.tex"):
                self.compile_tex(tex)

        # 2. Group existing PDFs
        groups = self.group_notes()
        
        # 3. Create category-wise merged PDFs
        master_writer = PdfWriter()
        
        for category, pdfs in groups.items():
            if not pdfs: continue
            
            cat_writer = PdfWriter()
            # Sort by filename or modification time
            pdfs.sort(key=lambda x: x.name)
            
            for pdf in pdfs:
                try:
                    reader = PdfReader(str(pdf))
                    for page in reader.pages:
                        cat_writer.add_page(page)
                        master_writer.add_page(page)
                except Exception as e:
                    logger.error(f"Error reading PDF {pdf}: {e}")

            # Save category PDF
            cat_filename = f"Category_{category.replace(' ', '_')}.pdf"
            with open(self.output_dir / cat_filename, "wb") as f:
                cat_writer.write(f)
            logger.info(f"Created category PDF: {cat_filename}")

        # 4. Save Master PDF
        master_filename = "Master_Notes.pdf"
        with open(self.output_dir / master_filename, "wb") as f:
            master_writer.write(f)
        
        return {
            "success": True,
            "categories": list(groups.keys()),
            "master_pdf": str(self.output_dir / master_filename),
            "output_dir": str(self.output_dir)
        }

    def compile_note(self, note_id):
        """Compiles a specific note and updates the DB record."""
        from services.note import note_service
        from core.database import db
        
        note = note_service.get_note(note_id)
        if not note or not note.get('latex_path'):
            return {"success": False, "error": "Note not found or has no LaTeX source."}
            
        tex_path = Path(note['latex_path'])
        pdf_path = self.compile_tex(tex_path)
        
        if pdf_path and pdf_path.exists():
            # Update DB
            with db.get_connection() as conn:
                conn.execute("UPDATE notes SET pdf_path = ? WHERE id = ?", (str(pdf_path), note_id))
            return {"success": True, "pdf_path": str(pdf_path)}
        else:
            return {"success": False, "error": "LaTeX compilation failed. Check pdflatex logs."}

compilation_service = CompilationService()
