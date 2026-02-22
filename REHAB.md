# REHAB.md - MathStudio Master Documentation & Technical Manual

**Last Update:** 2026-02-19 (Vision-Reflection Pipeline Integration)
**Status:** ALL SYSTEMS OPERATIONAL | 4GB RAM Dedicated | Vision-First Architecture

---

## 1. Project Identity & Core Mission
MathStudio is a specialized research environment for mathematical and physical sciences. It transforms a static PDF library into a networked **Knowledge Graph** using AI-powered vision and deterministic metadata verification.

---

## 2. Infrastructure & Architecture

### A. Core Foundation (`core/`)
*   **`database.py`**: SQLite management (WAL mode, STRICT tables, JSONB).
*   **`ai.py`**: Gemini 2.0 Flash integration with File API support.
*   **`utils.py`**: **Zero-Duplication PDF Handler**. Atomic slicing and multilingual heuristics.
*   **`config.py`**: System-wide path and model constants.

### B. Service Layer (`services/`)
*   **`universal_processor.py`**: **The 7-Phase Pipeline**. Orchestrates Vision-First metadata extraction, chunked bibliography scanning, and Reflection-based conflict resolution.
*   **`search.py`**: Hybrid retrieval (Vector + FTS5 + AI Reranking).
*   **`library.py`**: Maintenance logic (Sanity, Duplicate SHA-256 detection).
*   **`ingestor.py`**: Bridge between `/Unsorted` and the Universal Pipeline.
*   **`zbmath.py`**: Resolver for Crossref (Polite Pool) and EMS zbMATH OAI-PMH.

### C. Interface Layer
*   **Web UI (`app.py` / `api_v1.py`)**: Unified metadata refresh and bibliography discovery.

---

## 3. Development Workflow (Server-Local)

### A. Environment
*   **Development occurs directly on the server.**
*   **Deployment is managed via Docker containers.** 
*   Use `docker-compose up -d --build` to apply changes to the production environment.

### B. Commits & Versioning
*   **Mandatory Commits**: Perform a Git commit after every medium-to-large functional change.
*   **Commit Quality**: Messages must concisely describe *what* was changed and *why* (e.g., "Fix OOM via sequential I/O slicing").
*   **Agentic Extraction**: The AI agent is authorized to perform "Manual Agentic Extraction" for complex bibliographies (e.g., Folland, Yang-Mills) by directly reading PDF pages and injecting structured JSON into the DB, bypassing rigid pipeline heuristics when necessary.

### C. Masterpiece Backup
*   The `TECHNICAL_MANUAL.md` must be kept in sync with architecture changes and pushed to GitHub as the primary technical reference.

---

## 5. Git Maintenance & Bloat Prevention (Scrubbing)
To maintain a lightweight GitHub backup, the repository history must be strictly source-only.

### A. The "Disaster Recovery" Protocol
If large binaries (databases, PDFs) accidentally enter the Git history, follow these steps to scrub them from **all past commits**:

1.  **Stop Tracking**: `git rm --cached <file>` (keeps it on disk, removes from Git index).
2.  **Scrub History**: 
    ```bash
    git filter-branch --force --index-filter \
      "git rm --cached --ignore-unmatch <file_pattern>" \
      --prune-empty --tag-name-filter cat -- --all
    ```
3.  **Physical Cleanup**: 
    ```bash
    rm -rf .git/refs/original/ && git reflog expire --expire=now --all && git gc --prune=now --aggressive
    ```
4.  **Mirror Reset**: `git push --force origin main`

### B. Prohibited File Patterns
The following MUST NEVER be committed:
*   `*.db`, `*.arxiv`, `*.bak` (Database and archives)
*   `static/cache/`, `static/thumbnails/` (Generated assets)
*   `bib_extracts/`, `converted_notes/` (Research I/O)
*   `venv/`, `.venv/` (Local environments)

---
*Status: Verified History Clean | Last Scrub: 2026-02-22*
