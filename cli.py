import argparse
import sys
import time
from core.database import db
from core.config import PROJECT_ROOT, UNSORTED_DIR
from services.search import search_service
from services.library import library_service
from services.ingestor import ingestor_service
from services.indexer import indexer_service

def handle_init(args):
    print("Initializing Database Schema...")
    db.initialize_schema(force_fts_rebuild=args.force_fts)
    print("Done.")

def handle_index(args):
    print(f"Scanning Library (force={args.force})...")
    indexer_service.scan_library(force=args.force)

def handle_deep_index(args):
    success, message = indexer_service.deep_index_book(args.book_id)
    if success:
        print(f"[OK] {message}")
    else:
        print(f"[ERR] {message}")

def handle_search(args):
    query = " ".join(args.query)
    print(f"Searching for: '{query}'...")
    results = search_service.search(
        query, 
        limit=args.limit, 
        use_vector=not args.no_vec, 
        use_fts=not args.no_fts,
        use_rerank=args.rank
    )
    
    for res in results['results']:
        label = f"[{res.get('found_by', '???').upper()}]"
        print(f"{label} {res['title']} ({res['author']})")
        if res.get('ai_reason'):
            print(f"  AI Reason: {res['ai_reason']}")
        print(f"  Path: {res['path']}")
        print("-" * 20)

def handle_sanity(args):
    print(f"Running Sanity Check (fix={args.fix})...")
    results = library_service.check_sanity(fix=args.fix)
    
    if not results['broken'] and not results['duplicates']:
        print("Library is healthy.")
        return

    if results['broken']:
        print(f"\n[BROKEN] Found {len(results['broken'])} entries with missing files:")
        for b in results['broken']:
            print(f"  - [{b['id']}] {b['path']} ({b['title']})")
    
    if results['duplicates']:
        print(f"\n[DUPLICATES] Found {len(results['duplicates'])} duplicate hash sets:")
        for d in results['duplicates']:
            print(f"  - Hash: {d['hash'][:10]}...")
            print(f"    KEEP: [{d['best']['id']}] {d['best']['path']}")
            for r in d['redundant']:
                print(f"    REDUNDANT: [{r['id']}] {r['path']}")

def handle_ingest(args):
    print(f"Scanning {UNSORTED_DIR}...")
    files = list(UNSORTED_DIR.glob("*.pdf")) + list(UNSORTED_DIR.glob("*.djvu"))
    
    for f in files:
        result = ingestor_service.process_file(f, execute=args.execute)
        if result['status'] == 'success':
            print(f"  [OK] Ingested to {result['path']}")
        elif result['status'] == 'plan':
            print(f"  [PLAN] Would move to {result['target']}")
        elif result['status'] == 'duplicate':
            print(f"  [DUP] {f.name} is a duplicate of {result['match']['path']}")
        else:
            print(f"  [ERR] {f.name}: {result.get('message')}")

def handle_clear_index(args):
    success, message = library_service.clear_indexes(args.book_ids)
    if success:
        print(f"[OK] {message}")
    else:
        print(f"[ERR] {message}")

def handle_audit_index(args):
    print("Auditing index quality...")
    results = indexer_service.audit_indexes()
    if not results:
        print("No issues found.")
        return
        
    print(f"{'ID':<5} | {'Title':<40} | {'Len':<6} | {'Dens.':<5} | {'Struct':<5} | {'Flag'}")
    print("-" * 80)
    for r in results:
        title = (r['title'][:37] + '...') if len(r['title']) > 37 else r['title']
        print(f"{r['id']:<5} | {title:<40} | {r['len']:<6} | {r['density']:.2f}  | {r['struct']:.2f}  | {','.join(r['flags'])}")
    print("-" * 80)
    print(f"Total: {len(results)} potentially bad indexes.")

def handle_audit_toc(args):
    if args.fix:
        print("Starting Table of Contents repair...")
        repaired = indexer_service.repair_missing_tocs()
        print(f"Repair complete. Successfully extracted bookmarks for {repaired} books.")
        return

    print("Auditing Table of Contents quality...")
    results = indexer_service.audit_tocs()
    if not results:
        print("No issues found.")
        return
        
    print(f"{'ID':<5} | {'Title':<40} | {'Entries':<7} | {'Depth':<5} | {'Coverage':<10} | {'Flag'}")
    print("-" * 90)
    for r in results:
        title = (r['title'][:37] + '...') if len(r['title']) > 37 else r['title']
        print(f"{r['id']:<5} | {title:<40} | {r['count']:<7} | {r['depth']:<5} | {r['coverage']:<10} | {','.join(r['flags'])}")
    print("-" * 90)
    print(f"Total: {len(results)} books with suboptimal TOCs.")

