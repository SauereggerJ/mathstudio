# MathStudio Data Schemas

This document outlines the database schemas and internal JSON structures used across the MathStudio project.

---

## 1. SQLite Database: `library.db`

The core data store using SQLite 3 with WAL (Write-Ahead Logging) mode.

### 1.1 Table: `books`
The central registry for all mathematical literature.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER (PK) | Auto-incrementing identifier. |
| `filename` | TEXT | Original filename on disk. |
| `path` | TEXT (UNIQUE) | Relative path from `LIBRARY_ROOT`. |
| `directory` | TEXT | Relative directory path. |
| `author` | TEXT | Primary author(s) string. |
| `title` | TEXT | Full title of the work. |
| `size_bytes` | INTEGER | File size in bytes. |
| `isbn` | TEXT | 10 or 13 digit ISBN. |
| `publisher` | TEXT | Publisher name. |
| `year` | INTEGER | Publication year. |
| `description` | TEXT | Detailed description/blurb. |
| `last_modified` | REAL | Last file system modification time. |
| `arxiv_id` | TEXT | ArXiv identifier (e.g., `2401.12345`). |
| `doi` | TEXT | Digital Object Identifier. |
| `zbl_id` | TEXT | zbMATH identifier (e.g., `Zbl 1234.56789`). |
| `index_text` | TEXT | Text extracted from the back-of-book index. |
| `summary` | TEXT | Short academic summary (often AI-generated). |
| `level` | TEXT | Difficulty level (e.g., Undergraduate, Graduate, Research). |
| `audience` | TEXT | Targeted audience description. |
| `has_exercises` | INTEGER | Boolean (0 or 1) indicating exercise presence. |
| `has_solutions` | INTEGER | Boolean (0 or 1) indicating solution presence. |
| `page_count` | INTEGER | Total pages in the document. |
| `toc_json` | TEXT | Structured Table of Contents (JSON string). |
| `msc_class` | TEXT | MSC 2020 classification codes (comma-separated). |
| `tags` | TEXT | User-defined or AI-extracted keywords. |
| `embedding` | BLOB | 768-dimensional vector embedding (float32). |
| `file_hash` | TEXT | MD5/SHA256 hash of the file content for deduplication. |
| `index_version` | INTEGER | Version of the indexing pipeline used. |
| `reference_url` | TEXT | External URL (e.g., publisher page). |
| `last_metadata_refresh` | INTEGER | Unix timestamp of the last AI/API refresh. |
| `page_offset` | INTEGER | Offset to align PDF page numbers with printed page numbers. |
| `metadata_status` | TEXT | Status: `raw`, `verified`, `conflict`, `ignored`. |
| `trust_score` | REAL | Confidence score (0.0 - 1.0) of the metadata. |
| `zb_review` | TEXT | Markdown review text from zbMATH. |

### 1.2 Table: `chapters` (TOC)
Hierarchical Table of Contents entries.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER (PK) | |
| `book_id` | INTEGER (FK) | References `books.id`. |
| `title` | TEXT | Chapter/Section title. |
| `level` | INTEGER | Depth level (0 for Chapter, 1 for Section, etc.). |
| `page` | INTEGER | Starting page number (aligned). |
| `msc_code` | TEXT | MSC code specific to this chapter. |
| `topics` | TEXT | Topic keywords for this chapter. |

### 1.3 Table: `knowledge_terms` (Flat KB)
Atomic mathematical entities harvested from literature.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER (PK) | |
| `book_id` | INTEGER (FK) | References `books.id`. |
| `page_start` | INTEGER | Page where the term is defined. |
| `name` | TEXT | "Speaking Name" (e.g., "Banach Space (Definition 1.1)"). |
| `term_type` | TEXT | Type: `definition`, `theorem`, `lemma`, `example`, `exercise`. |
| `latex_content` | TEXT | The LaTeX source of the statement. |
| `used_terms` | TEXT | Keywords or dependencies found within the statement. |
| `status` | TEXT | Status: `draft`, `approved`. |
| `created_at` | INTEGER | Unix timestamp. |
| `updated_at` | INTEGER | Unix timestamp. |

