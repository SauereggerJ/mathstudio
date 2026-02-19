# MathStudio: Exhaustive Technical Reference Manual (Developer Edition)

## 1. System Environment & Core Specs
- **OS:** Linux (Debian 13 Container)
- **Language:** Python 3.11.14
- **Database:** SQLite 3.46.1 (Enabled: WAL Mode, Foreign Keys, FTS5, JSONB)
- **OCR/PDF:** PyMuPDF (fitz) 1.27.1
- **AI Core:** Gemini 2.0 Flash (SDK: `google-genai`)

---

## 2. Complete Database Schema (DDL)

All tables use `STRICT` mode for data integrity.

### 2.1 The `books` Table
Main repository for verified document data.
```sql
CREATE TABLE books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,      -- Relativer Pfad ab /library
    directory TEXT,                 -- Übergeordneter Ordner
    author TEXT,
    title TEXT,
    size_bytes INTEGER,
    isbn TEXT,
    publisher TEXT,
    year INTEGER,
    description TEXT,               -- Langer Beschreibungstext (oft zbMATH Review)
    last_modified REAL,
    arxiv_id TEXT,                  -- Platzhalter für zbMATH Zbl-ID
    doi TEXT UNIQUE,                -- Globaler Primärschlüssel (Anchor)
    index_text TEXT,                -- Roher Textlayer für die Suche
    summary TEXT,                   -- Kurze KI-Zusammenfassung
    level TEXT,                     -- z.B. 'Bachelor', 'Graduate'
    audience TEXT,                  -- Zielgruppe
    has_exercises INTEGER,          -- 0 oder 1
    has_solutions INTEGER,          -- 0 oder 1
    page_count INTEGER,
    toc_json TEXT,                  -- JSON-Dump des Inhaltsverzeichnisses
    msc_class TEXT,                 -- Grobe MSC Klasse
    msc_code TEXT,                  -- Exakter MSC Code (z.B. 14A05)
    tags TEXT,
    embedding BLOB,                 -- Vektor-Daten (768-dim)
    file_hash TEXT,                 -- SHA-256 Fingerabdruck
    index_version INTEGER,
    reference_url TEXT
) STRICT;
```

### 2.2 The `bib_entries` Table
Tracks every single citation found in any document.
```sql
CREATE TABLE bib_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL,       -- Verweis auf Quelle (books.id)
    raw_text TEXT NOT NULL,         -- Unveränderter String aus PDF
    title TEXT,                     -- Extrahiert via Gemini
    author TEXT,                    -- Extrahiert via Gemini
    extracted_at INTEGER DEFAULT (unixepoch()),
    resolved_zbl_id TEXT,           -- Verknüpfte DOI oder Zbl-ID
    confidence REAL,                -- 1.0 (Match), 0.0 (Missing), -1.0 (Failed)
    FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
) STRICT;
```

---

## 3. The Bibliography Engine (Deep Dive)

### 3.1 Call Sequence: `Scan Bibliography`
1.  **UI:** `scanBibliography()` -> `fetch('/api/v1/tools/bib-scan')`.
2.  **API (`api_v1.py`):** `bib_scan_tool(book_id)` -> `bibliography_service.scan_book(book_id)`.
3.  **Discovery (`bibliography.py`):** `find_bib_pages(book_path)`.
    - **MuPDF Logic:** Öffnet `fitz.open(path)`, iteriert von hinten (max. 60 Seiten).
    - **Keywords:** Sucht nach "Bibliography", "References" etc.
4.  **Extraction (`bibliography.py`):** `extract_and_structure_page(abs_path, page_num)`.
    - **Gemini Prompt:**
      > "You are a bibliography expert. Extract all bibliography entries from the following text. For each entry, create a JSON object with: 'title', 'author', 'year', and 'raw_text' (verbatim). Return a JSON array of these objects."
    - **Action:** Schickt den kompletten Textlayer der Seite an Gemini.
5.  **Persistence:** Schreibt Rohdaten sofort in `bib_entries`.
6.  **Enrichment (`app.py` / `zbmath.py`):** `enrichment_worker` -> `resolve_citation(raw_text)`.
    - **Crossref Query:** `GET api.crossref.org/works?query.bibliographic=<text>&rows=1`.
    - **Identity Logic:** Wenn DOI gefunden, Abgleich gegen `books.doi`.

### 3.2 Key Source Code: `extract_and_structure_page`
```python
def extract_and_structure_page(self, pdf_path: Path, page_num: int):
    doc = fitz.open(str(pdf_path))
    text = doc[page_num - 1].get_text() # MuPDF Standard Extraction
    doc.close()
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}], # Siehe Prompt oben
        "generationConfig": {"responseMimeType": "application/json"}
    }
    res = requests.post(url, json=payload, timeout=60)
    return json.loads(res.json()['candidates'][0]['content']['parts'][0]['text'])
```

---

## 4. The AI Re-Indexing Engine (Deep Dive)

### 4.1 Call Sequence: `AI Re-Index`
1.  **UI:** `reindexBook()` -> `fetch('/api/v1/books/<id>/reindex/preview')`.
2.  **Analysis (`ingestor.py`):** `extract_structure(file_path)`.
    - **Heuristik:** Prüft die ersten 50 Seiten. Wenn Textdichte < 200 Zeichen, springe zur nächsten Seite.
    - **Vision Trigger:** Wenn kein Text gefunden wird, setze Status `[SCANNED DOCUMENT]`.
3.  **KI-Analyse (`ingestor.py`):** `analyze_book_content()`.
    - **Vision Path:** Rendert erste 3 Seiten (`pix.tobytes("jpeg")`), sendet an Gemini Vision.
    - **Text Path:** Sendet die ersten 20 Seiten Text.
4.  **Verification:** UI zeigt Diff-View.
5.  **Apply:** `update_metadata()` schreibt finale Felder in `books` und triggert `sync_chapters()`.

---

## 5. Metadata Unification & Resolution

### 5.1 The DOI Bridge (`services/zbmath.py`)
Die Architektur nutzt Crossref als "Resolver", um die DOI zu finden, und OpenAlex/zbMATH-OAI als "Bridge", um zur Zbl-ID zu kommen.

```python
def resolve_citation(self, raw_string: str):
    # Noise Removal via Regex
    clean_query = re.sub(r'^\[\d+\]\s*', '', raw_string)
    clean_query = re.sub(r'p\.\s*\d+.*$', '', clean_query).strip()
    
    # Polite Pool Call
    headers = {"User-Agent": "MathStudio/1.0 (mailto:admin@mathstudio.local)"}
    resp = self.session.get(self.CROSSREF_URL, params={"query.bibliographic": clean_query, "rows": 1}, headers=headers)
    
    # DOI Extraction & Score Check
    if resp.status_code == 200:
        item = resp.json()['message']['items'][0]
        return {'doi': item.get('DOI'), 'title': item.get('title')[0]}
```

---

## 6. Background Workers & Periodic Tasks

### 6.1 Housekeeping (`app.py`)
Läuft alle 12 Stunden im `enrichment_worker` Thread.
- **Wunschlisten-Synchronisation:**
  `SELECT w.doi FROM wishlist w JOIN books b ON w.doi = b.doi WHERE w.status = 'missing'`
- **Aktion:** Setzt `status = 'acquired'`, wenn DOI physisch vorhanden.

---
*Dokumentation Version: 1.5.0 / Entwickler-Referenz / Date: 2026-02-19*
