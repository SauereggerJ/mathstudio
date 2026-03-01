# Knowledge Extraction Master Blueprint

This document defines the strict data model and quality standards for the MathStudio digitization pipeline.

---

## 1. The "Absolute PDF Page" House Rule
All components of the system must communicate using **1-indexed absolute PDF page numbers**. 
- **Physical Reality**: If a book has 20 pages of Roman numeral preface, the first page of "Chapter 1" is PDF Page 21. 
- **Storage**: We store it as `page_21.tex`.
- **Reference**: The database links all terms to `page_21`.
- **Translation**: `page_offset` is used *only* to help the user find a PDF page if they only know the printed number.

---

## 2. Data Association Model

### 2.1 The Registry (`extracted_pages`)
Every time a page is digitized, it is registered. This allows the system to know which parts of a book are "complete."
- **Path**: `converted_notes/{book_id}/page_{N}.tex`
- **Metadata**: Stores the `quality_score` and `harvested_at` (to track if terms were extracted).

### 2.2 The Fact Index (`knowledge_terms`)
Atomic mathematical entities discovered on pages.
- **Link**: Associated with the Registry via `(book_id, page_start)`.
- **Content**: Stores a standalone `latex_content` snippet so the term can be read without opening the full page.
- **Markers**: Uses `start_marker` and `end_marker` (text strings) to identify the segment within the Registry file.

---

## 3. Validation Guardrails (Checks & Rechecks)

To ensure the Knowledge Base doesn't become "wonky," every extraction must pass four gates:

### Gate 1: Structural Integrity (Linting)
- **Mechanism**: Fast Regex scan.
- **Check**: Mismatched LaTeX environments (`\begin` vs `\end`) or curly braces.
- **Action**: Failure triggers an immediate AI Repair pass.

### Gate 2: Mathematical Validity (Compilation)
- **Mechanism**: `subprocess.run(['pdflatex', ...])`
- **Check**: Compiles a snippet in a temporary buffer.
- **Action**: Rejects snippets that would break a PDF viewer.

### Gate 3: The Active Repair Loop
- **Mechanism**: Reflection pass via Gemini.
- **Check**: If Gate 1 or 2 fails, the AI analyzes the **compiler error log** and the **raw text** to regenerate the LaTeX.
- **Action**: If repair fails, the system falls back to raw OCR text to prevent data loss, but marks the quality as 0.0.

### Gate 4: Semantic Deduplication
- **Mechanism**: RapidFuzz (String Similarity).
- **Check**: Compares new terms against existing terms in a ±1 page window.
- **Action**: If >85% similar, the discovery is discarded as a duplicate.

---

## 4. Technical Strategy: Markers vs. Line Numbers
MathStudio uses **Textual Markers** for segmenting pages.
- **Why?** LaTeX line numbers change if a header is added or spacing is adjusted.
- **Reliability**: A marker like "Theorem 4.2" is unique and persistent.
- **Fuzzy Matching**: We use fuzzy logic to find markers, ensuring that "Definition 1" still matches even if the OCR read it as "Definiton 1."
