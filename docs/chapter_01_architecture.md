# MathStudio: Architectural Overview

MathStudio is an enterprise-grade digital research library management system designed for mathematical sciences. It leverages a federated search architecture, combining relational metadata, dense vector search, and structural mathematical formula matching.

## 1. System Components

The architecture is composed of four primary layers:

### A. The Core Application Layer (Flask)
The central nervous system of MathStudio.
*   **Web Interface**: A template-driven UI using Jinja2 and Vanilla CSS.
*   **REST API (v1)**: Orchestrates workflows between the frontend and backend services.
*   **Blueprint Architecture**: Modularizing routes (e.g., `api_v1`, `book_details`).

### B. Persistence Layer (SQLite 3)
Manages relational state and metadata.
*   **WAL Mode**: Enabled for high-concurrency read/write operations.
*   **STRICT Tables**: Ensuring data integrity across all core tables (books, chapters, bib_entries, etc.).
*   **FTS5 Integration**: Local full-text search for fast metadata lookups and page-level LaTeX indexing.

### C. Federated Search Engine (ES & MWS)
Provides high-performance discovery across heterogeneous data.
*   **Elasticsearch (v8.12+)**:
    *   `mathstudio_books`: Metadata + 768-dim Gemini embeddings (kNN).
    *   `mathstudio_pages`: Granular page-level content.
    *   `mathstudio_terms`: Knowledge Base term indexing.
*   **MathWebSearch (MWS)**:
    *   Structural formula search using substitution tree indexing.
    *   Handles sanitized Content MathML for precise mathematical matching.

### D. AI & Enrichment Layer (Gemini)
Integrates state-of-the-art LLMs for structural extraction and semantic understanding.
*   **Gemini 2.5 Flash**: Primary model for vision-based OCR (PDF to LaTeX/Markdown).
*   **Gemini Embedding**: Generates 768-dimensional vectors for semantic search.
*   **AI Reranking**: A "librarian pass" to refine search results based on mathematical relevance.

---

## 2. The Federated Search Pipeline

The engine follows a 6-stage cascade to ensure maximum recall and precision:

1.  **Math Pass**: Structural LaTeX matching via MWS. Query variables (e.g., `?a + ?b`) are supported.
2.  **Hybrid Pass**: Combined kNN vector search + Multi-match text search (BM25) in Elasticsearch.
3.  **Boost Profile**: Metadata fields receive weighted scores:
    *   `title^4`
    *   `index_text^3`
    *   `toc^2`
    *   `zb_review^1`
4.  **Index Boost**: A manual override boost (+0.5) for matches found in the physical back-of-the-book index.
5.  **Relational Enrichment**: ES results are joined with SQLite metadata (paths, years, publishers).
6.  **AI Reranking**: Final refinement using LLM logic to prune irrelevant hits.

---

## 3. Data Ingestion Workflow

Incoming documents (PDF/DjVu) pass through a multi-phase pipeline:

1.  **Phase 1: Scanning**: Page-by-page vision extraction converting PDF images to LaTeX/Markdown.
2.  **Phase 2: Term Extraction**: Identification of Definitions, Theorems, and Lemmas.
3.  **Phase 3: Embedding**: Generating vectors for books, pages, and terms.
4.  **Phase 4: Anchoring**: Mapping extracted terms to the canonical Knowledge Base Concepts.
5.  **Phase 5: Synchronization**: Updating Elasticsearch and MWS with the newly processed data.

---

## 4. Key Maintenance Routines

*   **Housekeeping**: Scheduled ogni 12 hours to clean the wishlist and refresh DOI/zbl_id mappings.
*   **Scan Worker**: A background thread processing the ingestion queue sequentially.
*   **FTS Backfill**: On startup, ensures the local SQLite FTS indices are in sync with cached content.
