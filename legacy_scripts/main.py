import argparse
import sys
from indexer import setup_database, scan_library
from search import search_books
from bibgen import find_and_bib

def handle_index(args):
    conn = setup_database()
    scan_library(conn, force=args.force)
    conn.close()

def handle_search(args):
    query = " ".join(args.query)
    # Use search_hybrid as default
    from search import search_hybrid
    print(f"Performing Hybrid Search for: '{query}'...")
    results = search_hybrid(query, args.limit)
    
    if not results:
         print(f"No results found for '{query}'")
         return

    print(f"Found {len(results)} matches:\n")
    for res in results:
        # found_by can be 'vector', 'fts', or 'both'
        label = f"[{res['found_by'].upper()}]"
        # Color coding if supported by terminal
        if res['found_by'] == 'both':
            label = f"\033[92m{label}\033[0m" # Green
        elif res['found_by'] == 'vector':
            label = f"\033[94m{label}\033[0m" # Blue
        
        print(f"{label} {res['title']}")
        print(f"Author: {res['author']}")
        print(f"Path:   ../{res['path']}")
        if 'snippet' in res and res['snippet']:
            clean_snippet = res['snippet'].replace("<b>", "\033[1m").replace("</b>", "\033[0m")
            print(f"Snippet: {clean_snippet}")
        print("-" * 40)

def handle_bib(args):
    query = " ".join(args.query)
    bibs = find_and_bib(query)
    
    if not bibs:
        print(f"No books found matching '{query}'")
    else:
        print(f"Found {len(bibs)} candidates. Here are the BibTeX entries:\n")
        for bib in bibs:
            print(bib)
            print("")

def main():
    parser = argparse.ArgumentParser(description="Math Studio Library Manager")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Index command
    parser_index = subparsers.add_parser("index", help="Scan and index the library")
    parser_index.add_argument("--force", action="store_true", help="Force re-indexing of all files")
    
    # Search command
    parser_search = subparsers.add_parser("search", help="Search for books")
    parser_search.add_argument("query", nargs="+", help="Search keywords")
    parser_search.add_argument("--limit", type=int, default=20, help="Max results")
    parser_search.add_argument("--content", action="store_true", help="Search full content")
    
    # Bib command
    parser_bib = subparsers.add_parser("bib", help="Generate BibTeX entries")
    parser_bib.add_argument("query", nargs="+", help="Search keywords for the book")
    
    args = parser.parse_args()
    
    if args.command == "index":
        handle_index(args)
    elif args.command == "search":
        handle_search(args)
    elif args.command == "bib":
        handle_bib(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
