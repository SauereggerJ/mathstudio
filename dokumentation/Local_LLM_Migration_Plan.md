# System Architecture Update: MathStudio Local LLM Migration

**Objective:** Replace the synchronous Gemini API integration in MathStudio with an asynchronous, trickle-feed architecture utilizing a dedicated Apple Silicon M2 Mac (16GB RAM) as a headless inference node on the `192.168.178.*` subnet.

---

## Phase 1: M2 Inference Node Setup (Stateless API)
The Mac operates purely as a stateless Vision-Language/Reasoning server.

- **Framework:** Deploy the `mlx-vlm` package to leverage native Metal Performance Shaders for memory efficiency.
- **Network Binding:** Bind the server to `0.0.0.0` to ensure accessibility from the Intel host at `192.168.178.2`.
- **Vision Model:** Load `Qwen2.5-VL-7B` quantized to 4-bit (`Q4_K_M`) for the initial PDF-to-LaTeX pass. This requires approximately 4.5 GB of RAM, leaving sufficient overhead for the OS.
- **Reasoning Model:** For text-only semantic extraction, utilize `DeepSeek-R1-Distill-14B` (`Q4_K_S`), which occupies ~8.5 GB of RAM and is optimized for mathematical logic verification. The `mlx-vlm` server's `/unload` endpoint must be used to swap models in memory when transitioning from vision tasks to reasoning tasks.

## Phase 2: MathStudio Orchestration & Queue Management (Intel Server)
MathStudio (`192.168.178.2`) handles all state, validation, and multi-page logic.

- **Task Queue:** Repurpose the existing `llm_tasks` table to act as the asynchronous trickle-feed queue.
- **Decoupling:** Rewrite `core/ai.py` to strip out the `google-generativeai` SDK. Implement a standard HTTP client that POSTs base64-encoded images or text payloads to the Mac's API endpoints. Keep the Gemini implementation as a configurable fallback.
- **Page Slicing:** Use the existing `PDFHandler` (`core/utils.py`) to isolate single pages.

## Phase 3: Vision Pipeline (PDF Page to Raw LaTeX)
This phase transforms visual data into raw, structured text.

- **Trickle-Feed Execution:** The background worker pulls one task from `llm_tasks`, extracts a single page, and sends it to the `Qwen2.5-VL` model on the Mac.
- **Quality Gating:** MathStudio receives the raw LaTeX and performs deterministic structural checks (e.g., matching `\begin{...}` and `\end{...}` tags).
- **Retry Logic:** If validation fails, the task status in `llm_tasks` is updated to retry. The subsequent request to the Mac should dynamically adjust the generation temperature to force a different stochastic output path.
- **Storage:** Successful conversions are saved to the `extracted_pages` cache.

## Phase 4: Semantic Extraction Pipeline (Raw LaTeX to Knowledge Base)
This phase converts structured text into formal Knowledge Base entities.

- **Multi-Page Stitching:** MathStudio queries the `extracted_pages` cache to retrieve consecutive validated LaTeX pages, concatenating them to form a complete logical context (e.g., a full proof).
- **RAG Context Injection:** Before requesting extraction, MathStudio queries the `concept_fts` virtual table to find existing mathematical concepts related to the stitched text.
- **Guided Decoding:** MathStudio sends the stitched LaTeX, the list of existing KB titles, and a strict JSON schema via the LangExtract methodology to the DeepSeek reasoning model on the Mac. The prompt explicitly instructs the model to reuse existing titles if a match occurs.
- **Proposal Staging:** The Mac returns structured JSON containing definitions, theorems, and lemmas. MathStudio inserts these into the `kb_proposals` table, maintaining the status as `pending`.

## Phase 5: UI Integration
The web frontend (`knowledge/` templates) reads from `kb_proposals`.

- The user reviews the generated proposals from their LMDE machine (`192.168.178.30`), triggering a merge into the `concepts` and `entries` tables upon approval.
