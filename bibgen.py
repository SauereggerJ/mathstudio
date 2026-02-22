import sqlite3
import argparse
import sys
from pathlib import Path

# Configuration
DB_FILE = "library.db"

def generate_bibtex_key(author, title):
    """Generates a simple BibTeX citation key."""
    if not author:
        author = "Unknown"
    if not title:
        title = "Unknown"
        
    # Take first word of author (surname often)
    # Remove special chars
    clean_author = "".join([c for c in author if c.isalnum() or c==' ']).split()[0]
    
    # Take first significant word of title
    clean_title = "".join([c for c in title if c.isalnum() or c==' '])
    title_words = [w for w in clean_title.split() if len(w) > 3]
    first_title_word = title_words[0] if title_words else "Book"
    
    return f"{clean_author}{first_title_word}"

def generate_bibtex(book_tuple):
    """
    Generates a BibTeX entry string.
    book_tuple: (title, author, path, filename)
    """
    title, author, path, filename = book_tuple
    
    key = generate_bibtex_key(author, title)
    
    # Basic cleanup
    if not author: author = "Unknown"
    
    bib = f"""@book{{{key},
  author    = {{{author}}},
  title     = {{{title}}},
  year      = {{20XX}},
  publisher = {{Unknown}},
  note      = {{File: {filename}}}
}}"""
    return bib

def find_and_bib(query):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Search logic similar to search.py but we want to select specific item
    keywords = query.split()
    sql_query = "SELECT title, author, path, filename FROM books WHERE 1=1"
    params = []
    
    for word in keywords:
        sql_query += " AND (title LIKE ? OR author LIKE ? OR filename LIKE ?)"
        like_pattern = f"%{word}%"
        params.extend([like_pattern, like_pattern, like_pattern])
        
    sql_query += " LIMIT 5" # Only parse top few
    
    results = cursor.execute(sql_query, params).fetchall()
    conn.close()
    
    if not results:
        return []
        
    return [generate_bibtex(r) for r in results]

def main():
    parser = argparse.ArgumentParser(description="Generate BibTeX for library books")
    parser.add_argument("query", nargs="+", help="Search keywords for the book")
    
    args = parser.parse_args()
    query = " ".join(args.query)
    
    bibs = find_and_bib(query)
    
    if not bibs:
        print(f"No books found matching '{query}'")
    else:
        print(f"Found {len(bibs)} candidates. Here are the BibTeX entries:\n")
        for bib in bibs:
            print(bib)
            print("")

if __name__ == "__main__":
    main()
