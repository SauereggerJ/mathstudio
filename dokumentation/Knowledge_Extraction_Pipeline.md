# Knowledge Extraction Pipeline Technical Report

This document details the technical architecture, Python implementation, and call sequences of the MathStudio PDF-to-LaTeX and Knowledge Extraction pipeline.

---

## 1. System Components & Method Signatures

### 1.1 Orchestration Layer (`app.py`, `api_v1.py`)
Responsible for job queueing and background worker initialization.

-   **`app.py: _run_scan_worker()`**
    -   Starts the background thread that polls for new scan jobs.
-   **`api_v1.py: enqueue_book_scan(book_id)`**
    -   API Endpoint: `POST /api/v1/books/<int:book_id>/scan`
    -   Creates a record in the `book_scans` table to trigger the background process.
-   **`api_v1.py: pdf_to_note_tool()`**
    -   API Endpoint: `POST /api/v1/tools/pdf-to-note`
    -   The "Lab" entry point for manual, synchronous extraction of a page range.

### 1.2 Service Layer (`services/note.py`)
The "Brain" of the operation, managing the high-level logic, caching, and deduplication.

-   **`scan_worker(self)`**
    -   An infinite loop that picks the oldest `queued` job from the DB.
-   **`run_book_scan(self, scan_id)`**
    -   Executes the full-book workflow: classification, batch conversion, and term harvesting.
-   **`get_or_convert_pages(self, book_id, pages, force_refresh=False, min_quality=0.7, abort_on_failure=False)`**
    -   The central portal for digitized LaTeX. Orchestrates cache lookup vs. AI batch conversion.
-   **`extract_and_save_knowledge_terms_batch(self, book_id, pages_list, window_buffer=2, force=False)`**
    -   Chunks a list of pages and calls the AI to harvest definitions/theorems.
-   **`_save_knowledge_term(self, book_id, page_start, term_data)`**
    -   Handles fuzzy deduplication (via RapidFuzz) and SQLite persistence.

### 1.3 AI Interface Layer (`converter.py`)
Specialized low-level functions that interact directly with the Gemini API.

-   **`convert_pages_batch(book_path: str, pages: list[int])`**
    -   Uses "Gate Logic" to decide between native PDF or Raster extraction. Uploads a batch of pages to Gemini.
-   **`extract_terms_batch(concatenated_latex, start_page, end_page, metadata=None)`**
    -   Analyses a block of LaTeX to identify formal mathematical terms and their descriptors.
-   **`repair_latex(latex_content: str, original_text_preview: str, error_msg: str) -> str | None`**
    -   The "Active Repair Loop" that fixes malformed LaTeX based on linting/compilation errors.

---

## 2. Call Sequence (Full Book Scan)

The following sequence illustrates how a "Full Book Scan" flows through the system:

1.  **`app.py`** starts a daemon thread calling **`NoteService.scan_worker()`**.
2.  **`scan_worker()`** finds a queued job and calls **`NoteService.run_book_scan(scan_id)`**.
3.  **`run_book_scan()`** classifies pages and groups them into chunks.
4.  For each chunk, it calls **`NoteService.get_or_convert_pages()`**.
5.  **`get_or_convert_pages()`** calls **`converter.convert_pages_batch()`**.
6.  **`converter.convert_pages_batch()`** uploads files to Gemini and returns structured LaTeX.
7.  **`get_or_convert_pages()`** performs linting/compilation checks. If errors occur, it calls **`converter.repair_latex()`**.
8.  Once LaTeX is cached, **`run_book_scan()`** calls **`NoteService.extract_and_save_knowledge_terms_batch()`**.
9.  **`extract_and_save_knowledge_terms_batch()`** calls **`converter.extract_terms_batch()`** to find markers.
10. **`NoteService._save_knowledge_term()`** is called for each discovery to finalize the DB entry.

---

## 3. Alternative & Obsolete Methods

### 3.1 Obsolete (Removed)
-   **`converter.convert_page(path, page_num)`**: Formerly used for single-page conversion. Removed in favor of batching to reduce API overhead and preserve context.
-   **`NoteService._create_proposals_from_discoveries()`**: Legacy method that pushed discoveries into the old `kb_proposals` table. Replaced by the Flat Term Index system.

### 3.2 Similar but Distinct Usage
-   **`NoteService.transcribe_note(image_data)`**:
    -   **Usage**: Used for handwritten notes (E-Ink scans) rather than textbook PDFs.
    -   **Difference**: It generates both Markdown and LaTeX in a single pass without the marker-based extraction needed for books.
-   **`NoteService.create_note_from_pdf(book_id, pages)`**:
    -   **Usage**: High-level UI action to "turn these pages into a standalone research note".
    -   **Difference**: It aggregates the LaTeX into a single `.md` and `.tex` document for the user to edit, rather than indexing atomic terms in the KB.
-   **`NoteService.backfill_latex_fts()`**:
    -   **Usage**: Management utility.
    -   **Difference**: Populates the search index from existing files on disk without calling any AI components.

---

## 4. Current Pipeline Statistics (March 2026)

| Metric | Value |
|--------|-------|
| **Total Knowledge Terms** | **1,248** |
| Terms with Full LaTeX | 1,003 (80.4%) |
| Terms with Placeholders/Markers | 245 (19.6%) |
| **Searchable Pages (FTS)** | **~2,500 cached LaTeX pages** |
