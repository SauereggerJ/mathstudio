import os
import sys
import json
from pathlib import Path
from elasticsearch import Elasticsearch, helpers

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import db
from core.config import CONVERTED_NOTES_DIR
from core.search_engine import es_client

def index_latex_pages(book_id=None):
    """
    Reads .tex files from CONVERTED_NOTES_DIR/book_id/page_N.tex
    and pushes them to mathstudio_pages ES index.
    """
    if book_id:
        target_ids = [str(book_id)]
    else:
        # Index all available directories in converted_notes
        target_ids = [d for d in os.listdir(CONVERTED_NOTES_DIR) if d.isdigit()]

    for bid in target_ids:
        print(f"Indexing LaTeX for Book {bid}...")
        book_dir = CONVERTED_NOTES_DIR / bid
        if not book_dir.exists():
            print(f"  Directory not found: {book_dir}")
            continue

        actions = []
        # Find all .tex files
        for tex_file in book_dir.glob("page_*.tex"):
            try:
                page_num = int(tex_file.stem.split('_')[1])
                content = tex_file.read_text(encoding='utf-8')
                
                # Strip excessive LaTeX boilerplate if needed, but the search analyzer handles it usually
                actions.append({
                    "_index": "mathstudio_pages",
                    "_id": f"book_{bid}_p{page_num}",
                    "_source": {
                        "book_id": int(bid),
                        "page_number": page_num,
                        "content": content
                    }
                })
            except (IndexError, ValueError):
                continue

        if actions:
            print(f"  Pushing {len(actions)} pages to ES...")
            helpers.bulk(es_client, actions)
            print(f"  Success.")
        else:
            print(f"  No pages found for Book {bid}.")

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    index_latex_pages(target)
