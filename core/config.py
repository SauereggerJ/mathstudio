import os
from pathlib import Path

# Project Root (mathstudio/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Library Root (math/)
LIBRARY_ROOT = PROJECT_ROOT.parent

# Database
DB_FILE = PROJECT_ROOT / "library.db"

# External Paths
WORKSPACE_DIR = Path("/srv/data/math/workspace")

# Project Subdirectories
CONVERTED_NOTES_DIR = PROJECT_ROOT / "converted_notes"
NOTES_OUTPUT_DIR = PROJECT_ROOT / "notes_output"
STATIC_DIR = PROJECT_ROOT / "static"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
TEMP_UPLOADS_DIR = PROJECT_ROOT / "temp_uploads"
BIB_EXTRACTS_DIR = PROJECT_ROOT / "bib_extracts"
COMPILED_NOTES_DIR = PROJECT_ROOT / "compiled_notes"
EXPORTS_DIR = PROJECT_ROOT / "exports"
DUPLICATES_DIR = LIBRARY_ROOT / "_Admin" / "Duplicates"
UNSORTED_DIR = LIBRARY_ROOT / "99_General_and_Diverse" / "Unsorted"

# Knowledge Vault
KNOWLEDGE_VAULT_ROOT = PROJECT_ROOT / "knowledge_vault"
KNOWLEDGE_GENERATED_DIR = KNOWLEDGE_VAULT_ROOT / "Generated"
KNOWLEDGE_DRAFTS_DIR = KNOWLEDGE_VAULT_ROOT / "Drafts"
KNOWLEDGE_TEMPLATES_DIR = PROJECT_ROOT / "templates" / "knowledge"

IGNORED_FOLDERS = {
    'mathstudio', '_Admin', 'gemini', '.gemini', '.git', '.venv', 
    'notes_output', 'archive', 'lost+found', '__pycache__', 'compiled_notes', 'exports'
}

# Ensure directories exist
for d in [CONVERTED_NOTES_DIR, NOTES_OUTPUT_DIR, TEMP_UPLOADS_DIR, BIB_EXTRACTS_DIR,
          COMPILED_NOTES_DIR, EXPORTS_DIR,
          KNOWLEDGE_GENERATED_DIR, KNOWLEDGE_DRAFTS_DIR,
          KNOWLEDGE_GENERATED_DIR / "Definitions",
          KNOWLEDGE_GENERATED_DIR / "Theorems",
          KNOWLEDGE_GENERATED_DIR / "Examples",
          KNOWLEDGE_GENERATED_DIR / "Notations",
          KNOWLEDGE_TEMPLATES_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# AI Settings
GEMINI_MODEL = "gemini-2.5-flash-lite-preview-09-2025"
EMBEDDING_MODEL = "models/gemini-embedding-001"

# Search Infrastructure
ELASTICSEARCH_URL = os.environ.get("ELASTICSEARCH_URL", "http://localhost:9200")
MWS_URL = os.environ.get("MWS_URL", "http://localhost:8080")

def get_api_key():
    try:
        import json
        with open(PROJECT_ROOT / "credentials.json", "r") as f:
            return json.load(f).get("GEMINI_API_KEY")
    except Exception:
        return os.environ.get("GEMINI_API_KEY")
