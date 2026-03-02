# MathStudio: Instructional Context & Guidelines

## 1. Project Overview
MathStudio is an enterprise-grade digital research library management system designed specifically for mathematical sciences. It enables researchers to manage, search, and extract knowledge from large collections of PDF and DjVu documents using a sophisticated federated search architecture.

### Core Technologies
*   **Backend**: Python 3.11 (Flask)
*   **Database**: SQLite 3 (WAL mode) for relational state and metadata.
*   **Search Engine (Federated)**:
    *   **Elasticsearch (v8.12+)**: Dense vector search (768-dim Gemini embeddings) and high-performance BM25 text search.
    *   **MathWebSearch (MWS)**: Structural mathematical formula search using substitution tree indexing.
*   **AI Integration**: Google Gemini (Pro, Flash, and Embedding models) for vision-based extraction, semantic search, and metadata enrichment.
*   **Infrastructure**: Docker & Docker Compose.

---

## 2. Key Architectural Standards

### The "Absolute PDF Page" House Rule
All page-level data—including deep-indexed text, Knowledge Base extractions, and MathWebSearch URIs—must strictly adhere to the **1-indexed absolute PDF page number**. 
*   **Constraint**: Never use printed page numbers for internal logic. 
*   **Validation**: Use `read_pdf_pages` to verify offsets before performing AI-driven extractions.

### Federated Search Pipeline
The search system follows a 6-stage cascade:
1.  **Math Pass**: Structural LaTeX matching via MWS (sanitized MathML).
2.  **Hybrid Pass**: Combined kNN vector search + Multi-match text search in Elasticsearch.
3.  **Boost Profile**: `title^4`, `index_text^3`, `toc^2`, `zb_review^1`.
4.  **Index Boost**: +0.5 score boost for matches found in the back-of-book index strings.
5.  **Relational Enrichment**: Joining ES hits with SQLite metadata.
6.  **AI Reranking**: Final "librarian pass" using LLM for precision.

---

## 3. Building and Running

### Development Environment
*   **Dependencies**: `pip install -r requirements.txt` (requires `elasticsearch`, `beautifulsoup4`, `lxml`).
*   **System Tools**: `latexml` must be installed for LaTeX-to-MathML conversion.

### Launching the Stack
```bash
# Start all services (ES, MWS, MathStudio)
docker-compose up -d

# Initialize Search Indices
python3 scripts/initialize_search.py

# Perform Migration (if database is new)
python3 scripts/migrate_to_federated.py
```

### Key Endpoints
*   **Web UI**: `http://localhost:5002`
*   **REST API**: `http://localhost:5002/api/v1`
*   **MCP Server**: Accessible via stdio for LLM tools.

---

## 4. Development Conventions

### Data Ingestion Pipeline
When modifying ingestion (e.g., `universal_processor.py` or `indexer.py`), you MUST ensure the search engines stay in sync:
1.  **Books**: Sync metadata and embeddings to the `mathstudio_books` ES index.
2.  **Pages**: Bulk-stream text to the `mathstudio_pages` ES index during deep indexing.
3.  **Formulas**: Sanitize MathML (strip all attributes except `xmlns`) and append to `mathstudio.harvest` for MWS.

### Coding Style
*   **Type Safety**: Use Python type hints for service methods.
*   **Error Handling**: Wrap external service calls (ES, MWS, latexmlmath) in try-except blocks to prevent ingestion halts.
*   **Paths**: Always use `pathlib.Path` for filesystem operations. Use `LIBRARY_ROOT` as the base for all book paths.

---

## 5. Key Files
*   `services/search.py`: The heart of the federated search orchestration.
*   `core/search_engine.py`: Elasticsearch client and index mapping definitions.
*   `services/knowledge.py`: Management of mathematical terms and MWS harvesting.
*   `mcp_server/server.py`: MCP protocol bridge for agentic research.
*   `dokumentation/`: Detailed reports on architecture and troubleshooting history.