### 1.4 Table: `notes`
Registry for research notes and transcriptions.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER (PK) | |
| `title` | TEXT | Note title. |
| `source_type` | TEXT | `handwritten`, `book_extraction`, `manual`. |
| `source_book_id` | INTEGER | References `books.id` (NULL if handwritten). |
| `source_page_number` | INTEGER | Page number (NULL if handwritten). |
| `latex_path` | TEXT | Path to `.tex` file (relative to `PROJECT_ROOT`). |
| `markdown_path` | TEXT | Path to `.md` file (relative to `PROJECT_ROOT`). |
| `pdf_path` | TEXT | Path to compiled `.pdf` file. |
| `json_meta_path` | TEXT | Path to `.json` metadata file. |
| `tags` | TEXT | Keywords. |
| `msc` | TEXT | MSC classification code. |
| `content_preview` | TEXT | Short summary or snippet. |
| `created_at` | INTEGER | Unix timestamp. |
| `updated_at` | INTEGER | Unix timestamp. |

### 1.5 Table: `llm_tasks`
Queue for asynchronous AI operations.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER (PK) | |
| `task_type` | TEXT | e.g., `extract_page_mlx`, `rebuild_index`. |
| `payload` | TEXT | JSON payload specific to the task. |
| `status` | TEXT | `pending`, `processing`, `completed`, `failed`. |
| `priority` | INTEGER | 1 (high) to 10 (low). |
| `retry_count` | INTEGER | |
| `error_log` | TEXT | Error details if failed. |
| `result` | TEXT | JSON result if completed. |
| `created_at` | INTEGER | Unix timestamp. |
| `completed_at` | INTEGER | Unix timestamp. |

---

## 2. Application State: `current_state.json`

Used to communicate the current UI context to LLM agents (MCP).

```json
{
  "last_action": "view_book",
  "timestamp": "2026-03-01T13:58:20.399170",
  "book_id": 516,
  "extra": {
    "title": "Analysis 3",
    "path": "02_Analysis_and_Operator_Theory/00_Calculus_and_Undergraduate_Analysis/Analysis 3.pdf"
  }
}
```

---

## 3. AI Service Schemas (JSON)

### 3.1 Universal Processor Output
Schema for holistic book analysis (`services/universal_processor.py`).

```json
{
  "metadata": {
    "title": "string",
    "author": "string",
    "publisher": "string",
    "year": 2024,
    "isbn": "string",
    "doi": "string",
    "msc_class": "string",
    "target_path": "string",
    "summary": "string",
    "description": "string",
    "audience": "string",
    "has_exercises": true,
    "has_solutions": false
  },
  "toc": [
    {
      "title": "Introduction",
      "page": 1,
      "level": 0
    }
  ],
  "index_terms": ["Keyword 1", "Keyword 2"],
  "page_offset": 0
}
```

### 3.2 Note Transcription Output
Schema for handwritten or PDF transcription (`services/note.py`).

```json
{
  "latex_source": "string",
  "markdown_source": "string",
  "title": "string",
  "tags": "string",
  "msc": "string"
}
```

---

## 4. Classification Scheme: `msc2020.json`

The Mathematical Subject Classification (MSC) hierarchy.

```json
{
  "00": {
    "title": "General and overarching topics",
    "children": {
      "00A": {
        "title": "General and miscellaneous specific topics",
        "children": {
          "00A05": "General mathematics"
        }
      }
    }
  }
}
```

---

## 5. LLM Task Payloads

### 5.1 `extract_page_mlx`
Task for local MLX-based OCR and extraction.

```json
{
  "book_id": 123,
  "page_number": 45,
  "mode": "test|prod"
}
```
