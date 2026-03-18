#!/usr/bin/env python3
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import db
from core.config import LIBRARY_ROOT

def find_ghosts():
    with db.get_connection() as conn:
        books = conn.execute("SELECT id, title, path FROM books").fetchall()
    
    ghosts = []
    for book in books:
        abs_path = LIBRARY_ROOT / book['path']
        if not abs_path.exists():
            ghosts.append((book['id'], book['title'], book['path']))
            
    if not ghosts:
        print("No ghost entries found! All DB entries have physical files.")
    else:
        print(f"Found {len(ghosts)} ghost entries:")
        for gid, gtitle, gpath in ghosts:
            print(f"ID: {gid} | Title: {gtitle} | Path: {gpath}")
            
if __name__ == "__main__":
    find_ghosts()
