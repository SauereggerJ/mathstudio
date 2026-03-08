# Mathematical Brain: Project Status & Handoff

**Date**: 2026-03-05 (End of Day Handoff)
**Active Pipelines (Running in Background via nohup)**:
1. **[DONE] Wikipedia Scraper** (`batch_ingest_wiki.sh`): Scraped 12 glossaries into `mathematical_concepts` (Target: ~2,141 rows). **Script finished successfully.**
2. **[RUNNING] DB Prose Repair** (`batch_repair_prose.py`): DeepSeek XML-block semantic repair running on the 4,545 broken terms in `knowledge_terms`. Expected to finish in ~8 hours.

## Architectural Decisions Made Today
We pivoted from the "Visual Harvester" and "Ghost Graph" ideas to focus entirely on **Canonical Anchoring (The Mathematical Brain)**. 
- The schema for `mathematical_concepts` was created. It contains `name`, `subject_area`, `summary`, and `embedding` fields.
- We solved the **Name Collision Trap** (e.g., "Normal" in Topology vs. Algebra) by enforcing a `UNIQUE(name, subject_area)` constraint.
- Embeddings will inject `subject_area` into the text payload so that Vector Searches map Book Context -> Concept Context naturally.

## Roadmap for Tomorrow (Next Immediate Steps)

### Step 1: Batch Embeddings Generation
We need to generate 768-dim semantic float arrays for:
1. The ~2,141 new Canonical Concepts (Target Vectors). *Format: `[Name] {name} [Subject] {subject} [Summary] {summary}`*
2. The ~4,500+ repaired Knowledge Terms (Query Vectors). *Format: `[Term] {name} [Book Subject] {msc} [LaTeX Context] {latex_content}`*

**How to Execute**: Write a `scripts/batch_embed_kb.py` script using the existing `models/gemini-embedding-001` via `core.ai`. It is completely free and should take ~4 minutes to process all rows.

### Step 2: Tier A (Vector Matcher) Implementation
Update the codebase so that when a new term is extracted the system:
1. Computes the Query Vector.
2. Queries the Elasticsearch `mathstudio_concepts` index (which we will need to create/schema map) using kNN.
3. Retrieves the top 5 closest Anchors.

### Step 3: Tier B (DeepSeek Librarian)
Create the system prompt that feeds the extracted snippet to DeepSeek alongside the Top 5 candidates from Tier A, forcing it to either select a candidate ID or return `CREATE NEW`.

### Step 4: The Fallback (MathStudio-Native Anchoring)
If DeepSeek returns `CREATE NEW`, generate a new Canonical Concept derived purely from the book's definition snippet, embed it, and save it to `mathematical_concepts` as a `mathstudio_native` source.
