"""
Fuzzy Book Matcher - Robust book matching for Bibliography Hunter and Wishlist Checker

This module provides a multi-strategy cascading matcher to find books in the database
with high accuracy, handling variations in titles, author names, editions, and punctuation.

Strategies (in order):
1. Exact Match - Direct title + author match (case-insensitive)
2. Normalized Match - Remove punctuation, editions, normalize author names
3. Fuzzy String Match - Levenshtein distance using rapidfuzz
4. Token-Based Match - SQL LIKE with relaxed token requirements
"""

import sqlite3
import re
from typing import Dict, List, Optional, Tuple
from rapidfuzz import fuzz
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FuzzyBookMatcher:
    """
    Multi-strategy book matcher with configurable thresholds.
    
    Usage:
        matcher = FuzzyBookMatcher('library.db', threshold=0.75)
        result = matcher.match_book('Probability and Measure', 'P. Billingsley')
    """
    
    # Stopwords to remove from titles/authors
    STOPWORDS = {
        'the', 'a', 'an', 'of', 'and', 'in', 'on', 'at', 'to', 'for', 
        'with', 'by', 'from', 'vol', 'volume', 'edition', 'ed', 
        'nd', 'rd', 'th', 'st'
    }
    
    # Edition patterns to remove
    EDITION_PATTERNS = [
        r'\(\d+(?:st|nd|rd|th)?\s*ed\.?\)',  # (2nd ed.)
        r'\d+(?:st|nd|rd|th)?\s*edition',     # 2nd edition
        r'revised\s+edition',
        r'international\s+edition',
    ]
    
    def __init__(self, db_path: str, threshold: float = 0.75, debug: bool = False):
        """
        Initialize the matcher.
        
        Args:
            db_path: Path to library.db
            threshold: Minimum similarity score (0.0-1.0) to consider a match
            debug: Enable detailed logging
        """
        self.db_path = db_path
        self.threshold = threshold
        self.debug = debug
        
        if debug:
            logger.setLevel(logging.DEBUG)
    
    def normalize_text(self, text: str, remove_editions: bool = True) -> str:
        """
        Normalize text by removing punctuation, extra spaces, and optionally edition info.
        
        Args:
            text: Input text
            remove_editions: Whether to remove edition information
            
        Returns:
            Normalized text
        """
        if not text:
            return ""
        
        # Convert to lowercase
        text = text.lower()
        
        # Remove edition information
        if remove_editions:
            for pattern in self.EDITION_PATTERNS:
                text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        
        # Remove punctuation except spaces
        text = re.sub(r'[^\w\s]', ' ', text)
        
        # Remove extra spaces
        text = ' '.join(text.split())
        
        return text.strip()
    
    def tokenize(self, text: str) -> List[str]:
        """
        Tokenize and filter text, removing stopwords.
        
        Args:
            text: Input text
            
        Returns:
            List of filtered tokens
        """
        normalized = self.normalize_text(text)
        tokens = normalized.split()
        
        # Remove stopwords
        filtered = [t for t in tokens if t not in self.STOPWORDS]
        
        # If all tokens were stopwords, return original tokens
        return filtered if filtered else tokens
    
    def expand_author_initials(self, author: str, db_cursor: sqlite3.Cursor) -> List[str]:
        """
        Expand author initials to possible full names from database.
        
        E.g., "P. Billingsley" -> ["Patrick Billingsley", "Paul Billingsley", ...]
        
        Args:
            author: Author name with possible initials
            db_cursor: Database cursor
            
        Returns:
            List of possible full author names
        """
        if not author:
            return []
        
        # Check if author has initials (single letter followed by period)
        initial_pattern = r'\b([A-Z])\.\s*(\w+)'
        match = re.search(initial_pattern, author)
        
        if not match:
            return [author]  # No initials, return as-is
        
        initial = match.group(1)
        last_name = match.group(2)
        
        # Query database for authors with this last name
        query = "SELECT DISTINCT author FROM books WHERE author LIKE ?"
        db_cursor.execute(query, (f"%{last_name}%",))
        
        candidates = []
        for row in db_cursor.fetchall():
            db_author = row[0]
            if not db_author:
                continue
            
            # Check if first name starts with the initial
            parts = db_author.split()
            if len(parts) >= 2:
                first_name = parts[0]
                if first_name.startswith(initial) and last_name.lower() in db_author.lower():
                    candidates.append(db_author)
        
        # Return candidates or original if none found
        return candidates if candidates else [author]
    
    def match_exact(self, title: str, author: Optional[str], db_cursor: sqlite3.Cursor) -> Optional[Dict]:
        """
        Strategy 1: Exact match (case-insensitive).
        
        Returns:
            Match dict with score 1.0 or None
        """
        query = "SELECT id, title, author, path FROM books WHERE LOWER(title) = ?"
        params = [title.lower()]
        
        if author:
            query += " AND LOWER(author) = ?"
            params.append(author.lower())
        
        query += " LIMIT 1"
        
        db_cursor.execute(query, params)
        row = db_cursor.fetchone()
        
        if row:
            if self.debug:
                logger.debug(f"Exact match found: {row[1]} by {row[2]}")
            return {
                'id': row[0],
                'title': row[1],
                'author': row[2],
                'path': row[3],
                'score': 1.0,
                'strategy': 'exact'
            }
        
        return None
    
    def match_normalized(self, title: str, author: Optional[str], db_cursor: sqlite3.Cursor) -> Optional[Dict]:
        """
        Strategy 2: Normalized match (remove punctuation, editions, expand initials).
        
        Returns:
            Match dict with score 0.95 or None
        """
        norm_title = self.normalize_text(title)
        
        # Expand author initials
        author_variants = [author] if author else []
        if author:
            author_variants = self.expand_author_initials(author, db_cursor)
        
        for author_variant in author_variants:
            norm_author = self.normalize_text(author_variant) if author_variant else None
            
            # Query with normalized comparison
            query = """
                SELECT id, title, author, path FROM books 
                WHERE REPLACE(REPLACE(REPLACE(LOWER(title), '.', ''), '-', ' '), ',', '') LIKE ?
            """
            params = [f"%{norm_title}%"]
            
            if norm_author:
                query += " AND REPLACE(REPLACE(REPLACE(LOWER(author), '.', ''), '-', ' '), ',', '') LIKE ?"
                params.append(f"%{norm_author}%")
            
            query += " LIMIT 1"
            
            db_cursor.execute(query, params)
            row = db_cursor.fetchone()
            
            if row:
                if self.debug:
                    logger.debug(f"Normalized match found: {row[1]} by {row[2]}")
                return {
                    'id': row[0],
                    'title': row[1],
                    'author': row[2],
                    'path': row[3],
                    'score': 0.95,
                    'strategy': 'normalized'
                }
        
        return None
    
    def match_fuzzy(self, title: str, author: Optional[str], db_cursor: sqlite3.Cursor) -> Optional[Dict]:
        """
        Strategy 3: Fuzzy string matching using Levenshtein distance.
        
        Returns:
            Match dict with score 0.7-0.9 or None
        """
        # Get candidate books (limit to reasonable set)
        # Use first few words of title for initial filtering
        title_words = self.tokenize(title)[:3]
        
        if not title_words:
            return None
        
        # Build query to get candidates
        query = "SELECT id, title, author, path FROM books WHERE "
        conditions = []
        params = []
        
        for word in title_words:
            conditions.append("title LIKE ?")
            params.append(f"%{word}%")
        
        query += " OR ".join(conditions)
        query += " LIMIT 100"  # Limit candidates for performance
        
        db_cursor.execute(query, params)
        candidates = db_cursor.fetchall()
        
        best_match = None
        best_score = 0.0
        
        for row in candidates:
            db_id, db_title, db_author, db_path = row
            
            # Calculate title similarity
            title_score = fuzz.ratio(title.lower(), db_title.lower()) / 100.0
            
            # Calculate author similarity if provided
            author_score = 1.0
            if author and db_author:
                author_score = fuzz.ratio(author.lower(), db_author.lower()) / 100.0
            
            # Combined score (70% title, 30% author)
            combined_score = (title_score * 0.7) + (author_score * 0.3)
            
            # Must meet minimum thresholds
            if title_score >= 0.85 and (not author or author_score >= 0.80):
                if combined_score > best_score:
                    best_score = combined_score
                    best_match = {
                        'id': db_id,
                        'title': db_title,
                        'author': db_author,
                        'path': db_path,
                        'score': combined_score,
                        'strategy': 'fuzzy'
                    }
        
        if best_match and self.debug:
            logger.debug(f"Fuzzy match found: {best_match['title']} (score: {best_score:.2f})")
        
        return best_match
    
    def match_token_based(self, title: str, author: Optional[str], db_cursor: sqlite3.Cursor) -> Optional[Dict]:
        """
        Strategy 4: Token-based SQL LIKE matching with relaxed requirements.
        
        Returns:
            Match dict with score 0.6-0.8 or None
        """
        # Handle subtitles: split on colon and prioritize main title
        # E.g., "Real Analysis: Modern Techniques" -> use "Real Analysis" primarily
        main_title = title.split(':')[0].strip() if ':' in title else title
        
        title_tokens = self.tokenize(main_title)  # Use main title for matching
        author_tokens = self.tokenize(author) if author else []
        
        if not title_tokens:
            return None
        
        # Build SQL query - require most tokens but allow 1-2 missing for long titles
        required_title_tokens = title_tokens
        if len(title_tokens) > 3:
            # For long titles, allow 1 missing token
            required_title_tokens = title_tokens[:-1]
        
        params = []
        sql = "SELECT id, title, author, path FROM books WHERE 1=1"
        
        # Title conditions
        if required_title_tokens:
            title_conditions = []
            for token in required_title_tokens:
                title_conditions.append("title LIKE ?")
                params.append(f"%{token}%")
            sql += " AND (" + " AND ".join(title_conditions) + ")"
        
        # Author conditions - RELAXED: only require last name (most significant token)
        if author_tokens:
            # Use the last token (typically the surname) as the primary match
            # This handles cases like "Paul R. Halmos" matching "Halmos"
            last_name = author_tokens[-1] if author_tokens else None
            
            if last_name:
                sql += " AND author LIKE ?"
                params.append(f"%{last_name}%")
        
        sql += " LIMIT 5"  # Get top 5 candidates
        
        db_cursor.execute(sql, params)
        rows = db_cursor.fetchall()
        
        if not rows:
            return None
        
        # If we have multiple candidates, use fuzzy matching to pick the best
        best_match = None
        best_author_score = 0.0
        
        for row in rows:
            if author and row[2]:  # If author was provided, score the match
                author_score = fuzz.ratio(author.lower(), row[2].lower()) / 100.0
                if author_score > best_author_score:
                    best_author_score = author_score
                    best_match = row
            else:
                # No author provided or no author in DB, take first match
                best_match = row
                break
        
        if best_match:
            # Calculate score based on token coverage
            matched_tokens = len(required_title_tokens)
            total_tokens = len(title_tokens)
            score = 0.6 + (0.2 * (matched_tokens / total_tokens))
            
            if self.debug:
                logger.debug(f"Token-based match found: {best_match[1]} (score: {score:.2f})")
            
            return {
                'id': best_match[0],
                'title': best_match[1],
                'author': best_match[2],
                'path': best_match[3],
                'score': score,
                'strategy': 'token'
            }
        
        return None
    
    def match_book(self, title: str, author: Optional[str] = None) -> Dict:
        """
        Find the best match for a book using cascading strategies.
        
        Args:
            title: Book title
            author: Book author (optional)
            
        Returns:
            {
                'found': bool,
                'match': {'id', 'title', 'author', 'path', 'score'} or None,
                'strategy': 'exact' | 'normalized' | 'fuzzy' | 'token' | None
            }
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        strategies = [
            self.match_exact,
            self.match_normalized,
            self.match_fuzzy,
            self.match_token_based
        ]
        
        for strategy in strategies:
            match = strategy(title, author, cursor)
            if match and match['score'] >= self.threshold:
                conn.close()
                return {
                    'found': True,
                    'match': match,
                    'strategy': match['strategy']
                }
        
        conn.close()
        
        if self.debug:
            logger.debug(f"No match found for: {title} by {author}")
        
        return {
            'found': False,
            'match': None,
            'strategy': None
        }
    
    def batch_match(self, books: List[Dict[str, str]]) -> List[Dict]:
        """
        Match multiple books efficiently.
        
        Args:
            books: List of {'title': str, 'author': str} dicts
            
        Returns:
            List of match results
        """
        results = []
        
        for book in books:
            title = book.get('title', '')
            author = book.get('author', '')
            result = self.match_book(title, author)
            results.append(result)
        
        return results
