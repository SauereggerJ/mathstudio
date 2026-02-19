# MathStudio: Universal Vision-Reflection Pipeline (Technical Manual)

## 1. System-Architektur (v2.0)
MathStudio nutzt eine vereinheitlichte Pipeline für Ingestion, Metadaten-Refresh und Bibliografie-Extraktion. Das System folgt dem Prinzip **"Vision-First, Deterministic Verification, LLM Reflection"**.

### 1.1 Kern-Komponenten
- **Processor:** `UniversalProcessor` (Orchestriert den 7-Phasen-Ablauf).
- **Vision:** Gemini 2.0 Flash (Verarbeitung via PDF-Slices und File API).
- **I/O:** `PDFHandler` (Speicherschonendes Slicing, DjVu-Support).
- **Verification:** `ZBMathService` (Crossref Polite Pool, DOI-Master Resolution).

---

## 2. Die 7-Phasen-Pipeline (Detail-Flow)

### Phase 0.5: Local Heuristic Analysis
**Funktion:** `estimate_slicing_ranges()` in `core/utils.py`.
- Scannt das Dokument multilingual (DE/EN/FR) nach TOC- und Bibliografie-Markern.
- Bestimmt dynamisch die relevanten Seitenbereiche (Vorne ca. 20, Hinten ab erstem Bib-Marker).

### Phase 1 & 2: Skeleton Slicing & Cloud-Upload
**Funktion:** `create_slice()` und `ai.upload_file()`.
- Erstellt physische PDF-Teilstücke auf `/tmp`.
- Lädt Slices sequenziell zur Gemini File API hoch (kein Base64 im RAM).

### Phase 3: Initial Holistic Pass
Extrahiert Metadaten (Titel, Autor, DOI, ISBN, MSC) und das TOC.
**Prompt:** "Analyze the provided PDF (title pages/ToC). Extract metadata and TOC. Return JSON..."

### Phase 3.5: Vision-First Chunking (Bibliography)
Zerschneidet große Bibliografien in Chunks von **10 Seiten**.
- Verarbeitet jeden Chunk sequenziell als PDF-Bild.
- **Vorteil:** Umgeht das 8k-Output-Limit von Gemini und bewahrt mathematische Notation.

### Phase 4: Deterministic Verification (Cross-Check)
Gleicht KI-Daten gegen Crossref ab.
- **DOI-Upgrade:** Wandelt Kapitel-DOIs (`book-chapter`) automatisch in Buch-DOIs um.

### Phase 5: Reflection-Loop (Konfliktauflösung)
Trigger bei Widerspruch (z.B. Titel vs. Dateiname).
- Zweiter KI-Pass mit explizitem Konflikt-Kontext zur finalen Wahrheitsfindung.

### Phase 6: Transactional Persistence
Schreibt Daten atomar in `books`, `chapters` und `bib_entries`.

---

## 3. Speichermanagement (OOM-Prävention)
- **Disk-Buffering:** PDF-Slices werden niemals im RAM gehalten.
- **Explicit Cleanup:** `del doc`, `gc.collect()` und `ai.delete_file()` nach jedem Chunk.
- **Atomic Handles:** Jede Phase öffnet und schließt das PDF-Handle unabhängig.

---
*Status: Produktion / Stand: 19. Februar 2026*
