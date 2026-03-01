#!/usr/bin/env python3
"""
MathStudio MCP Server

Provides LLM access to the MathStudio Research Library:
 - Library search and discovery
 - PDF-to-LaTeX conversion pipeline (for deep research)
 - Knowledge Base browsing (approved theorems/definitions)
 - Note creation and management (handwritten + LLM-authored)
"""

import json
import logging
from pathlib import Path
from typing import Any

import requests
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
    Resource,
    Prompt,
    PromptMessage,
    GetPromptResult,
)

LOG_FILE = Path(__file__).parent / "mcp.log"

# Write to file + stderr so we can tail the log without disrupting stdio protocol
_file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
_file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
_stderr_handler = logging.StreamHandler()
_stderr_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

logging.basicConfig(level=logging.DEBUG, handlers=[_file_handler, _stderr_handler])
logger = logging.getLogger("mathstudio-mcp")
logger.info(f"=== MCP Server starting. Log: {LOG_FILE} ===")

CONFIG_PATH = Path(__file__).parent / "config.json"
with open(CONFIG_PATH) as f:
    config = json.load(f)

API_BASE = config["api_base_url"]
SERVER_NAME = config["server_name"]
SERVER_VERSION = config["server_version"]

app = Server(SERVER_NAME)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

@app.list_prompts()
async def list_prompts() -> list[Prompt]:
    return [
        Prompt(
            name="usage_manifesto",
            description="Core guidelines for using the MathStudio library. Read this first.",
            arguments=[]
        ),
        Prompt(
            name="deep_research_workflow",
            description="Multi-source research protocol: find → convert → synthesise → store.",
            arguments=[
                {"name": "topic", "description": "Mathematical topic to research", "required": True}
            ]
        ),
        Prompt(
            name="note_writing_workflow",
            description="Full workflow for writing and storing a scholarly note on a mathematical topic.",
            arguments=[
                {"name": "request", "description": "What the user wants the note to cover", "required": True}
            ]
        ),
    ]


@app.get_prompt()
async def get_prompt(name: str, arguments: dict | None) -> GetPromptResult:
    args = arguments or {}

    if name == "usage_manifesto":
        return GetPromptResult(
            description="MathStudio Usage Manifesto",
            messages=[PromptMessage(role="user", content=TextContent(type="text", text="""\
You are an Agentic Research Assistant for the MathStudio Mathematical Library.

## YOUR MISSION
Answer mathematical questions by extracting knowledge directly from primary sources in the library. Never guess or hallucinate; always cite actual book pages.

## CORE TOOLS (in preferred order of use)
1. **search_knowledge_base** — Search approved KB terms (theorems, definitions). This is the fastest path.
2. **search_books** — Find relevant books across the library.
3. **search_within_book** — Find the exact page where a concept appears.
4. **get_book_pages_latex** — Convert pages to high-quality LaTeX. This caches results for reuse.
5. **read_pdf_pages** — Cheap page peek to verify page offsets (printed vs. PDF page numbers).

## THE RESEARCH IMPERATIVE
**Never settle for the first result.** When researching a topic:
- Search for it in MULTIPLE books (at least 2-3 if available).
- Quote from each source, noting similarities and differences in approach.
- Only then synthesise a conclusion.

## PDF PAGE OFFSETS
The printed page number (e.g., "Page 10") is NEVER the same as the PDF page index (often +12 due to prefaces). Use `read_pdf_pages` to peek at a page, read its printed number, calculate the offset, and jump to the correct PDF page. Do this at most 2 times before proceeding.

## CRITICAL RULES
- Never run `get_book_pages_latex` on Table of Contents or Index pages.
- After converting pages, always summarise what you found and ask the user if they want the result stored as a note.
"""))]
        )

    if name == "deep_research_workflow":
        topic = args.get("topic", "the requested topic")
        return GetPromptResult(
            description=f"Deep research protocol for: {topic}",
            messages=[PromptMessage(role="user", content=TextContent(type="text", text=f"""\
I need a deep, multi-source research session on: **{topic}**

Follow this protocol strictly:

### PHASE 1: KNOWLEDGE BASE FIRST
- Call `search_knowledge_base` with the topic.
- If good results exist, present them. Note which books they come from.

### PHASE 2: FULL LIBRARY SEARCH
- Call `search_books` to find all relevant books (aim for 3+ sources).
- For each book found, call `search_within_book` to find the exact pages that discuss {topic}.
- Call `get_book_details` to check if the book has a back-of-book index; if so, it might have more precise page numbers.

### PHASE 3: PDF EXTRACTION (Required — do not skip)
- For each relevant source (at least 2 books), call `get_book_pages_latex` to extract the actual content.
- First use `read_pdf_pages` to verify the page offset if the page numbers seem off.
- Present the extracted LaTeX/content from each source.

### PHASE 4: SYNTHESIS
- Synthesise the findings across all sources.
- Note how different authors approach the topic differently.
- Identify the most rigorous (or most accessible) treatment.

### PHASE 5: OFFER TO STORE
- Ask: "Would you like me to write this up as a permanent research note?"
- If yes, follow the `note_writing_workflow`.
"""))]
        )

    if name == "note_writing_workflow":
        request = args.get("request", "a mathematical topic")
        return GetPromptResult(
            description=f"Note writing workflow for: {request}",
            messages=[PromptMessage(role="user", content=TextContent(type="text", text=f"""\
I want you to write a high-quality research note about: **{request}**

### PHASE 1: RESEARCH (Required before writing anything)
1. Use `search_knowledge_base` to find pre-indexed terms.
2. Use `search_books` and `search_within_book` to locate primary sources in the library.
3. Use `get_book_pages_latex` on the relevant pages — **minimum 2 books, ideally 3**.
4. Present a brief summary of what you found and where.

### PHASE 2: DRAFT PROPOSAL
Stop and present a draft to me:
- **Title**: Descriptive, not just "Definition 2.3"
- **Structure**: What sections the note will have
- **Sources**: Which books / pages will be cited
- **Content preview**: A few key statements in LaTeX

Wait for my approval before continuing.

### PHASE 3: CREATE THE NOTE (After approval only)
Once I approve:
1. Call `create_note` with:
   - A polished `title`
   - Full `markdown` content (well-structured, with LaTeX for math using `$...$`)
   - Full `latex` content (proper LaTeX document, ready to compile)
   - `tags`: comma-separated keywords
2. Call `add_note_book_relation` to link the note to each source book with the correct page.
3. Call `compile_note` to generate the PDF.
4. Confirm the Note ID and all three formats (MD, LaTeX, PDF) are ready.

IMPORTANT: The note should be a permanent, scholarly artifact — not a quick summary.
"""))]
        )

    raise ValueError(f"Unknown prompt: {name}")


