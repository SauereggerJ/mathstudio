# MathStudio Search Architecture Report

This document details the search capabilities of the MathStudio project, including technical implementations, data flows, and the underlying multi-stage search engine.

---

## 1. Architecture Overview

MathStudio employs a **Hybrid Search Engine** that combines traditional information retrieval (Full-Text Search) with modern semantic understanding (Vector Embeddings) and AI-powered reasoning.

### 1.1 Core Components
- **`SearchService` (`services/search.py`)**: The central orchestration layer.
- **`IndexerService` (`services/indexer.py`)**: Responsible for building and maintaining search indexes.
- **`api_v1.py`**: Exposes search capabilities via a RESTful interface.
- **`mcp_server/server.py`**: Provides specialized tools for LLM agents to interact with the search engine.
- **SQLite FTS5**: Powers high-performance full-text search with BM25 ranking.
- **Gemini Embedding Model**: Generates 768-dimensional semantic vectors for books and queries.
- **Elasticsearch (Docker)**: Deployed for future scalable semantic and advanced search capabilities.
- **MathWebSearch (Docker)**: Deployed to enable formula-based querying via Content MathML.

---

## 2. The 6-Stage Search Pipeline

When a user or agent submits a query to the primary `/search` endpoint, it triggers a sophisticated pipeline:

1.  **Query Pre-processing**:
    - **Expansion**: If enabled, Gemini translates non-English queries and adds mathematical synonyms to improve recall.
    - **Embedding**: The query is converted into a vector embedding in parallel with expansion.
2.  **Vector Search**: 
    - Cosine similarity is calculated against all book embeddings stored in the database.
    - Matches with a score > 0.25 are added to the candidate list.
3.  **Full-Text Search (FTS5)**:
    - Performs BM25 ranking across `title`, `author`, and `content`.
    - If a candidate exists in both Vector and FTS results, the scores are fused (60% Vector, 40% FTS).
4.  **Back-of-Book Index Lookup**:
    - The engine searches the extracted `index_text` for the specific query term.
    - Hits in the physical index add a **+0.5 boost** to the candidate's score.
5.  **Metadata Fallback**:
    - If no candidates are found via Vector or FTS, a standard SQL `LIKE` query is performed as a last resort.
6.  **AI Reranking (Optional)**:
    - The top candidates are sent to Gemini for a "librarian pass," where it ranks them based on deep mathematical relevance and provides a reasoning string.

---

## 3. Data Flows

### 3.1 Web UI Flow
1.  **Trigger**: User types in the search bar on the Index or MSC Browser page.
2.  **Transport**: Frontend calls `GET /api/v1/search?q=...`.
3.  **Process**: `api_v1.py` calls `search_service.search()`.
4.  **Response**: Returns a JSON list of books with snippets, scores, and BibTeX entries. The UI renders these results with thumbnails.

### 3.2 MCP Server (Agentic) Flow
1.  **Trigger**: An LLM (e.g., Claude) calls the `search_books` tool.
2.  **Transport**: MCP server receives the tool call and proxies it to the local API.
3.  **Process**: Same as UI flow, but often uses `use_rerank=True` for higher precision.
4.  **Response**: The MCP server formats the JSON results into a structured text report for the LLM to read.

### 3.3 Deep Within-Book Search
1.  **Trigger**: User searches while viewing a specific book.
2.  **Logic**: If the book is "Deep Indexed" (has page-level text in `pages_fts`), it performs a per-page FTS5 search.
3.  **Fallback**: If not deep indexed, it falls back to a regex-based snippet extractor that identifies the closest `[[PAGE_N]]` marker in the full-text blob.

---

## 4. Technical Implementations

### 4.1 Indexing & Schemas
- **`books_fts`**: Virtual table for library-wide search. 
  - *Columns*: `title`, `author`, `content`, `index_content`.
- **`pages_fts`**: Virtual table for granular within-book search.
  - *Columns*: `book_id`, `page_number`, `content`.
- **`knowledge_terms_fts`**: Specialized index for harvested theorems and definitions.
  - *Columns*: `name`, `used_terms`, `latex_content`.

### 4.2 Key Python Methods

| Method | File | Purpose |
|--------|------|---------|
| `search()` | `search.py` | Main orchestration entry point. |
| `search_books_semantic()` | `search.py` | Numpy-powered cosine similarity across the library. |
| `extract_index_pages()` | `search.py` | Regex-based parser for physical index strings. |
| `deep_index_book()` | `indexer.py` | Populates `pages_fts` table for a specific PDF. |
| `scan_library()` | `indexer.py` | Syncs filesystem with DB and updates `books_fts`. |

---

## 5. Search Features Comparison

| Feature | Scope | Engine | Strength |
|---------|-------|--------|----------|
| **Hybrid Search** | Library | FTS5 + Vector | Broad discovery, handles synonyms. |
| **Index Search** | Book | Regex / FTS | High precision for specific terms. |
| **Deep Search** | Page | FTS5 | Find exact definitions or theorem statements. |
| **Semantic Search** | Library | Gemini Embeddings | Find "books like this one" or conceptual matches. |
| **KB Search** | Terms | FTS5 | Fastest path to proven mathematical facts. |
