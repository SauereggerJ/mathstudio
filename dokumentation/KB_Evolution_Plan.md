# MathStudio: Knowledge Base Evolution Plan (The "New Era" Strategy)

This document outlines the strategic roadmap for transforming the MathStudio Knowledge Base from a flat repository of snippets into a structured, high-precision mathematical engine.

## Status Quo (The "Rising Sea" Problem)
- **Current Data:** ~4,600 terms from ~4 books.
- **Projected Data:** 100,000+ terms as the full library is scanned.
- **Challenge:** Avoid informational noise. A search for "Limit" cannot return 800 results. We must organize by *concept*, not just by *occurrence*.

---

## Project 1: The Mathematical Brain (Hierarchy & Anchoring)
**Priority: HIGH (To be started immediately)**

### 1.1 Canonical Anchoring (The "Fixed Shelves" Strategy)
To prevent the AI from hallucinating names or notation, we move from "authoring" to "matching."
- **Reference Ingestion:** Import a canonical list of mathematical concept titles (Source: Wikipedia Mathematics categories, Wolfram MathWorld, or PlanetMath).
- **The Concept Layer:** Create a `mathematical_concepts` table. Every term extracted from a book must be "anchored" to one of these IDs.
- **Automated Mapping:**
    - **Tier A (Vector Match):** Use semantic embeddings to find the top 5 most likely canonical anchors for a new term.
    - **Tier B (Librarian Pass):** Use Gemini Flash to select the correct anchor from the 5 candidates based on the LaTeX content.
- **Benefit:** 100 books defining "Heine-Cantor" will result in **1 Search Hit** (The Concept), which then expands to show all 100 verbatim variants.

### 1.2 The Knowledge Pyramid
1. **Topic Islands (Macro):** Automated clustering of concepts into fields (e.g., "Measure Theory", "Complex Analysis").
2. **Canonical Concepts (Meso):** The "Anchors" (e.g., "Uniform Continuity").
3. **Verbatim Terms (Micro):** The specific, original LaTeX snippets from Zorich, Amann, etc.

### 1.3 The Dual-Layer Relation Graph
- **Curated Links (Gold):** Explicit relations created manually by the user during research. These are "Absolute Truth."
- **Ghost Links (AI):** Suggested relations based on term similarity. Users can "promote" these to Gold.

---

## Project 2: The Visual Harvester (Diagrams & Linking)
**Priority: SECONDARY (Follows Project 1)**

### 2.1 Local Extraction Pipeline
- **Heuristic Detection:** Use PyMuPDF and OpenCV to isolate non-text regions (blobs) on a page.
- **Caption Matching:** OCR the area immediately below/above a blob to find "Figure X.Y" labels.
- **Local Cleanup:** Apply adaptive thresholding and sharpening to raw crops to ensure high-quality, transparent-background PNGs suitable for modern UI display.

### 2.2 Relational Association
- **Strong Association:** Links created when a diagram falls within the bounding box of a specific theorem or when the LaTeX text explicitly references the caption.
- **Weak Association:** "Found on same page" tab for images that cannot be precisely pinned to a term.

---

## Implementation Milestones (Tomorrow's Goals)
1. **Define Schema** for `mathematical_concepts` and `concept_links`.
2. **Ingest Initial Anchor List** (Wikipedia/MathWorld titles).
3. **Draft the "Anchoring Script"** to begin mapping existing terms.
4. **Update Search UI** to support the Concept -> Term hierarchy.

---
*Plan formulated during the planning session on 2026-03-04. No code changes implemented.*
