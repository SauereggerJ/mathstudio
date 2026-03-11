# Chapter 8: Infrastructure & Deployment

This chapter details the MathStudio infrastructure stack, container orchestration, and the initialization sequences required for a production-grade deployment.

## 1. Container Architecture (`docker-compose.yml`)

MathStudio is orchestrated via Docker Compose, isolating the application from its federated search engines.

### Service Stack

| Service | Image | Ports | Role |
| :--- | :--- | :--- | :--- |
| `mathstudio` | `.` (Python 3.11) | `5002:5001` | Main Flask app & MCP bridge. |
| `elasticsearch`| `elasticsearch:8.12.2`| `9200:9200` | Vector (kNN) and Text (BM25) search engine. |
| `mathwebsearch`| `mathwebsearch:latest` | `8085:8080` | Structural math formula search engine. |

### Volume Management
*   `../:/library`: Maps the actual research documents to the container.
*   `/srv/.../obsidian:/obsidian`: Direct bridge to the researcher's knowledge base.
*   `~/mathstudio_search_data/es_data`: Persistent storage for ES indices to survive container restarts.

---

## 2. Environment Configuration

The application relies on critical environment Variables passed into the `mathstudio` container:

| Variable | Default Value | Purpose |
| :--- | :--- | :--- |
| `ELASTICSEARCH_URL`| `http://elasticsearch:9200` | Internal network link to the ES service. |
| `MWS_URL` | `http://mathwebsearch:8080` | Internal network link to the MWS service. |
| `GEMINI_API_KEY` | *From credentials.json* | Required for Vision OCR and embeddings. |
| `DEEPSEEK_API_KEY` | *From credentials.json* | Optional for High-speed reasoning fallback. |

---

## 3. Initialization Pipeline (`scripts/`)

Before the first launch, the following sequence must be executed to prepare the federated engines:

### 1. Elasticsearch Indexing (`initialize_search.py`)
This script calls `core.search_engine.create_mathstudio_indices()`. It defines the strict mappings for:
*   `mathstudio_books`: (Embeddings, MSC, metadata).
*   `mathstudio_pages`: (Page-level deep text).
*   `mathstudio_terms`: (KB extraction hits).
*   `mathstudio_concepts`: (Canonical ontology).

### 2. Relational Migration
SQLite handles its own migrations via `DatabaseManager.initialize_schema()`, which runs at every startup to ensure the `STRICT` tables and `FTS5` virtual tables match the latest codebase version.

---

## 4. Maintenance & Health Checks

MathStudio implements a `/system-check` workflow that audits the health of all three engines:
1.  **SQLite Check**: Verifies table integrity.
2.  **ES Check**: Pings `_cluster/health`.
3.  **MWS Check**: Verifies harvest file accessibility.
4.  **Disk Check**: Ensures `LIBRARY_ROOT` is mounted correctly.
