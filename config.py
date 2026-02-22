import sys
from pathlib import Path

# Path setup
current_dir = Path(__file__).resolve().parent
# Since we consolidated to root, project_dir IS current_dir
project_dir = current_dir

if str(project_dir) not in sys.path:
    sys.path.append(str(project_dir))

# Constants
DB_FILE = project_dir / "library.db"
LIBRARY_ROOT = project_dir.parent
OBSIDIAN_INBOX = "/srv/data/math/obsidian/mathematik_obsidian/00_Inbox"
NOTES_OUTPUT_DIR = project_dir / "notes_output"
CONVERTED_NOTES_DIR = project_dir / "converted_notes"
# For backward compatibility with some scripts that might expect parent_dir
parent_dir = project_dir
