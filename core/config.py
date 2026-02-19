import os
from pathlib import Path

# Project Root (mathstudio/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Library Root (math/)
LIBRARY_ROOT = PROJECT_ROOT.parent

# Database
DB_FILE = PROJECT_ROOT / "library.db"

# External Paths
OBSIDIAN_INBOX = Path("/srv/data/math/obsidian/mathematik_obsidian/00_Inbox")

# Project Subdirectories
CONVERTED_NOTES_DIR = PROJECT_ROOT / "converted_notes"
NOTES_OUTPUT_DIR = PROJECT_ROOT / "notes_output"
STATIC_DIR = PROJECT_ROOT / "static"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
TEMP_UPLOADS_DIR = PROJECT_ROOT / "temp_uploads"
BIB_EXTRACTS_DIR = PROJECT_ROOT / "bib_extracts"
DUPLICATES_DIR = LIBRARY_ROOT / "_Admin" / "Duplicates"
UNSORTED_DIR = LIBRARY_ROOT / "99_General_and_Diverse" / "Unsorted"

IGNORED_FOLDERS = {
    'mathstudio', '_Admin', 'gemini', '.gemini', '.git', '.venv', 
    'notes_output', 'archive', 'lost+found', '__pycache__'
}

# Ensure directories exist
for d in [CONVERTED_NOTES_DIR, NOTES_OUTPUT_DIR, TEMP_UPLOADS_DIR, BIB_EXTRACTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# AI Settings
GEMINI_MODEL = "gemini-2.5-flash-lite-preview-09-2025"
EMBEDDING_MODEL = "models/gemini-embedding-001"

def get_api_key():
    try:
        import json
        with open(PROJECT_ROOT / "credentials.json", "r") as f:
            return json.load(f).get("GEMINI_API_KEY")
    except Exception:
        return os.environ.get("GEMINI_API_KEY")
