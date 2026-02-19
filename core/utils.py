import fitz  # PyMuPDF
import logging
import os
import subprocess
import gc
from pathlib import Path
from typing import List, Dict, Tuple

logger = logging.getLogger(__name__)

class PDFHandler:
    """Memory-guarded PDF handler implementing strict sequential I/O and zero-duplication slicing."""
    
    TOC_MARKERS = ["contents", "inhaltsverzeichnis", "inhalt", "table des matières"]
    BIB_MARKERS = ["bibliography", "references", "literaturverzeichnis", "bibliographie"]

    def __init__(self, file_path: Path):
        self.file_path = file_path

    def _open_source(self):
        """Internal helper to provide a clean document handle."""
        if self.file_path.suffix.lower() == '.djvu':
            temp_pdf = Path(f"/tmp/conv_{os.getpid()}.pdf")
            subprocess.run(['ddjvu', '-format=pdf', str(self.file_path), str(temp_pdf)], 
                           check=True, capture_output=True)
            return fitz.open(str(temp_pdf)), temp_pdf
        return fitz.open(str(self.file_path)), None

    def estimate_slicing_ranges(self) -> Dict[str, List[int]]:
        """Identifies ranges and immediately releases all handles."""
        doc, t_path = self._open_source()
        ranges = {"metadata": [], "bibliography": []}
        try:
            page_count = len(doc)
            # Metadata detection
            f_end = min(20, page_count)
            for i in range(min(50, page_count)):
                if any(m in doc[i].get_text().lower() for m in self.TOC_MARKERS):
                    f_end = min(i + 20, page_count)
                    break
            ranges["metadata"] = list(range(0, f_end))

            # Bibliography detection (forward scan in tail)
            b_start = max(0, page_count - 50)
            for i in range(max(0, page_count - 150), page_count):
                if any(m in doc[i].get_text().lower() for m in self.BIB_MARKERS):
                    b_start = i
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
        src_doc, t_path = self._open_source()
        try:
            # Behalte im RAM nur die exakt benötigten Seiten
            src_doc.select(page_indices)
            # Speichere diesen manipulierten State als neue Datei
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