# ---------------------------------------------------------------------------
# Tool Definitions
# ---------------------------------------------------------------------------

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [

        # ── LIBRARY SEARCH & DISCOVERY ──────────────────────────────────────

        Tool(
            name="search_books",
            description=(
                "Search the mathematical library using hybrid vector + full-text search. "
                "Returns books with metadata and relevance scores. "
                "Always search with multiple queries to find all relevant sources before extracting content."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query (e.g., 'Banach spaces', 'Riemann integral')"},
                    "limit": {"type": "integer", "default": 10},
                    "use_fts": {"type": "boolean", "default": True},
                    "use_vector": {"type": "boolean", "default": True},
                    "field": {"type": "string", "enum": ["all", "title", "author", "index"], "default": "all"}
                },
                "required": ["query"]
            }
        ),

        Tool(
            name="get_book_details",
            description=(
                "Retrieve comprehensive metadata for a specific book, including page count, "
                "summary, MSC classification, and indexing status. "
                "Always call this before extracting pages — it tells you if a deep index is available "
                "and the page offset needed to find the correct PDF page."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer", "description": "Book ID from search results"}
                },
                "required": ["book_id"]
            }
        ),

        Tool(
            name="get_book_toc",
            description=(
                "Retrieve the structured Table of Contents for a book. "
                "Use this to understand which chapter covers a topic and its logical page range."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer"}
                },
                "required": ["book_id"]
            }
        ),

        Tool(
            name="search_within_book",
            description=(
                "Search for a term or phrase within a specific book's pages. "
                "Returns page numbers and snippets. Run `deep_index_book` first for best results."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer"},
                    "query": {"type": "string", "description": "Term or phrase to find (e.g., 'Cauchy sequence', 'Hahn-Banach')"}
                },
                "required": ["book_id", "query"]
            }
        ),

        Tool(
            name="deep_index_book",
            description=(
                "Enable page-level full-text search for a book. "
                "Call this once per book before using `search_within_book` for accurate results."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer"}
                },
                "required": ["book_id"]
            }
        ),

        Tool(
            name="reindex_book",
            description=(
                "Rebuild a book's Table of Contents or back-of-book Index using AI. "
                "Use when `get_book_details` shows TOC or Index is missing.\n"
                "Modes: 'toc' | 'index' | 'auto' (both)"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer"},
                    "mode": {"type": "string", "enum": ["toc", "index", "auto"], "default": "auto"}
                },
                "required": ["book_id"]
            }
        ),

        # ── PDF CONTENT EXTRACTION ───────────────────────────────────────────

        Tool(
            name="read_pdf_pages",
            description=(
                "Extract raw (unformatted) text from PDF pages. FREE and instant. "
                "Use this to verify page offsets: peek at a page, read its printed number, "
                "calculate the difference from the PDF page index, then use `get_book_pages_latex` "
                "on the correct page. Do not use this to read entire chapters."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer"},
                    "pages": {"type": "string", "description": "Page range (e.g., '10', '10-15', '10,12')"}
                },
                "required": ["book_id", "pages"]
            }
        ),

        Tool(
            name="get_book_pages_latex",
            description=(
                "CORE EXTRACTION TOOL. Convert book pages to high-quality LaTeX using AI vision. "
                "Results are cached — subsequent calls for the same page are instant. "
                "USE THIS on every source book when researching. Minimum 2 source books per research session. "
                "WARNING: Never use on Table of Contents or Index pages."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer"},
                    "pages": {"type": "string", "description": "Page range (e.g., '112-115')"},
                    "refresh": {"type": "boolean", "description": "Force re-conversion (overrides cache)", "default": False},
                    "min_quality": {"type": "number", "description": "Minimum quality score (0.0–1.0)", "default": 0.7}
                },
                "required": ["book_id", "pages"]
            }
        ),

        Tool(
            name="synthesize_page_knowledge",
            description=(
                "Extract Knowledge Base terms (theorems, definitions, lemmas) from specific book pages "
                "and index them permanently in the Knowledge Base. "
                "Call this after `get_book_pages_latex` when a page contains formal mathematical content "
                "you want permanently indexed in the KB."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer"},
                    "page": {"type": "string", "description": "Single page or range to synthesise (e.g., '112', '112-114')"}
                },
                "required": ["book_id", "page"]
            }
        ),

        # ── KNOWLEDGE BASE ────────────────────────────────────────────────────

        Tool(
            name="search_knowledge_base",
            description=(
                "Search the Knowledge Base for indexed theorems, definitions, and mathematical results. "
                "These are human-reviewed, high-quality extractions with full LaTeX content. "
                "Always check here first before doing a full PDF extraction."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search term (e.g., 'Hahn-Banach', 'Lipschitz continuity')"},
                    "type": {
                        "type": "string",
                        "enum": ["theorem", "definition", "lemma", "proposition", "corollary", "example", "remark", "note"],
                        "description": "Filter by term type"
                    },
                    "limit": {"type": "integer", "default": 20}
                },
                "required": ["query"]
            }
        ),

        Tool(
            name="get_kb_term",
            description=(
                "Retrieve the full content of a specific Knowledge Base entry, including "
                "the complete LaTeX snippet, source book, and page number."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "term_id": {"type": "integer", "description": "Term ID from search_knowledge_base results"}
                },
                "required": ["term_id"]
            }
        ),

        # ── BOOK METADATA ─────────────────────────────────────────────────────

        Tool(
            name="update_book_metadata",
            description="Correct or update a book's metadata (title, author, year, MSC code, summary, tags).",
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer"},
                    "title": {"type": "string"},
                    "author": {"type": "string"},
                    "publisher": {"type": "string"},
                    "year": {"type": "integer"},
                    "isbn": {"type": "string"},
                    "msc_class": {"type": "string"},
                    "summary": {"type": "string"},
                    "tags": {"type": "string"},
                    "level": {"type": "string"},
                },
                "required": ["book_id"]
            }
        ),

        Tool(
            name="enrich_book_metadata",
            description=(
                "Fetch professional metadata for a book from zbMATH Open (MSC codes, expert reviews, keywords). "
                "Requires the book to have a DOI or zbMATH ID."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer"}
                },
                "required": ["book_id"]
            }
        ),

        Tool(
            name="refresh_book_metadata",
            description="Re-run the AI metadata extraction pipeline for a book (title, author, summary, MSC).",
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer"}
                },
                "required": ["book_id"]
            }
        ),

        Tool(
            name="scan_bibliography",
            description="Extract bibliography entries from a book's reference pages using AI vision.",
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer"}
                },
                "required": ["book_id"]
            }
        ),

        # ── NOTES ─────────────────────────────────────────────────────────────

        Tool(
            name="list_notes",
            description=(
                "List research notes in the database. "
                "Includes handwritten-scan notes and LLM-authored notes."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer", "description": "Filter by source book"},
                    "limit": {"type": "integer", "default": 50}
                }
            }
        ),

        Tool(
            name="get_note_content",
            description="Retrieve the full Markdown and LaTeX content of a research note.",
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {"type": "integer"}
                },
                "required": ["note_id"]
            }
        ),

        Tool(
            name="create_note",
            description=(
                "Create and store a new research note. "
                "Use this ONLY after presenting a draft to the user and receiving approval. "
                "Provide both markdown and latex for full functionality."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Descriptive title (not just e.g., 'Definition 2.3')"},
                    "markdown": {"type": "string", "description": "Full Markdown content with inline LaTeX ($...$)"},
                    "latex": {"type": "string", "description": "Full LaTeX document for PDF compilation"},
                    "tags": {"type": "string", "description": "Comma-separated subject keywords"},
                    "msc": {"type": "string", "description": "MSC 2020 classification code"}
                },
                "required": ["title", "markdown"]
            }
        ),

        Tool(
            name="update_note_content",
            description="Update the Markdown and/or LaTeX content of an existing note.",
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {"type": "integer"},
                    "markdown": {"type": "string"},
                    "latex": {"type": "string"}
                },
                "required": ["note_id"]
            }
        ),

        Tool(
            name="add_note_book_relation",
            description="Link a note to a source book and page number, creating a permanent citation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {"type": "integer"},
                    "book_id": {"type": "integer"},
                    "page": {"type": "integer", "description": "Source page number"},
                    "relation_type": {"type": "string", "default": "references"}
                },
                "required": ["note_id", "book_id"]
            }
        ),

        Tool(
            name="compile_note",
            description="Compile a note's LaTeX to PDF. Call this after creating or updating a note with LaTeX content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {"type": "integer"}
                },
                "required": ["note_id"]
            }
        ),

        Tool(
            name="upload_note_scan",
            description="Transcribe a handwritten note image (photo/scan) into Markdown + LaTeX and store it.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the image file"}
                },
                "required": ["file_path"]
            }
        ),

        # ── CONTEXT & BOOKMARKS ───────────────────────────────────────────────

        Tool(
            name="get_system_state",
            description="Read the current Web UI state — tells you which book the user is currently viewing.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),

        Tool(
            name="manage_bookmarks",
            description=(
                "Save, list, or delete bookmarks for important book pages. "
                "Actions: 'create' | 'list' | 'delete'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["create", "list", "delete"]},
                    "book_id": {"type": "integer"},
                    "page_range": {"type": "string", "description": "e.g., '112-115'"},
                    "tags": {"type": "string"},
                    "notes": {"type": "string"},
                    "bookmark_id": {"type": "integer", "description": "Required for delete"}
                },
                "required": ["action"]
            }
        ),
    ]


