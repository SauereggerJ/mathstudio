# MathStudio: Project State & Architecture (Fresh Start 2026)

This document provides a definitive, ground-truth analysis of the MathStudio project as of March 2026, superseding older documentation where contradictions exist.

---

## 1. Core Architecture: The Federated Engine
MathStudio operates on a **Federated Search & Management** architecture. It no longer relies solely on local SQLite FTS; instead, it orchestrates three distinct search engines:

| Engine | Role | Implementation |
| :--- | :--- | :--- |
| **Relational (SQLite WAL)** | Source of Truth | Metadata, book paths, user notes, and term registry. |
| **Semantic/Lexical (Elasticsearch 8.12)** | "Librarian" | Dense vector search (768-dim Gemini), BM25 text search (titles, summaries, deep-indexed pages). |
| **Structural (MathWebSearch)** | "Mathematician" | Substitution tree indexing of Content MathML for formula matching with query variables (`?a`, `?b`). |

### Indices in Elasticsearch:
1. `mathstudio_books`: Metadata, AI summaries, dense embeddings.
2. `mathstudio_pages`: Page-level digitized text (deterministic IDs: `book_{id}_p{page}`).
3. `mathstudio_terms`: Knowledge Base theorems/definitions.

---

## 2. Ingestion & "Slow Crawl" Pipeline
The system uses a multi-phase pipeline to turn raw PDFs into searchable knowledge.

### Phase A: Universal Ingestion (Fast)
- **Tool**: `UniversalProcessor` (triggered by `IngestorService`).
- **Process**: Extracts front matter and bibliography slicing → Gemini Vision holistic analysis → zbMATH/Crossref verification → Auto-renaming and folder routing.
- **Outcome**: A book record with metadata, TOC, and basic index keywords.

### Phase B: Full Book Digitization ("Slow Crawl")
- **Tool**: `NoteService.run_book_scan`.
- **Logic**: A background worker picks books from a queue.
- **Classification**: Heuristically skips front/back matter; focuses only on "content" pages.
- **Digitization**: Processes pages in adaptive batches (up to 25) using Gemini Vision.
- **Active Repair Loop**:
    - **Gate 1 (Lint)**: Checks LaTeX environment/bracket balance.
    - **Gate 2 (Compile)**: Attempts `pdflatex` compilation of snippets.
    - **Gate 3 (Repair)**: If Gate 1 or 2 fails, `converter.repair_latex` sends the error log back to the AI for a surgical fix.
- **Sync**: Results are pushed to `mathstudio_pages` (ES) for full-text search.

### Phase C: Knowledge Harvesting (The Lab)
- **Logic**: During the slow crawl, extractable pages are analyzed for mathematical terms (theorems, definitions).
- **Speaking Names**: AI generates descriptive titles (e.g., "Cauchy's Integral Formula (Theorem 4.1)").
- **Deduplication**: RapidFuzz (>85% similarity) prevents duplicate terms within a ±1 page window.

---

## 3. Mathematical Search Orchestration
The `SearchService` orchestrates the search flow in 6 stages:

1. **Math Pass**: LaTeX queries are converted to Content MathML (latexmlmath) and sent to MWS. Supports query variables.
2. **Hybrid Pass**: Parallel lexical and semantic search in ES (`mathstudio_books`).
3. **Cross-Engine Fusion**: MWS hits boost corresponding books/terms in the ES result set.
4. **Index Boost**: +0.5 score boost if the query matches a back-of-book index term in SQLite.
5. **Relational Enrichment**: Joins ES IDs with SQLite to retrieve real filesystem paths.
6. **AI Reranking**: Final precision pass using Gemini to explain relevance.

---

## 4. Maintenance & Sync Logic
- **MWS Harvesting**: Done via `scripts/fix_mws_harvest.py`. It generates a file-based harvest at `/library/mathstudio/mathstudio.harvest` using canonical namespaces.
- **Incremental Sync**: `KnowledgeService.sync_term_to_federated` pushes new "approved" terms to ES and appends to the MWS harvest.
- **Deep Indexing**: `IndexerService` provides a baseline raw-text index before high-quality AI LaTeX overwrites it.

---

## 5. Strict Data Rules
- **Absolute PDF Page Rule**: All page references must be **1-indexed absolute PDF pages**. No printed page numbers are used for internal logic.
- **Marker-Based Extraction**: KB terms use textual markers (e.g., "Definition 2.1") instead of line numbers for stability.
- **Cache Registry**: `extracted_pages` table tracks quality scores and paths for every digitized page.

---

## 6. Current Project State: "Extraction & Evolution"
As of March 2026, the specific "Zorich Repair" phase has concluded. The system has shifted into two parallel high-priority tracks:

### A. Intensive Exercise Extraction (Book ID 510 Focus)
The "Slow Crawl" engine is currently targeting advanced mathematical exercises (e.g., Hodge-Laplace, Laplace-Beltrami, Maxwell's Equations). 
- **Activity**: High volume of `exercise` type terms being harvested.
- **Challenge**: Snippet extraction occasionally fails due to OCR/marker mismatches (as seen in `app.log` for Exercise 14), triggering the **Active Repair Loop** and the `log_processing_error` mechanism.

### B. Knowledge Base Evolution (Project: Mathematical Brain)
A strategic shift from a "Flat Term Index" to a "Structured Conceptual Hierarchy" is underway.
- **Concept Layer**: Planning the `mathematical_concepts` table to act as a canonical anchor for all harvested terms.
- **Anchoring Strategy**: Moving from AI-authored titles to AI-matched titles based on a fixed reference list (Wikipedia/MathWorld) to eliminate redundancy.
- **Status**: Schema design and initial anchor list ingestion are the immediate next milestones.

---

## 7. System Health Indicators
- **MWS Harvest**: `mathstudio.harvest` has reached ~1.7M lines, indicating a significant structural math index.
- **KB Scale**: The `knowledge_terms` table has crossed ~9,800 entries.
- **Federated Sync**: The `sync_term_to_federated` workflow is active, ensuring that all approved terms are immediately searchable via formula and text.

---

## 8. MCP Server & Agentic Integration
The project makes heavy use of an MCP server (`mcp_server/server.py`) exposing 40+ tools to LLM agents (e.g., Claude, Gemini). It operates as an HTTP proxy to the Flask REST API.
- **Agent Guardrails**: Critical operational rules are baked into the agent prompts, explicitly banning "TOC LaTeXing" (forcing agents to rely on FTS instead of expensive extraction tools for metadata windows) and strictly enforcing the 1-indexed Absolute PDF Page offset matching.
- **Workflows**: Three main agentic protocols orchestrate interactions: `usage_manifesto` (The Leitidee setting a KB-first philosophy), `researcher_workflow`, and `note_creation_workflow`. 
- **UI State Bridge**: A `current_state.json` file serves as a bridge, allowing the MCP server via `get_system_state` to see exactly what book or component the user currently has open in the web UI.

---

## 9. Codebase Implementation Findings
- **Database Concurrency**: The system explicitly leverages SQLite WAL mode combined with `threading.local()` for thread-safe database connections, enabling concurrent service reads (critical for the parallel nature of the hybrid search via `ThreadPoolExecutor`).
- **Singleton Services**: All major module services (`SearchService`, `KnowledgeService`, etc.) instantiate a global singleton at import time.
- **Two-Tiered Knowledge Store**: While the `knowledge_terms` table represents the primary "Flat Term Index" for active harvesting (representing definitions/theorems contextually), legacy relational structures (`concepts`, `entries`, `relations`) remain supported by the database, acting as a foundation for the "Mathematical Brain" evolution strategy.
