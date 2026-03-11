# MathStudio Technical Documentation

Welcome to the internal technical documentation for MathStudio. This repository of knowledge is designed for researchers, developers, and administrators of the system.

## Table of Contents

### [Chapter 1: Architectural Overview](chapter_01_architecture.md)
Introduction to the federated search architecture, the AI-driven reranking cascade, and core component interaction.

### [Chapter 2: Relational Database Schema & State Management](chapter_02_database.md)
Detailed breakdown of the SQLite schema (WAL mode), STRICT tables, and metadata state transitions.

### [Chapter 3: Search Engine Architecture (ES & MWS)](chapter_03_search.md)
Technical details of Elasticsearch (BM25 + kNN vector search) and MathWebSearch (structural formula matching).

### [Chapter 4: Data Ingestion & Enrichment Pipeline](chapter_04_ingestion.md)
Deep dive into the ingestion flow: OCR/Vision-based extraction (Gemini), and deterministic enrichment (zbMATH).

### [Chapter 5: Knowledge Base & Semantic Anchoring](chapter_05_knowledge_base.md)
The core of the literature graph: Disambiguation (DeepSeek), semantic search (RRF), and MWS formula harvesting.

### [Chapter 6: AI Integration & MCP Server](chapter_06_ai_mcp.md)
AI routing policies (Gemini/DeepSeek), RAG workflows, and the MCP research protocol.
### [Chapter 7: API Reference & Web Architecture](chapter_07_web_api.md)
REST v1 endpoint specifications and the Flask template-driven UI architecture.

### [Chapter 8: Infrastructure, Deployment & Maintenance](chapter_08_infrastructure.md)
Docker setup, background maintenance routines, and diagnostic tools.

## Technical Standards

*   **Language**: Python 3.11 / Vanilla JS
*   **Storage**: SQLite 3 (WAL) / Elasticsearch 8.12
*   **AI**: Google Gemini Pro/Flash
*   **Indexing**: MWS (MathWebSearch)
