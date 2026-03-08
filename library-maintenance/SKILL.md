---
name: library-maintenance
description: Specialist for MathStudio library health, auditing ingestion hiccups, repairing failed LaTeX conversions, and recovering placeholder terms. Use when a book ingestion is complete or when search results return 'wonky' or placeholder LaTeX content.
---

# Library Maintenance Specialist

This skill provides a rigorous workflow for maintaining the technical integrity of the MathStudio knowledge base.

## Core Maintenance Workflows

### 1. The Post-Ingestion Audit
Always perform an audit after a book has been deep-indexed to identify "hiccups" (failures that didn't stop the process but left gaps).

**Procedure:**
1. Run the audit script: `python3 scripts/audit_book.py <book_id>`
2. Analyze the "RECENT ERRORS" section.
3. Check the "LaTeX Cached" percentage. If < 95%, investigate `app.log` for compilation errors.

### 2. Deep Recovery of Placeholders
If the audit shows a high percentage of "Placeholders (Fixable)", run the Deep Recovery service.

**Procedure:**
1. Run recovery: `docker exec mathstudio python3 scripts/deep_recovery.py <book_id>`
2. Review the number of recovered terms.
3. If recovery is successful, synchronize the new content to Elasticsearch:
   `docker exec mathstudio python3 scripts/fix_missing_terms_es.py`

### 3. Repairing 'Wonky' Terms
If a user reports a specific term has bad LaTeX (e.g., cuts off, starts mid-sentence), follow this repair chain:

1. **Verify Location:** Check if the `page_start` in `knowledge_terms` is correct by checking the PDF or raw text.
2. **Force Re-conversion:** If the page was missing or poor quality, force a re-conversion:
   `docker exec mathstudio python3 -c "from services.note import note_service; note_service.get_or_convert_pages(<book_id>, [<page_num>], force_refresh=True, min_quality=0.1)"`
3. **Manual Marker Sync:** If automatic recovery fails, use a manual script (like `scripts/repair_1975.py`) to join adjacent pages or adjust markers.

## Error Categories & Diagnostics

- `latex_compilation`: The page failed strict LaTeX linting or `pdflatex` checks. 
  - *Fix:* Check `app.log` for missing packages or malformed math. Use "Active Repair" via the `NoteService`.
- `marker_not_found`: The AI provided a start_marker that doesn't exist in the LaTeX.
  - *Fix:* Run `scripts/deep_recovery.py`. It uses ultra-aggressive normalization to find markers across line breaks and noise.
- `schema_violation`: The AI returned a non-standard category (e.g., 'section_title').
  - *Fix:* Handled automatically by the updated `TERM_EXTRACTION_SCHEMA`, but check for existing junk using `SELECT term_type FROM knowledge_terms GROUP BY term_type;`.

## Performance Limits
- Search: 250 results (Max)
- Browse: 500 results (Max)
- Multi-page Snippets: Max 2 pages look-ahead for `end_marker`.
