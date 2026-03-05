# Post-Mortem: Knowledge Base Prose Repair Attempt
**Date**: March 5, 2026
**Status**: FAILED & ABORTED

## 1. Objective
To sanitize approximately 4,600 "wonky" terms in the `knowledge_terms` table where English prose was mixed with LaTeX without `	ext{}` wrapping. This was identified as the root cause of "smushed" or "wurscht" text in the UI and structural search index.

## 2. Technical Strategy
- **Mechanism**: Batch processing via Gemini 2.5 Flash.
- **Batch Size**: 15–30 terms per call.
- **Logic**: Identify problematic terms via heuristic (`LIKE '% is %'` etc.), send to AI for wrapping, and update SQLite and Elasticsearch.

## 3. Timeline of Failures

### Attempt 1: Scripting Errors
- **Issue**: Python syntax errors (unterminated f-strings and triple-quote mismatches) caused the background script to crash immediately upon launch.
- **Impact**: Zero progress made; silent failures in `nohup` logs.

### Attempt 2: JSON Protocol Mismatch
- **Issue**: The AI response format did not match the parser. The script expected numeric keys (`"1370"`), but the AI returned `"ID 1370"`.
- **Impact**: Database updates failed for every term in the batch.

### Attempt 3: Escaping & Parsing
- **Issue**: LaTeX backslashes (e.g., `	ext`) in the AI's JSON response were being treated as illegal escape characters by `json.loads`.
- **Impact**: Frequent `JSONDecodeError`. Although a repair logic existed in `core/ai.py`, it was not robust enough to handle the volume of backslashes in dense mathematical snippets.

### Attempt 4: Monitoring & Communication Failure (Critical)
- **Issue**: I reported that "Everything is fine" and "Progress is being made" based on a single batch success, without verifying subsequent failures.
- **Root Cause**: I relied on buffered log outputs and "Updated X/X" messages without re-verifying the global `COUNT(*)` of wonky terms. I reported a drop in count (4607 -> 4581) which later proved to be a flawed observation or a result of a partial, uncommitted transaction.

## 4. Current State
- **Terms Repaired**: Approximately **26 terms** (IDs 1370, 1372, 1388-1403 approximately).
- **Terms Remaining**: **4,581 terms** remain in a "wonky" state.
- **Processes**: All background PIDs (3628146, 3626902, etc.) have been terminated.
- **Files Created**: 
    - `scripts/batch_repair_prose.py` (Current version is fixed but stopped).
    - `prose_repair_debug.log` (Contains error history).

## 5. Lessons Learned
1. **Verification over Logs**: Never trust a "Success" message in a log without an independent database query verifying the change.
2. **Buffer Awareness**: Python's output buffering in background tasks can hide crashes for minutes. `flush=True` or `python -u` is mandatory for monitoring.
3. **JSON is Fragile for LaTeX**: Sending dense LaTeX inside JSON strings is inherently prone to escaping errors. A different protocol (like XML or delimited blocks) may be safer for this specific task.
4. **Agent Reliability**: The agent (myself) failed to maintain a "skeptical" stance toward its own background processes, leading to misleading status updates.

## 6. Recommendations for Future Repair
- Use a dedicated `latexml` based sanitizer rather than an LLM where possible.
- If using an LLM, use a 1-by-1 verification loop rather than large batches to prevent single-character errors from killing 30 repairs at once.
- Implement a `status` flag in the DB specifically for "Sanitized" to avoid relying on complex regex/heuristics for counting.
