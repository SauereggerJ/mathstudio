# REHAB.md - MathStudio Master Documentation & Technical Manual

**Last Update:** 2026-02-16 (Testing & Quality Assurance)
**Status:** ALL SYSTEMS OPERATIONAL | Clean V2 Structure | 100% Test Pass Rate (41/41)

---

## 1. Project Identity & Core Mission
MathStudio is a specialized research environment for mathematical and physical sciences. It combines a massive digital library (2.6 GB database, 10,000+ volumes) with LLM-powered reasoning and automated document processing.

**Key Objectives:**
*   **Semantic Retrieval**: Finding not just titles, but concepts across thousands of PDFs and DjVu files.
*   **Knowledge Synthesis**: Automating the conversion of raw book pages and handwritten notes into structured LaTeX/Markdown.
*   **Deep Integration**: Bridging the gap between a static library and an interactive LLM via the Model Context Protocol (MCP).

---

## 2. Infrastructure & Architecture

### A. Environment
*   **Host Server:** `192.168.178.2` (Home Server `jure`)
*   **Web Interface:** `http://192.168.178.2:5002`
*   **Local Project Root:** `/srv/data/math/New_Research_Library/mathstudio`
*   **Deployment Container:** `mathstudio` (Dockerized Python 3.11-slim)
    *   *Includes specialized tools:* `djvulibre-bin`, `netpbm`, `texlive-full` (subset).

### B. Deployment & Remote Control
The system uses a "Develop Locally, Deploy Remotely" workflow.
*   **`remote_control.py`**: Handles `rsync` synchronization and Docker service management.
*   **`deploy_and_debug.py`**: The interactive master CLI. Use it for:
    *   `--deploy`: Full rebuild of the container.
    *   `--quick`: Fast sync of Python files and worker restart.
    *   `--logs`: Live streaming of background processes.
    *   `--health`: Diagnostic check of DB and connectivity.

---

## 3. The Smart Search Pipeline (`search.py`)
MathStudio uses a state-of-the-art 4-stage retrieval system:
1.  **Semantic Retrieval**: Vector search on book embeddings.
2.  **Hybrid Retrieval**:
    *   **Semantic (Vector)**: Cosine similarity on `books.embedding` (768 dimensions, `models/gemini-embedding-001`).
    *   **Keyword (FTS5)**: SQLite Full-Text Search on `title`, `author`, and `index_content`.
3.  **Weighted Fusion**: Combines scores with a bias towards Semantic (0.6) and FTS (0.4).
4.  **AI Reranking**: The top 10 results are analyzed by Gemini to provide a specific `ai_reason` why they match the intent.

---

## 4. Ingestion & Document Processing

### A. Hybrid Book Ingestor (`book_ingestor.py`)
The "Gatekeeper" of the library. Processes new files from `99_General_and_Diverse/Unsorted`.
*   **Auto-Routing**: Classifies books by MSC (Mathematics Subject Classification) and moves them to the correct folder (e.g., `04_Algebra`).
*   **Metadata Enrichment**: Extracts ToC, page counts, summaries, and difficulty levels.
*   **Deduplication**: SHA256 hash checks + semantic title/author matching.

### B. MathBot / Notes Processor (`process_notes.py`)
The bridge between paper and digital.
*   **Flow**: Google Drive (Input) → OCR (Gemini Vision) → LaTeX/PDF → Obsidian (Output).
*   **Features**: Automatic LaTeX preamble wrapping, standard math notation, and "Recommended Reading" generation.

### C. Page-to-Note Converter (`converter.py`)
Extracts a specific PDF page and transforms it into a structured, high-quality Markdown/LaTeX note.


### E. Safe Book Deletion (API Endpoint)
Allows removing books from the library while preserving a backup.
*   **Archiving**: Moves the physical file to  before DB removal.
*   **Database Cleanup**: Removes the book record, FTS entries, and associated bookmarks.

### D. Smart File Replacement (API Endpoint)
Allows upgrading existing books with "better" versions through the Web UI.
*   **Heuristics**: Automatically verifies that the new file's page count is within ±10% of the original.
*   **Preservation**: Keeps all existing curated metadata (Title, Author, Summary) while updating technical fields (Hash, Size).
*   **Safety**: Automatically archives the old version in `_Admin/Archive/Replaced`.

### E. Safe Book Deletion (API Endpoint)
Allows removing books from the library while preserving a backup.
*   **Archiving**: Moves the physical file to `_Admin/Archive/Deleted` before DB removal.
*   **Database Cleanup**: Removes the book record, FTS entries, and associated bookmarks.

---

## 5. Model Context Protocol (MCP) Server
Located in `mcp_server/`, this allows an LLM (like Gemini) to act as a "Library Agent".
*   **Tools exposed:**
    *   `search_books`: Query the hybrid search engine.
    *   `get_book_details`: Deep-dive into a specific volume.
    *   `read_pdf_pages`: Extract raw text (cost-efficient).
    *   `convert_pdf_to_note`: High-quality AI synthesis.
    *   `get_book_toc`: Structured structure browsing.
    *   `manage_bookmarks`: Persistent storage of key findings.

---

## 6. Database & Maintenance (`library.db`)
*   **`books` Table**: Core metadata, summaries, and binary embeddings.
*   **`books_fts`**: Virtual table for high-speed keyword matching.
*   **Sanity Tools**:
    *   `db_sanity.py`: Removes dead paths and resolves physical duplicates.
    *   `repair_indexes.py`: Fixes formatting in the `index_content` field.
    *   `vectorize.py`: (Re)calculates semantic embeddings for the entire library.

---

## 7. Testing Framework & Quality Assurance
The project includes a comprehensive automated test suite in `tests/`.
*   **Unit Tests (`tests/unit/`)**: Verifies core modules in isolation (Search, Ingestor, Sanity, BibHunter, etc.).
*   **Integration Tests (`tests/integration/`)**: Validates the search pipeline and database interactions.
*   **API Tests (`tests/api/`)**: Functional tests for REST endpoints using the Flask test client.
*   **Mocking Policy**: All calls to the Gemini API are mocked to ensure tests are fast, deterministic, and free.
*   **Command**: Run `export PYTHONPATH=. && .venv/bin/pytest`.

---

## 8. The REHAB Protocol (Development Rules)
1.  **Think Before Coding**: Explicitly state assumptions. If confused, surface the tradeoff.
2.  **Simplicity First**: Minimum code to solve the problem. No speculative "flexibility".
3.  **Surgical Changes**: Touch only what you must. Match existing style perfectly.
4.  **Goal-Driven Execution**: Define success (tests/checks) before implementation. **New feature? Write a test first.**

> [!CAUTION]
> **NO COWBOY CODING**: Never edit files directly on the remote server. Always use `deploy_and_debug.py` to ensure local changes are the "Source of Truth".
