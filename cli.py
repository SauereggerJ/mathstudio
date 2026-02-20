import click
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.ingestor import ingestor_service
from services.indexer import indexer_service
from services.library import library_service
from services.search import search_service

@click.group()
def cli():
    """MathStudio Administrative Command Line Interface."""
    pass

@cli.command()
@click.option('--dry-run', is_flag=True, default=True, help='Preview changes without moving files.')
def ingest(dry_run):
    """Processes new files from the Unsorted directory."""
    click.echo(f"Starting ingestion (Dry run: {dry_run})...")
    from core.config import UNSORTED_DIR
    files = list(UNSORTED_DIR.glob("*.pdf")) + list(UNSORTED_DIR.glob("*.djvu"))
    for f in files:
        res = ingestor_service.process_file(f, execute=not dry_run)
        click.echo(f"- {f.name}: {res['status']}")

@cli.command()
@click.option('--fix', is_flag=True, default=False, help='Fix broken paths and remove duplicates.')
def sanity(fix):
    """Checks library integrity and file existence."""
    results = library_service.check_sanity(fix=fix)
    click.echo(f"Broken links found: {len(results['broken'])}")
    click.echo(f"Duplicates found: {len(results['duplicates'])}")

@cli.command()
@click.option('--force', is_flag=True, default=False, help='Force full re-index.')
def index(force):
    """Updates the FTS5 search index."""
    indexer_service.scan_library(force=force)
    click.echo("Indexing complete.")

@cli.command()
@click.option('--limit', default=None, type=int, help='Maximum number of books to process.')
def sweep(limit):
    """Triggers a mass metadata refresh for the entire library (Grand Sweep)."""
    from core.batch_worker import run_grand_sweep
    run_grand_sweep(limit=limit)

if __name__ == '__main__':
    cli()