from services.metadata import metadata_service

def handle_bib(args):
    query = " ".join(args.query)
    print(f"Generating BibTeX for: '{query}'...")
    results = search_service.search(query, limit=5, use_vector=False) # Simple search
    
    if not results['results']:
        print("No matches found.")
        return
        
    for r in results['results']:
        bib = metadata_service.generate_bibtex(
            r['title'], r['author'], Path(r['path']).name, 
            year=r.get('year'), publisher=r.get('publisher')
        )
        print(bib)
        print("-" * 40)

from services.bibliography import bibliography_service

def handle_bib_scan(args):
    print(f"Scanning bibliography for Book ID {args.book_id}...")
    result = bibliography_service.scan_book(args.book_id)
    if not result['success']:
        print(f"[ERR] {result['error']}")
        return
        
    print(f"Found {result['stats']['total']} citations ({result['stats']['owned']} owned).")
    for c in result['citations']:
        status = "[OWNED]" if c['status'] == 'owned' else "[MISSING]"
        print(f"{status} {c['title']} ({c['author']})")

def main():
    parser = argparse.ArgumentParser(description="MathStudio CLI")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Init
    p_init = subparsers.add_parser("init", help="Initialize database schema")
    p_init.add_argument("--force-fts", action="store_true", help="Force FTS rebuild")

    # Search
    p_search = subparsers.add_parser("search", help="Search the library")
    p_search.add_argument("query", nargs="+")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--no-vec", action="store_true")
    p_search.add_argument("--no-fts", action="store_true")
    p_search.add_argument("--rank", action="store_true")

    # Ingest
    p_ingest = subparsers.add_parser("ingest", help="Ingest new books from Unsorted")
    p_ingest.add_argument("--execute", action="store_true", help="Perform move and DB update")
    
    # Index/Scan
    p_index = subparsers.add_parser("index", help="Scan library and update FTS")
    p_index.add_argument("--force", action="store_true", help="Force re-extraction of text")

    # Deep Index
    p_deep = subparsers.add_parser("deep-index", help="Perform page-level indexing for a book")
    p_deep.add_argument("book_id", type=int)

    # Clear Index
    p_clear = subparsers.add_parser("clear-index", help="Clear index_text for specific books")
    p_clear.add_argument("book_ids", type=int, nargs="+")

    # Audit Index
    p_audit = subparsers.add_parser("audit-index", help="Scan for low-quality indexes")

    # Audit TOC
    p_audit_toc = subparsers.add_parser("audit-toc", help="Scan for low-quality Tables of Contents")
    p_audit_toc.add_argument("--fix", action="store_true", help="Try to repair missing TOCs from PDF bookmarks")

    # Bib
    p_bib = subparsers.add_parser("bib", help="Generate BibTeX for a book")
    p_bib.add_argument("query", nargs="+")

    # Bib Scan
    p_bib_scan = subparsers.add_parser("bib-scan", help="Extract and cross-check bibliography from a book")
    p_bib_scan.add_argument("book_id", type=int)

    # Sanity
    p_sanity = subparsers.add_parser("sanity", help="Run database sanity check")
    p_sanity.add_argument("--fix", action="store_true", help="Fix broken entries")

    args = parser.parse_args()

    if args.command == "init":
        handle_init(args)
    elif args.command == "search":
        handle_search(args)
    elif args.command == "ingest":
        handle_ingest(args)
    elif args.command == "index":
        handle_index(args)
    elif args.command == "deep-index":
        handle_deep_index(args)
    elif args.command == "clear-index":
        handle_clear_index(args)
    elif args.command == "audit-index":
        handle_audit_index(args)
    elif args.command == "audit-toc":
        handle_audit_toc(args)
    elif args.command == "bib":
        handle_bib(args)
    elif args.command == "bib-scan":
        handle_bib_scan(args)
    elif args.command == "sanity":
        handle_sanity(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
