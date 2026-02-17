import argparse
import sys
import time
from core.database import db
from core.config import PROJECT_ROOT, UNSORTED_DIR
from services.search import search_service
from services.library import library_service
from services.ingestor import ingestor_service

def handle_init(args):
    print("Initializing Database Schema...")
    db.initialize_schema(force_fts_rebuild=args.force_fts)
    print("Done.")

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
        print(f"Found {len(results['broken'])} broken entries:")
        for b in results['broken']:
            print(f"  - [{b['id']}] {b['path']}")
    
    if results['duplicates']:
        print(f"Found {len(results['duplicates'])} duplicate hashes.")

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
    elif args.command == "sanity":
        handle_sanity(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
