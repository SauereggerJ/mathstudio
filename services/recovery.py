import re
import logging
from pathlib import Path
from rapidfuzz import fuzz
from core.database import db

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent.absolute()

logger = logging.getLogger(__name__)

class DeepRecoveryService:
    def __init__(self):
        self.db = db

    def normalize(self, s):
        """Ultra-aggressive normalization for LaTeX matching."""
        if not s: return ""
        # Remove LaTeX commands, math symbols, and braces
        s = re.sub(r'\\[a-z]+(\[[^\]]*\])?\{([^}]*)\}', r'\2', s)
        s = re.sub(r'\\[a-z]+', ' ', s)
        s = s.replace('$', '').replace('{', '').replace('}', '').replace('\\', '')
        s = s.replace('~', ' ').replace('=', ' ')
        # Normalize whitespace and lower
        return re.sub(r'\s+', ' ', s).strip().lower()

    def find_marker_in_text(self, text, marker):
        """Finds a marker in text using normalized matching across line breaks."""
        if not marker: return -1
        
        norm_marker = self.normalize(marker)
        if not norm_marker: return -1
        
        # Try finding the normalized marker in the normalized text
        norm_text = self.normalize(text)
        idx = norm_text.find(norm_marker)
        
        if idx != -1:
            anchor = re.sub(r'\s+', '', norm_marker)[:12]
            if not anchor: return -1
            
            for i in range(len(text) - 12):
                snippet = re.sub(r'[^a-z0-9]', '', text[i:i+60].lower())
                if snippet.startswith(anchor):
                    return i
        
        # Fuzzy fallback
        window_size = len(marker) + 50
        best_ratio = 0
        best_idx = -1
        for i in range(0, len(text) - len(marker), 5):
            window = text[i:i+window_size]
            ratio = fuzz.partial_ratio(norm_marker, self.normalize(window))
            if ratio > 85 and ratio > best_ratio:
                best_ratio = ratio
                best_idx = i
        
        return best_idx

    def recover_term(self, term_id):
        """Attempts to recover a term by searching surrounding pages and using aggressive matching."""
        with self.db.get_connection() as conn:
            term = conn.execute("SELECT * FROM knowledge_terms WHERE id = ?", (term_id,)).fetchone()
            if not term: return False
            
            # Extract marker from placeholder
            match = re.search(r'\(marker: (.*?)\)', term['latex_content'])
            if not match: return False
            start_marker = match.group(1)
            
        book_id = term['book_id']
        page_center = term['page_start']
        
        # Search range: center +/- 2 pages
        for p_num in range(page_center - 1, page_center + 3):
            with self.db.get_connection() as conn:
                row = conn.execute(
                    "SELECT latex_path FROM extracted_pages WHERE book_id = ? AND page_number = ?",
                    (book_id, p_num)
                ).fetchone()
            
            if not row or not row['latex_path']: continue
            
            abs_path = PROJECT_ROOT / row['latex_path']
            if not abs_path.exists(): continue
            
            latex = abs_path.read_text(encoding='utf-8')
            idx = self.find_marker_in_text(latex, start_marker)
            
            if idx != -1:
                snippet = latex[idx:]
                with self.db.get_connection() as conn:
                    conn.execute("UPDATE knowledge_terms SET latex_content = ?, page_start = ? WHERE id = ?", 
                                 (snippet, p_num, term_id))
                return True
                
        return False

recovery_service = DeepRecoveryService()