# ---------------------------------------------------------------------------
# Tool Dispatch
# ---------------------------------------------------------------------------

@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    try:
        dispatch = {
            # Search & discovery
            "search_books": search_books,
            "get_book_details": get_book_details,
            "get_book_toc": get_book_toc,
            "search_within_book": search_within_book,
            "deep_index_book": deep_index_book,
            "reindex_book": reindex_book,
            # Extraction
            "read_pdf_pages": read_pdf_pages,
            "get_book_pages_latex": get_book_pages_latex,
            "synthesize_page_knowledge": synthesize_page_knowledge,
            # Knowledge Base
            "search_knowledge_base": search_knowledge_base,
            "get_kb_term": get_kb_term,
            # Book metadata
            "update_book_metadata": update_book_metadata,
            "enrich_book_metadata": enrich_book_metadata,
            "refresh_book_metadata": refresh_book_metadata,
            "scan_bibliography": scan_bibliography,
            # Notes
            "list_notes": list_notes,
            "get_note_content": get_note_content,
            "create_note": create_note,
            "update_note_content": update_note_content,
            "add_note_book_relation": add_note_book_relation,
            "compile_note": compile_note,
            "upload_note_scan": upload_note_scan,
            # Context
            "get_system_state": get_system_state,
            "manage_bookmarks": manage_bookmarks,
        }
        fn = dispatch.get(name)
        if fn is None:
            raise ValueError(f"Unknown tool: {name}")
        import time as _time
        _t0 = _time.time()
        args_summary = json.dumps(arguments or {}, ensure_ascii=False)[:300]
        logger.info(f"→ TOOL CALL: {name}  args={args_summary}")
        result = await fn(arguments or {})
        elapsed = _time.time() - _t0
        result_len = sum(len(r.text) for r in result) if result else 0
        logger.info(f"← TOOL DONE: {name}  {elapsed:.1f}s  response={result_len} chars")
        return result
    except Exception as e:
        logger.error(f"✗ TOOL ERROR [{name}]: {e}", exc_info=True)
        return [TextContent(type="text", text=f"Error: {str(e)}")]


