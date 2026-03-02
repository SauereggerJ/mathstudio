# MathStudio Search Architecture (Federated)

## 1. Overview
The MathStudio search system has transitioned from a local SQLite FTS5/NumPy vector search to a scalable **federated architecture**. This architecture combines the lexical and semantic power of **Elasticsearch** with the structural mathematical precision of **MathWebSearch (MWS)**.

## 2. The 6-Stage Federated Pipeline
Search queries are orchestrated through a 6-stage cascade in `services/search.py`:

1.  **Math Pass (Structural)**: 
    *   Queries containing LaTeX are converted to Content MathML via `latexmlmath`.
    *   MathML attributes are stripped for maximum matching compatibility.
    *   MWS retrieves matching `term_id`s from the substitution tree index.
2.  **Hybrid Pass (Elasticsearch)**:
    *   **Lexical**: BM25 text search across titles, authors, summaries, and deep-indexed pages.
    *   **Semantic**: kNN dense vector search using 768-dim Gemini embeddings.
    *   **Boosting**: Field-level boosts applied: `title^4`, `index_text^3`, `toc^2`, `zb_review^1`.
3.  **Cross-Engine Fusion**: MWS hits are used to filter or significantly boost candidates in the ES result set.
4.  **Index Boost**: A +0.5 score boost is applied to books where the query is found in the physical back-of-book index.
5.  **Relational Enrichment**: Joining ES hits with SQLite metadata (paths, status, year).
6.  **AI Reranking**: Final precision pass using Gemini to rank the top 10 candidates.

## 3. Data Indices
*   **`mathstudio_books`**: Metadata, AI summaries, and dense embeddings.
*   **`mathstudio_pages`**: Granular, page-level text (deterministic IDs: `book_{id}_p{page}`).
*   **`mathstudio_terms`**: Knowledge Base theorems and definitions.
*   **`mathstudio.harvest`**: Unified Content MathML file used by MWS.

## 4. Maintenance & Ingestion
*   **Incremental Sync**: Every update to the SQLite `books` or `knowledge_terms` table triggers an instant sync to Elasticsearch and an append to the MWS harvest file.
*   **Deep Indexing**: A baseline library-wide pass is performed to ensure every page is searchable. High-quality AI LaTeX scans automatically overwrite raw text indices via deterministic IDs.
