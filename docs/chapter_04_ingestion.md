# Chapter 4: Data Ingestion & Enrichment Pipeline

This chapter provides an exhaustive mapping of the MathStudio ingestion stack. It details the **Universal Pipeline** (Vision OCR), the **Ingestor Service** (Flow Control), and the **Indexer Service** (Deep Indexing).

## 1. Universal Processor (`services/universal_processor.py`)

The `UniversalProcessor` is a "Fast Pipeline" designed to extract structural metadata from raw PDFs using Gemini Pro Vision.

### Class: `UniversalProcessor`

| Method | Signature | Detailed Rationale & Logic |
| :--- | :--- | :--- |
| `process_book` | `(book_id, save_to_db: bool)` | **Master Entry Point**: Orchestrates slicing, upload, holistic AI pass, and verification. Handles temporary file cleanup (`gc.collect()`). |
| `_get_library_folders`| `() -> list` | Dynamically scans `LIBRARY_ROOT` for numeric folders (e.g. `04_Algebra`) to provide the AI with existing routing options. |
| `_initial_holistic_pass`| `(file_obj, folders, native_toc)` | **The Core Prompt**: Instructs Gemini to perform OCR, summarize, describe, and route the book. It injects "Native TOBM" as a baseline to prevent hallucinations. |
| `_detect_conflicts` | `(initial_json, verification, filename)` | Uses `rapidfuzz` to compare AI-extracted titles against the physical filename. Flags mismatches. |
| `_reflection_pass` | `(file_obj, json, verification, conflicts)` | **Self-Correction**: If conflicts are found, it triggers a second AI call with a specific "Correction Prompt" to resolve discrepancies. |
| `_save_to_db` | `(book_id, final_data)` | Persists 17+ metadata fields (STRICT parsing of authors/terms). **Crucial**: Triggers a synchronous `index_book()` call to update Elasticsearch. |

---

### Dataflow: The Universal Vision Pipeline
The following diagram showcases the "fast-track" metadata extraction used when a new book enters the system.

```mermaid
graph LR
    File[Raw PDF/DjVu] --> Slice[Slice Front Matter (Pages 1-5)]
    Slice --> AI{Gemini Vision Pass}
    AI --> JSON[Structural JSON]
    JSON --> Verify{Refuzz Verification}
    Verify -->|Confidence High| DB[(SQLite)]
    Verify -->|Conflicts Found| Reflect[Reflection Pass]
    Reflect -->|Self-Correction| DB
    DB --> Route[Physical Move to Subfolder]
```

### The AI Reflection Pass (Self-Correction Logic)
When `_detect_conflicts` finds a significant discrepancy between the AI's extracted title and the physical filename (using `rapidfuzz` token-ratio), the `_reflection_pass` is triggered:
1.  **Context Injection**: The AI is given its initial JSON and a specific "Conflict Report".
2.  **Multimodal Re-examination**: The same visual pages are re-sent with a prompt asking: *"The filename says X, but you said Y. Explain the discrepancy and provide the correct canonical title."*
3.  **Conflict Resolution**: If the AI confirms the filename is correct (or provides a third, better option), the JSON is updated and the `trust_score` is adjusted accordingly.

---

## 2. Ingestor Service (`services/ingestor.py`)

The `IngestorService` acts as the high-level manager for the library flow, deciding when to run previews and how to route new files.

### Class: `IngestorService`

| Method | Signature | Logic & Side Effects |
| :--- | :--- | :--- |
| `refresh_metadata` | `(book_id)` | Triggers full pipeline + `zbmath_service.enrich_book()` + `search_service.vectorize_book()`. |
| `process_file` | `(file_path: Path, execute: bool)` | **New Ingest Logic**: 1. Hash/Duplicate check. 2. Shell entry creation. 3. Pipeline execution. 4. Metadata-driven physical `shutil.move()` to the target folder. 5. DB path update. |
| `run_review_round` | `(time_window: int)` | **QA utility**: Audits books ingested in the last N seconds for missing Zbl IDs, low trust scores, or 'conflict' statuses. |

---

## 3. Indexer Service (`services/indexer.py`)

The `IndexerService` manages the transition from "Raw PDF" to "Searchable Text/LaTeX" at the page level.

### Class: `IndexerService`

| Method | Signature | Logic & Side Effects |
| :--- | :--- | :--- |
| `extract_full_text` | `(file_path)` | Extracts flat text with `[[PAGE_N]]` markers for the legacy `books_fts` index. |
| `deep_index_book` | `(book_id)` | **Page-Level Sync**: Extract per-page text (PdfReader/djvutxt) and performs a **Bulk Upload** to the `mathstudio_pages` ES index. |
| `scan_library` | `(force: bool)` | Walks `LIBRARY_ROOT` and reconciles DB state with disk state. Triggers `bibliography_service` for every new book. |
| `reconstruct_index` | `(book_id)` | **OCR-to-Boolean**: 1. Identifies likely index pages. 2. Samples text. 3. Prompts AI to re-format as `Term | Page`. Updates `books_fts`. |
| `audit_tocs` / `audit_indexes` | `()` | Heuristic auditing based on "Digit Density" and "Structure Score" to flag poor-quality metadata. |
| `repair_missing_tocs`| `()` | Attempts to recover `native_toc` using `fitz` bookmarks for records missing structured chapters. |

---

## 4. Pipeline Logic Summary

1.  **File Arrival**: `process_file()` creates a database record.
2.  **Metadata Extraction**: `UniversalProcessor` runs Vision-OCR on front-matter.
3.  **Physical Routing**: Book is moved from `/Unsorted` to a specific subfolder (e.g., `04_Algebra`).
4.  **Deep Enrichment**: `zbmath_service` fetches official reviews and MSC codes.
5.  **Search Sync**: Metadata and dense vectors are pushed to `mathstudio_books`.
6.  **Deep Indexing**: Pages are sliced and pushed to `mathstudio_pages`.