# ---------------------------------------------------------------------------
# Tool Implementations
# ---------------------------------------------------------------------------

async def search_books(args: dict) -> list[TextContent]:
    params = {
        "q": args["query"],
        "limit": args.get("limit", 10),
        "fts": "true" if args.get("use_fts", True) else "false",
        "vec": "true" if args.get("use_vector", True) else "false",
        "field": args.get("field", "all"),
    }
    response = requests.get(f"{API_BASE}/search", params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    results = data.get("results", [])
    if not results:
        return [TextContent(type="text", text=f"No results for '{args['query']}'.")]
    output = f"Found {data.get('total_count', len(results))} results for '{args['query']}':\n\n"
    for i, b in enumerate(results, 1):
        output += f"{i}. **{b['title']}** — {b['author']} [ID: {b['id']}]\n"
        if b.get("summary"):
            output += f"   {b['summary'][:120]}...\n"
        output += "\n"
    return [TextContent(type="text", text=output)]


async def get_book_details(args: dict) -> list[TextContent]:
    r = requests.get(f"{API_BASE}/books/{args['book_id']}", timeout=10)
    r.raise_for_status()
    d = r.json()
    out = f"# {d['title']}\n**Author:** {d['author']} | **ID:** {d['id']} | **Pages:** {d.get('page_count', '?')}\n\n"
    flags = []
    if d.get("has_toc"): flags.append("TOC ✓")
    else: flags.append("TOC ✗ → run reindex_book")
    if d.get("has_index"): flags.append("Index ✓")
    else: flags.append("Index ✗ → run reindex_book")
    if d.get("is_deep_indexed"): flags.append("DeepIndex ✓")
    else: flags.append("DeepIndex ✗ → run deep_index_book")
    out += "**Status:** " + " | ".join(flags) + "\n"
    if d.get("page_offset"):
        out += f"**Page Offset:** +{d['page_offset']} (PDF page = printed page + {d['page_offset']})\n"
    if d.get("summary"): out += f"\n**Summary:** {d['summary']}\n"
    if d.get("msc_class"): out += f"**MSC:** {d['msc_class']}\n"
    if d.get("tags"): out += f"**Tags:** {d['tags']}\n"
    if d.get("similar_books"):
        out += "\n**Similar Books:**\n"
        for b in d["similar_books"]:
            out += f"  - {b['title']} [ID: {b['id']}]\n"
    return [TextContent(type="text", text=out)]


async def get_book_toc(args: dict) -> list[TextContent]:
    r = requests.get(f"{API_BASE}/books/{args['book_id']}/toc", timeout=10)
    r.raise_for_status()
    toc = r.json().get("toc", [])
    if not toc:
        return [TextContent(type="text", text="No Table of Contents available for this book.")]
    out = f"Table of Contents (Book {args['book_id']}):\n\n"
    for item in toc:
        if isinstance(item, (list, tuple)) and len(item) >= 3:
            indent = "  " * item[1]
            out += f"{indent}- {item[0]} (p. {item[2]})\n"
        elif isinstance(item, dict):
            indent = "  " * item.get("level", 0)
            page = item.get("pdf_page") or item.get("page", "?")
            out += f"{indent}- {item.get('title', '?')} (p. {page})\n"
    return [TextContent(type="text", text=out)]


async def search_within_book(args: dict) -> list[TextContent]:
    r = requests.get(f"{API_BASE}/books/{args['book_id']}/search",
                     params={"q": args["query"]}, timeout=30)
    if not r.ok:
        return [TextContent(type="text", text=f"Search failed: {r.text}")]
    data = r.json()
    matches = data.get("matches", [])
    if not matches:
        return [TextContent(type="text", text=f"No matches for '{args['query']}' in book {args['book_id']}.")]
    is_deep = data.get("is_deep_indexed", False)
    out = f"Matches ({len(matches)}) in book {args['book_id']} "
    out += "— deep index ✓:\n\n" if is_deep else "— snippet search (run deep_index_book for better results):\n\n"
    for m in matches:
        out += f"  p. {m['page']}: {m['snippet']}\n"
    return [TextContent(type="text", text=out)]


async def deep_index_book(args: dict) -> list[TextContent]:
    r = requests.post(f"{API_BASE}/books/{args['book_id']}/deep-index", timeout=300)
    if r.ok:
        return [TextContent(type="text", text=f"✓ Deep indexing complete: {r.json().get('message')}")]
    return [TextContent(type="text", text=f"✗ Failed: {r.text}")]


async def reindex_book(args: dict) -> list[TextContent]:
    mode = args.get("mode", "auto")
    r = requests.post(f"{API_BASE}/books/{args['book_id']}/reindex/{mode}", timeout=300)
    if r.ok:
        results = r.json().get("results", {})
        out = f"✓ Re-indexing ({mode}) done.\n"
        for k, v in results.items():
            ok = (isinstance(v, dict) and v.get("success")) or (isinstance(v, bool) and v)
            out += f"  {k.upper()}: {'✓' if ok else '✗'}\n"
        return [TextContent(type="text", text=out)]
    return [TextContent(type="text", text=f"✗ Re-indexing failed: {r.text}")]


async def read_pdf_pages(args: dict) -> list[TextContent]:
    r = requests.post(f"{API_BASE}/tools/pdf-to-text",
                      json={"book_id": args["book_id"], "pages": args["pages"]}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("success"):
        return [TextContent(type="text", text=data.get("text", "(empty)"))]
    return [TextContent(type="text", text=f"Error: {data.get('error', 'Unknown')}")]


async def get_book_pages_latex(args: dict) -> list[TextContent]:
    params = {
        "pages": args["pages"],
        "refresh": "true" if args.get("refresh") else "false",
        "min_quality": args.get("min_quality", 0.7)
    }
    r = requests.get(f"{API_BASE}/books/{args['book_id']}/pages/latex",
                     params=params, timeout=300)
    r.raise_for_status()
    data = r.json()
    out = f"## LaTeX — Book {args['book_id']}, Pages {args['pages']}\n\n"
    for p in data.get("pages", []):
        page_num = p["page"]
        if "error" in p:
            out += f"### Page {page_num}\n⚠ Error: {p['error']}\n\n"
        else:
            out += f"### Page {page_num} (quality: {p.get('quality', 0):.2f}, source: {p.get('source', '?')})\n"
            out += "```latex\n"
            out += p.get("latex") or "% No LaTeX recovered"
            out += "\n```\n\n"
    return [TextContent(type="text", text=out)]


async def synthesize_page_knowledge(args: dict) -> list[TextContent]:
    payload = {"book_id": args["book_id"], "page": args["page"], "refresh": True, "abort_on_failure": True, "force_extract": True}
    r = requests.post(f"{API_BASE}/tools/pdf-to-note", json=payload, timeout=300)
    r.raise_for_status()
    data = r.json()
    if data.get("success"):
        count = data.get("terms_found", 0)
        return [TextContent(type="text", text=f"✓ Synthesis complete. {count} knowledge term(s) added directly to the Knowledge Base.")]
    return [TextContent(type="text", text=f"✗ Synthesis failed: {data.get('error', 'Unknown')}")]


async def search_knowledge_base(args: dict) -> list[TextContent]:
    params = {"q": args["query"], "limit": args.get("limit", 20), "status": "approved"}
    if args.get("type"):
        params["kind"] = args["type"]
    r = requests.get(f"{API_BASE}/kb/terms/search", params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    if not data:
        return [TextContent(type="text", text=f"No KB entries found for '{args['query']}'.")]
    out = f"Knowledge Base — {len(data)} result(s) for '{args['query']}':\n\n"
    for item in data:
        out += f"- **{item.get('name', '?')}** ({item.get('term_type', '?')}) "
        out += f"— {item.get('book_author', 'Unknown')}, p. {item.get('page_start', '?')} "
        out += f"[ID: {item.get('id')}]\n"
    return [TextContent(type="text", text=out)]


async def get_kb_term(args: dict) -> list[TextContent]:
    r = requests.get(f"{API_BASE}/kb/terms/{args['term_id']}", timeout=10)
    if not r.ok:
        return [TextContent(type="text", text="Term not found.")]
    t = r.json()
    out = f"# {t['name']} ({t['term_type']})\n"
    out += f"**Source:** {t.get('book_title', '?')} by {t.get('book_author', '?')}, p. {t.get('page_start', '?')}\n\n"
    if t.get("used_terms"):
        import json as _json
        try:
            kws = _json.loads(t["used_terms"]) if isinstance(t["used_terms"], str) else t["used_terms"]
        except Exception:
            kws = [k.strip() for k in t["used_terms"].split(",")]
        out += "**Keywords:** " + ", ".join(kws) + "\n\n"
    out += "```latex\n"
    out += t.get("latex_content", "% No LaTeX content")
    out += "\n```\n"
    return [TextContent(type="text", text=out)]


async def update_book_metadata(args: dict) -> list[TextContent]:
    book_id = args.pop("book_id")
    r = requests.patch(f"{API_BASE}/books/{book_id}/metadata", json=args, timeout=10)
    if r.ok:
        return [TextContent(type="text", text=f"✓ Metadata updated for book {book_id}.")]
    return [TextContent(type="text", text=f"✗ Update failed: {r.text}")]


async def enrich_book_metadata(args: dict) -> list[TextContent]:
    r = requests.post(f"{API_BASE}/books/{args['book_id']}/enrich", timeout=60)
    if r.ok:
        d = r.json()
        return [TextContent(type="text", text=f"✓ zbMATH enrichment complete. Zbl: {d.get('zbl_id')}, Score: {d.get('trust_score', 0):.2f}")]
    return [TextContent(type="text", text=f"✗ Enrichment failed: {r.text}")]


async def refresh_book_metadata(args: dict) -> list[TextContent]:
    r = requests.post(f"{API_BASE}/books/{args['book_id']}/metadata/refresh", timeout=180)
    r.raise_for_status()
    return [TextContent(type="text", text=f"✓ Metadata refreshed for book {args['book_id']}.")]


async def scan_bibliography(args: dict) -> list[TextContent]:
    r = requests.post(f"{API_BASE}/tools/bib-scan", json={"book_id": args["book_id"]}, timeout=300)
    if r.ok:
        return [TextContent(type="text", text=f"✓ Bibliography scan triggered. View results in the Web UI.")]
    return [TextContent(type="text", text=f"✗ Scan failed: {r.text}")]


async def list_notes(args: dict) -> list[TextContent]:
    params = {"limit": args.get("limit", 50)}
    if args.get("book_id"): params["book_id"] = args["book_id"]
    r = requests.get(f"{API_BASE}/notes", params=params, timeout=10)
    r.raise_for_status()
    notes = r.json()
    if not notes:
        return [TextContent(type="text", text="No notes found.")]
    out = "Research Notes:\n\n"
    for n in notes:
        out += f"- [ID {n['id']}] **{n['title']}** ({n.get('source_type', '?')})\n"
    return [TextContent(type="text", text=out)]


async def get_note_content(args: dict) -> list[TextContent]:
    r = requests.get(f"{API_BASE}/notes/{args['note_id']}/content", timeout=10)
    r.raise_for_status()
    data = r.json()
    out = ""
    if data.get("markdown"):
        out += "### Markdown\n```markdown\n" + data["markdown"] + "\n```\n\n"
    if data.get("latex"):
        out += "### LaTeX\n```latex\n" + data["latex"] + "\n```\n"
    return [TextContent(type="text", text=out or "Note has no content.")]


async def create_note(args: dict) -> list[TextContent]:
    r = requests.post(f"{API_BASE}/notes", json=args, timeout=30)
    r.raise_for_status()
    data = r.json()
    return [TextContent(type="text", text=f"✓ Note created (ID: {data['id']}). Now call add_note_book_relation and compile_note.")]


async def update_note_content(args: dict) -> list[TextContent]:
    note_id = args.pop("note_id")
    r = requests.patch(f"{API_BASE}/notes/{note_id}/content", json=args, timeout=10)
    r.raise_for_status()
    return [TextContent(type="text", text=f"✓ Note {note_id} content updated.")]


async def add_note_book_relation(args: dict) -> list[TextContent]:
    note_id = args.pop("note_id")
    payload = {"book_id": args["book_id"], "page": args.get("page"), "type": args.get("relation_type", "references")}
    r = requests.post(f"{API_BASE}/notes/{note_id}/books", json=payload, timeout=10)
    r.raise_for_status()
    return [TextContent(type="text", text=f"✓ Note {note_id} linked to book {args['book_id']}.")]


async def compile_note(args: dict) -> list[TextContent]:
    r = requests.post(f"{API_BASE}/notes/{args['note_id']}/compile", timeout=120)
    if r.ok:
        return [TextContent(type="text", text=f"✓ PDF compiled: {r.json().get('pdf_path', '?')}")]
    return [TextContent(type="text", text=f"✗ Compilation failed: {r.json().get('error', r.text)}")]


async def upload_note_scan(args: dict) -> list[TextContent]:
    fp = Path(args["file_path"])
    if not fp.exists():
        return [TextContent(type="text", text=f"File not found: {fp}")]
    with open(fp, "rb") as f:
        r = requests.post(f"{API_BASE}/notes/upload", files={"file": (fp.name, f, "image/jpeg")}, timeout=60)
    if r.ok:
        data = r.json()
        return [TextContent(type="text", text=f"✓ Transcribed note stored (ID: {data['id']}).\n\n{data.get('transcription', '')}")]
    return [TextContent(type="text", text=f"✗ Upload failed: {r.text}")]


async def get_system_state(args: dict) -> list[TextContent]:
    state_path = Path(__file__).parent.parent / "current_state.json"
    if not state_path.exists():
        return [TextContent(type="text", text="No active UI state — user may not be using the Web UI.")]
    try:
        state = json.loads(state_path.read_text())
        out = "### Current UI State\n"
        out += f"- Action: {state.get('action')}\n"
        if state.get("book_id"): out += f"- Book ID: {state['book_id']}\n"
        for k, v in (state.get("extra") or {}).items():
            out += f"- {k}: {v}\n"
        return [TextContent(type="text", text=out)]
    except Exception as e:
        return [TextContent(type="text", text=f"Error reading state: {e}")]


async def manage_bookmarks(args: dict) -> list[TextContent]:
    action = args["action"]
    if action == "create":
        payload = {"book_id": args.get("book_id"), "page_range": args.get("page_range"),
                   "tags": args.get("tags"), "notes": args.get("notes")}
        r = requests.post(f"{API_BASE}/bookmarks", json=payload, timeout=5)
        r.raise_for_status()
        return [TextContent(type="text", text=f"✓ Bookmark created (ID: {r.json()['id']})")]
    elif action == "list":
        params = {}
        if args.get("book_id"): params["book_id"] = args["book_id"]
        if args.get("tags"): params["tag"] = args["tags"]
        r = requests.get(f"{API_BASE}/bookmarks", params=params, timeout=5)
        r.raise_for_status()
        bms = r.json()
        if not bms:
            return [TextContent(type="text", text="No bookmarks found.")]
        out = "Bookmarks:\n\n"
        for b in bms:
            out += f"[{b['id']}] {b['book_title']} p.{b['page_range']}"
            if b.get("tags"): out += f" #{b['tags']}"
            out += "\n"
        return [TextContent(type="text", text=out)]
    elif action == "delete":
        bid = args.get("bookmark_id")
        if not bid:
            return [TextContent(type="text", text="bookmark_id required for delete.")]
        r = requests.delete(f"{API_BASE}/bookmarks/{bid}", timeout=5)
        r.raise_for_status()
        return [TextContent(type="text", text=f"✓ Bookmark {bid} deleted.")]
    return [TextContent(type="text", text=f"Unknown action: {action}")]


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@app.list_resources()
async def list_resources() -> list[Resource]:
    return [
        Resource(
            uri="mathstudio://library/stats",
            name="Library Statistics",
            mimeType="application/json",
            description="Current library statistics"
        )
    ]


@app.read_resource()
async def read_resource(uri: str) -> str:
    if uri == "mathstudio://library/stats":
        r = requests.get(f"{API_BASE}/admin/stats", timeout=10)
        r.raise_for_status()
        return json.dumps(r.json(), indent=2)
    raise ValueError(f"Unknown resource: {uri}")


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
