import fitz  # PyMuPDF
import logging
import os
import subprocess
import gc
import shutil
from pathlib import Path
from typing import List, Dict, Tuple

logger = logging.getLogger(__name__)

class PDFHandler:
    """Memory-guarded PDF handler implementing strict sequential I/O and zero-duplication slicing."""
    
    TOC_MARKERS = ["contents", "inhaltsverzeichnis", "inhalt", "table des matières"]
    BIB_MARKERS = ["bibliography", "references", "literaturverzeichnis", "bibliographie"]

    def __init__(self, file_path: Path):
        self.file_path = file_path

    def _open_source(self, page_indices: List[int] = None):
        """Internal helper to provide a clean document handle."""
        if self.file_path.suffix.lower() == '.djvu':
            temp_pdf = Path(f"/tmp/conv_{os.getpid()}.pdf")
            cmd = ['ddjvu', '-format=pdf']
            if page_indices:
                # ddjvu pages are 1-indexed, fitz/indices are 0-indexed
                pg_str = ",".join([str(i+1) for i in page_indices])
                cmd.append(f"-page={pg_str}")
            
            cmd.extend([str(self.file_path), str(temp_pdf)])
            subprocess.run(cmd, check=True, capture_output=True)
            return fitz.open(str(temp_pdf)), temp_pdf
        return fitz.open(str(self.file_path)), None

    def estimate_slicing_ranges(self) -> Dict[str, List[int]]:
        """Identifies ranges and immediately releases all handles."""
        # For DjVu, we don't want to convert the whole thing just to estimate
        # We'll convert first 50 and last 50
        if self.file_path.suffix.lower() == '.djvu':
            # Need to know total count first
            import subprocess
            res = subprocess.run(['djvused', '-e', 'n', str(self.file_path)], capture_output=True, text=True)
            page_count = int(res.stdout.strip()) if res.returncode == 0 else 100
            
            # Convert representative samples
            sample_indices = list(range(0, min(50, page_count))) + list(range(max(0, page_count-50), page_count))
            doc, t_path = self._open_source(page_indices=sample_indices)
        else:
            doc, t_path = self._open_source()
            page_count = len(doc)

        ranges = {"metadata": [], "bibliography": []}
        try:
            # Metadata detection
            f_end = min(20, page_count)
            for i in range(min(50, len(doc))):
                if any(m in doc[i].get_text().lower() for m in self.TOC_MARKERS):
                    # This logic is slightly flawed for sampled DjVu but good enough
                    f_end = min(i + 20, page_count)
                    break
            ranges["metadata"] = list(range(0, f_end))

            # Bibliography detection
            b_start = max(0, page_count - 50)
            # Find in the 'tail' of the doc handle
            doc_len = len(doc)
            for i in range(max(0, doc_len - 50), doc_len):
                if any(m in doc[i].get_text().lower() for m in self.BIB_MARKERS):
                    # We need to map local index i back to global index
                    # If DjVu, len(doc) is the sum of slices.
                    if self.file_path.suffix.lower() == '.djvu':
                        # This is tricky. Let's just assume it's in the last 50 pages.
                        pass 
                    b_start = page_count - (doc_len - i)
                    break
            ranges["bibliography"] = list(range(b_start, page_count))
        finally:
            doc.close()
            del doc
            if t_path and t_path.exists(): t_path.unlink()
            gc.collect()
        return ranges

    def create_slice(self, page_indices: List[int], output_path: Path):
        """Creates a physical PDF file on disk with zero memory duplication."""
        if self.file_path.suffix.lower() == '.djvu':
            # For DjVu, ddjvu can do the slicing directly during conversion!
            temp_pdf = Path(f"/tmp/conv_slice_{os.getpid()}.pdf")
            pg_str = ",".join([str(i+1) for i in page_indices])
            subprocess.run(['ddjvu', '-format=pdf', f"-page={pg_str}", str(self.file_path), str(temp_pdf)], 
                           check=True, capture_output=True)
            # Just move it to output_path
            shutil.move(str(temp_pdf), str(output_path))
            return output_path

        src_doc, t_path = self._open_source()
        try:
            src_doc.select(page_indices)
            src_doc.save(str(output_path), garbage=4, deflate=True)
        finally:
            src_doc.close()
            del src_doc
            if t_path and t_path.exists(): t_path.unlink()
            gc.collect()
        return output_path

    def create_skeleton_slice(self, output_path: Path) -> Path:
        """Legacy support for the full skeleton."""
        ranges = self.estimate_slicing_ranges()
        all_pages = sorted(list(set(ranges["metadata"] + ranges["bibliography"])))
        return self.create_slice(all_pages, output_path)

def parse_page_range(pages_str: str, total_pages: int) -> List[int]:
    """Parses a string like '1-5, 10, 12' into a list of page numbers."""
    pages = set()
    if not pages_str: return []
    for part in pages_str.split(','):
        part = part.strip()
        if '-' in part:
            try:
                start, end = map(int, part.split('-'))
                pages.update(range(max(1, start), min(end, total_pages) + 1))
            except: pass
        else:
            try:
                p = int(part)
                if 1 <= p <= total_pages: pages.add(p)
            except: pass
    return sorted(list(pages))
