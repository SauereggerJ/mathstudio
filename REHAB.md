# REHAB.md - MathStudio Master Documentation & Technical Manual

**Last Update:** 2026-02-17 (Architectural Refactoring)
**Status:** ALL SYSTEMS OPERATIONAL | Modular Service Structure | 100% Test Pass Rate

---

## 1. Project Identity & Core Mission
MathStudio is a specialized research environment for mathematical and physical sciences. It combines a massive digital library with LLM-powered reasoning and automated document processing.

**Key Objectives:**
*   **Semantic Retrieval**: Finding concepts across thousands of volumes.
*   **Knowledge Synthesis**: Transforming raw pages into structured LaTeX/Markdown.
*   **Modular Architecture**: Separating core logic from interface layers for stability and scale.

---

## 2. Infrastructure & Architecture

### A. Core Foundation (`core/`)
*   **`database.py`**: Centralized SQLite management with WAL mode and thread-local connections.
*   **`ai.py`**: Unified Gemini API client with retry logic and JSON orchestration.
*   **`config.py`**: Single source of truth for all system paths and constants.
*   **`utils.py`**: Shared helper functions (e.g., PDF slicing, page range parsing).

### B. Service Layer (`services/`)
*   **`search.py`**: Hybrid retrieval pipeline (Vector + FTS5 + AI Reranking).
*   **`library.py`**: Administrative logic (Sanity, Metadata, Deletion).
*   **`ingestor.py`**: Automated ingestion and classification of new volumes.
*   **`indexer.py`**: Full-text and page-level indexing orchestration.
*   **`note.py`**: Hand-written note transcription and PDF-to-Note conversion.
*   **`metadata.py`**: External API integrations (ArXiv, CrossRef, etc.).

### C. Interface Layer
*   **Web Interface (`app.py` / `api_v1.py`)**: Flask-based REST API and UI.
*   **Unified CLI (`cli.py`)**: Single entry point for all administrative tasks.

---

## 3. Operations & Maintenance

### A. The Unified CLI (`cli.py`)
Use the CLI for library management:
*   `python3 cli.py ingest`: Process new files from `Unsorted`.
*   `python3 cli.py sanity`: Check for broken links and duplicates.
*   `python3 cli.py index`: Scan and update the search index.
*   `python3 cli.py search "query"`: Test retrieval performance.

### B. Smart Search Pipeline
Retrieval follows a 4-stage process:
1.  **Semantic (Vector)**: Cosine similarity on embeddings (768d).
2.  **Keyword (FTS5)**: SQLite Full-Text Search on metadata and content.
3.  **Index Lookup**: Physical back-of-book register mapping for mathematical terms.
4.  **AI Reranking**: LLM-driven verification of top candidates.

---

## 4. Testing & Quality Assurance
Run tests frequently: `export PYTHONPATH=. && .venv/bin/pytest`.
*   `tests/unit/core/`: Database and config tests.
*   `tests/unit/services/`: Service logic tests.
*   `tests/api/`: REST endpoint validation.

---

## 5. The REHAB Protocol (Development Rules)
1.  **Service First**: Add logic to services, not to API endpoints or standalone scripts.
2.  **Explicit Context**: Use `core.config` for all path references.
3.  **Strict Typing**: Maintain clear dictionary structures for data exchange.
4.  **Safety First**: Always perform `sanity` checks before and after major library operations.

> [!CAUTION]
> **SOURCE OF TRUTH**: The `core/database.py` and `services/` layer are the sources of truth. Never bypass them with direct `sqlite3` calls in new modules.
