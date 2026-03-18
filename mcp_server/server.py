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
import sys
import os
from pathlib import Path
from typing import Any

# Add project root to sys.path so we can import services
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
sys.path.append(str(PROJECT_ROOT))

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
Answer mathematical questions by extracting knowledge from primary sources and the human-verified Knowledge Base. Never guess or hallucinate; always cite actual book pages or KB entries.

## CORE TOOLS (in preferred order of use)
1. **search_kb** — Search for Gold Standard results (theorems, definitions, exercises). Use filters like `kind` or `msc`.
2. **search_books** — Find relevant books across the library when KB results are insufficient.
3. **search_within_book** — Find exact mentions of concepts in a specific book.
4. **search_latex** — Search across all AI-converted pages for deep technical details.
5. **get_kb_term** — Read the high-quality LaTeX of a verified result.

## THE RESEARCH IMPERATIVE: COMPARE & CONTRAST
**Never settle for a single definition.** When researching a concept:
- Find treatments in MULTIPLE books (at least 2-3).
- Identify differences in notation, assumptions, or scope (e.g., "Banach spaces" vs "Hilbert spaces").
- Look for **exercises** associated with the concept to understand its applications.
- Synthesise a conclusion that notes the "evolution" of the idea across your sources.

## NOTE-TAKING PIPELINE
Your findings are ephemeral unless you store them.
1. **start_research_draft** — Begin a session-long collection of findings.
2. **append_to_draft** — Store LaTeX snippets, comparisons, and proofs.
3. **publish_research_report** — Finalise your draft into a permanent, searchable Note.
4. **search_notes** — Before starting, check if previous research has already covered this ground.

## CRITICAL RULES
- Use `read_pdf_pages` to verify page offsets before citing.
- Treat 'Exercise' kind results as critical clues to a concept's utility.
- Citations must include Book ID, Title, and Printed Page Number.
"""))]
        )

    if name == "deep_research_workflow":
        topic = args.get("topic", "the requested topic")
        return GetPromptResult(
            description=f"Deep research protocol for: {topic}",
            messages=[PromptMessage(role="user", content=TextContent(type="text", text=f"""\
I need a deep, multi-source research session on: **{topic}**

Follow this protocol strictly:

### PHASE 1: PREVIOUS KNOWLEDGE
- Call `search_notes` to see if we have existing research on {topic}.
- Call `search_kb` for verified theorems and exercises.

### PHASE 2: COMPARATIVE LIBRARY SEARCH
- Call `search_books` to find relevant sources.
- For the best 3 sources, use `search_within_book` or `search_latex` to find technical discussions.
- Use `read_pdf_pages` to verify page context.

### PHASE 3: SYNTHESIS & DRAFTING
- Start a draft with `start_research_draft`.
- Compare how different authors approach the topic.
- Append LaTeX proofs and examples using `append_to_draft`.

### PHASE 4: PUBLISH
- Ask: "I have synthesized a comparative analysis. Would you like me to publish this as a research report?"
- If yes, `publish_research_report`.
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
                "Returns books with metadata and relevance scores."
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
                "Retrieve comprehensive metadata for a specific book, including indexing status. "
                "Examine the 'is_deep_indexed' and 'latex_cache_count' fields to see if the book is 'Research-Ready'."
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
                "Use this to understand which chapter covers a topic."
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
                "Search for a term or phrase within a specific book's index/toc/text. "
                "Returns page numbers and snippets."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer"},
                    "query": {"type": "string", "description": "Term or phrase to find (e.g., 'Cauchy sequence')"}
                },
                "required": ["book_id", "query"]
            }
        ),

        Tool(
            name="search_book_latex",
            description=(
                "Search the full AI-converted LaTeX content of a specific book. "
                "This is the most precise way to find technical content in a 'Research-Ready' book."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer"},
                    "query": {"type": "string", "description": "LaTeX snippet or keyword (e.g., 'Banach\\\\ space')"},
                    "limit": {"type": "integer", "default": 20}
                },
                "required": ["book_id", "query"]
            }
        ),

        Tool(
            name="search_latex",
            description=(
                "Search across ALL extracted mathematical content in the library (Approved + Drafts). "
                "Use this for broad technical discovery."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "LaTeX snippet or keyword"},
                    "limit": {"type": "integer", "default": 20}
                },
                "required": ["query"]
            }
        ),

        # ── KNOWLEDGE BASE & RESEARCH ──────────────────────────────────────────

        Tool(
            name="search_kb",
            description=(
                "Search the Knowledge Base for Gold Standard mathematical results (theorems, definitions, exercises). "
                "Returns only human-verified, high-precision mathematical data."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search term or LaTeX pattern (e.g., '\\\\int ?f(x) dx')"},
                    "kind": {"type": "string", "enum": ["theorem", "definition", "lemma", "proposition", "corollary", "example", "remark", "axiom", "notation", "exercise"]},
                    "book_id": {"type": "integer"},
                    "msc": {"type": "string", "description": "MSC 2020 code prefix (e.g. '26')"},
                    "year": {"type": "integer"},
                    "limit": {"type": "integer", "default": 20}
                },
                "required": ["query"]
            }
        ),

        Tool(
            name="get_kb_term",
            description=(
                "Retrieve the full content of a specific Knowledge Base entry, including cached LaTeX."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "term_id": {"type": "integer", "description": "Term ID from search_kb results"}
                },
                "required": ["term_id"]
            }
        ),

        Tool(
            name="search_concepts",
            description=(
                "Search for canonical mathematical concepts (e.g., 'Riemann Integral'). "
                "Returns concepts that group multiple theorems and definitions together."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Concept name fragment"},
                    "limit": {"type": "integer", "default": 10}
                },
                "required": ["query"]
            }
        ),

        Tool(
            name="list_concept_terms",
            description="List all theorems, definitions, and exercises associated with a specific concept.",
            inputSchema={
                "type": "object",
                "properties": {
                    "concept_id": {"type": "integer"},
                    "kind": {"type": "string", "enum": ["theorem", "definition", "exercise", "all"], "default": "all"}
                },
                "required": ["concept_id"]
            }
        ),

        # ── CONTENT EXTRACTION (CONSUMING) ───────────────────────────────────

        Tool(
            name="read_pdf_pages",
            description=(
                "Extract raw text from PDF pages to verify context and printed page numbers."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer"},
                    "pages": {"type": "string", "description": "Page range (e.g., '10-12')"}
                },
                "required": ["book_id", "pages"]
            }
        ),

        Tool(
            name="get_book_pages_latex",
            description=(
                "Retrieve high-quality AI-converted LaTeX for specific book pages. "
                "Use this for deep study of a book's mathematical content."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer"},
                    "pages": {"type": "string", "description": "Page range (e.g., '230-235')"},
                    "min_quality": {"type": "number", "default": 0.7}
                },
                "required": ["book_id", "pages"]
            }
        ),

        Tool(
            name="request_book_scan",
            description=(
                "Queue a full library pipeline scan for a book (ToC, Deep Indexing, LaTeX, KB Extraction). "
                "This makes a book 'Research-Ready' but takes several minutes per book."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer"},
                    "reason": {"type": "string", "description": "Reason for prioritization"}
                },
                "required": ["book_id"]
            }
        ),

        # ── RESEARCH & DRAFT MANAGEMENT (Autonomous) ──────────────────────────

        Tool(
            name="start_research_draft",
            description="Initialize a session-long research draft for a mathematical topic.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Title of the research report"}
                },
                "required": ["title"]
            }
        ),

        Tool(
            name="append_to_draft",
            description="Add LaTeX content, comparisons, or proofs to the current research draft.",
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "High-quality LaTeX content"}
                },
                "required": ["content"]
            }
        ),

        Tool(
            name="publish_research_report",
            description="Finalize and compile the draft into a standalone LaTeX and PDF document in the MCP notes folder.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),

        Tool(
            name="create_standalone_note",
            description="Directly create a standalone LaTeX and PDF note in the MCP notes folder (outside the draft workflow).",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Title of the note"},
                    "content": {"type": "string", "description": "Full LaTeX content (body or full document)"}
                },
                "required": ["title", "content"]
            }
        ),

        Tool(
            name="get_system_state",
            description="Read the current Web UI state.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
    ]


# ---------------------------------------------------------------------------
# Tool Dispatch & State
# ---------------------------------------------------------------------------

# Simple in-memory session state for the autonomous draft system
MCP_NOTES_DIR = Path(__file__).parent / "notes"
MCP_NOTES_DIR.mkdir(exist_ok=True)

class ResearchDraft:
    def __init__(self, title=""):
        self.title = title
        self.sections = []
        self.active = False

    def reset(self, title):
        self.title = title
        self.sections = []
        self.active = True

    def append(self, content):
        if not self.active: return False
        self.sections.append(content)
        return True

    def get_full_latex(self):
        safe_title = self.title.replace("_", " ").replace("&", "\\&")
        header = [
            "\\documentclass{article}",
            "\\usepackage[utf8]{inputenc}",
            "\\usepackage{amsmath,amssymb,amsfonts,amsthm,geometry}",
            "\\geometry{margin=1in}",
            "\\title{" + safe_title + "}",
            "\\author{MathStudio Agentic Researcher}",
            "\\date{\\today}",
            "\\begin{document}",
            "\\maketitle",
        ]
        footer = ["\\end{document}"]
        return "\n".join(header + self.sections + footer)

_draft_state = ResearchDraft()

def _compile_latex(title, full_latex):
    import subprocess
    import re
    
    # Generate safe filename
    base_name = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")[:64]
    tex_path = MCP_NOTES_DIR / f"{base_name}.tex"
    pdf_path = MCP_NOTES_DIR / f"{base_name}.pdf"
    
    # Save LaTeX
    tex_path.write_text(full_latex, encoding="utf-8")
    
    # Compile PDF
    try:
        # Run pdflatex
        cmd = ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex_path.name]
        result = subprocess.run(cmd, cwd=MCP_NOTES_DIR, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            error_log = result.stdout[-500:]
            return False, f"⚠ LaTeX saved to {tex_path.name}, but PDF compilation failed:\n\n{error_log}"
        
        # Cleanup auxiliary files
        for ext in [".aux", ".log", ".out"]:
            aux_file = MCP_NOTES_DIR / f"{base_name}{ext}"
            if aux_file.exists(): aux_file.unlink()
            
        return True, (tex_path.name, pdf_path.name)
        
    except Exception as e:
        return False, f"✗ Error during publication: {e}"

async def start_research_draft(args: dict) -> list[TextContent]:
    _draft_state.reset(args["title"])
    return [TextContent(type="text", text=f"✓ Research draft '{args['title']}' initialized.")]

async def append_to_draft(args: dict) -> list[TextContent]:
    if _draft_state.append(args["content"]):
        return [TextContent(type="text", text="✓ Section appended to draft.")]
    return [TextContent(type="text", text="✗ No active draft. Use start_research_draft first.")]

async def publish_research_report(args: dict) -> list[TextContent]:
    if not _draft_state.active:
        return [TextContent(type="text", text="✗ No active draft to publish.")]
    
    success, result = _compile_latex(_draft_state.title, _draft_state.get_full_latex())
    if success:
        tex_name, pdf_name = result
        _draft_state.active = False # Reset session
        return [TextContent(type="text", text=f"✓ Research report published successfully!\n- LaTeX: {tex_name}\n- PDF: {pdf_name}\n- Location: {MCP_NOTES_DIR}")]
    else:
        return [TextContent(type="text", text=result)]

async def create_standalone_note(args: dict) -> list[TextContent]:
    content = args["content"]
    # Wrap in document if not already a full document
    if "\\documentclass" not in content:
        safe_title = args["title"].replace("_", " ").replace("&", "\\&")
        header = [
            "\\documentclass{article}",
            "\\usepackage[utf8]{inputenc}",
            "\\usepackage{amsmath,amssymb,amsfonts,amsthm,geometry}",
            "\\geometry{margin=1in}",
            "\\title{" + safe_title + "}",
            "\\author{MathStudio Agentic Researcher}",
            "\\date{\\today}",
            "\\begin{document}",
            "\\maketitle",
        ]
        footer = ["\\end{document}"]
        full_latex = "\n".join(header) + "\n" + content + "\n" + "\n".join(footer)
    else:
        full_latex = content

    success, result = _compile_latex(args["title"], full_latex)
    if success:
        tex_name, pdf_name = result
        return [TextContent(type="text", text=f"✓ Standalone note created successfully!\n- LaTeX: {tex_name}\n- PDF: {pdf_name}\n- Location: {MCP_NOTES_DIR}")]
    else:
        return [TextContent(type="text", text=result)]


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    try:
        dispatch = {
            # Search & discovery
            "search_books": search_books,
            "get_book_details": get_book_details,
            "get_book_toc": get_book_toc,
            "search_within_book": search_within_book,
            "search_book_latex": search_book_latex,
            "search_latex": search_latex,
            # Knowledge Base & Research
            "search_kb": search_kb,
            "get_kb_term": get_kb_term,
            "search_concepts": search_concepts,
            "list_concept_terms": list_concept_terms,
            # Extraction & Monitoring
            "read_pdf_pages": read_pdf_pages,
            "get_book_pages_latex": get_book_pages_latex,
            "request_book_scan": request_book_scan,
            # Notes & Synthesis (Autonomous)
            "start_research_draft": start_research_draft,
            "append_to_draft": append_to_draft,
            "publish_research_report": publish_research_report,
            "create_standalone_note": create_standalone_note,
            "get_system_state": get_system_state,
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
        lang_str = f" [{b.get('language', 'unknown')}]" if b.get('language') else ""
        output += f"{i}. **{b['title']}** — {b['author']} [ID: {b['id']}]{lang_str}\n"
        if b.get("summary"):
            output += f"   {b['summary'][:120]}...\n"
        output += "\n"
    return [TextContent(type="text", text=output)]


async def get_book_details(args: dict) -> list[TextContent]:
    r = requests.get(f"{API_BASE}/books/{args['book_id']}", timeout=10)
    r.raise_for_status()
    d = r.json()
    lang = d.get('language', 'unknown')
    out = f"# {d['title']}\n**Author:** {d['author']} | **ID:** {d['id']} | **Language:** {lang} | **Pages:** {d.get('page_count', '?')}\n\n"
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


async def search_book_latex(args: dict) -> list[TextContent]:
    params = {"q": args["query"], "limit": args.get("limit", 20)}
    r = requests.get(f"{API_BASE}/books/{args['book_id']}/search/latex",
                     params=params, timeout=30)
    if not r.ok:
        return [TextContent(type="text", text=f"LaTeX search failed: {r.text}")]
    data = r.json()
    results = data.get("results", [])
    if not results:
        return [TextContent(type="text", text=f"No LaTeX matches for '{args['query']}' in book {args['book_id']}.")]
    out = f"LaTeX matches in book {args['book_id']} for '{args['query']}':\n\n"
    for m in results:
        out += f"  - p. {m['page']}: {m['snippet']}\n"
        if m.get("terms"):
            out += "    Associated terms: " + ", ".join([t['name'] for t in m['terms']]) + "\n"
    return [TextContent(type="text", text=out)]


async def search_latex(args: dict) -> list[TextContent]:
    params = {
        "q": args["query"], 
        "limit": args.get("limit", 20),
        "status": "" # Empty string bypasses status filter to show Approved + Drafts
    }
    r = requests.get(f"{API_BASE}/kb/terms/search", params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not data:
        return [TextContent(type="text", text=f"No mathematical content found for '{args['query']}'.")]
    out = f"Mathematical content search results for '{args['query']}':\n\n"
    for item in data:
        out += f"### ID: {item['id']} | {item.get('name', '?')} | {item.get('book_author', '?')}, p.{item.get('page_start', '?')}\n"
        status_flag = " [DRAFT]" if item.get("status") == "draft" else ""
        out += f"Kind: {item.get('term_type', '?')}{status_flag} | Book: {item.get('book_title', '?')} [ID: {item.get('book_id')}]\n\n"
    return [TextContent(type="text", text=out)]


async def read_pdf_pages(args: dict) -> list[TextContent]:
    r = requests.post(f"{API_BASE}/tools/pdf-to-text",
                      json={"book_id": args["book_id"], "pages": args["pages"]}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("success"):
        return [TextContent(type="text", text=data.get("text", "(empty)"))]
    return [TextContent(type="text", text=f"Error: {data.get('error', 'Unknown')}")]


async def get_book_pages_latex(args: dict) -> list[TextContent]:
    # We maintain this as a consuming-only tool
    params = {
        "pages": args["pages"],
        "refresh": "false", # Forbidden in refactored server
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
            out += f"### Page {page_num}\n⚠ Error: {p['error']} (Page might not be scanned yet)\n\n"
        else:
            out += f"### Page {page_num} (quality: {p.get('quality', 0):.2f})\n"
            out += "```latex\n"
            out += p.get("latex") or "% No LaTeX recovered"
            out += "\n```\n\n"
    return [TextContent(type="text", text=out)]


async def search_kb(args: dict) -> list[TextContent]:
    params = {
        "q": args["query"],
        "limit": args.get("limit", 20),
        "status": "approved"
    }
    if args.get("kind"): params["kind"] = args["kind"]
    if args.get("book_id"): params["book_id"] = args["book_id"]
    if args.get("msc"): params["msc"] = args["msc"]
    if args.get("year"): params["year"] = args["year"]

    r = requests.get(f"{API_BASE}/kb/terms/search", params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    if not data:
        return [TextContent(type="text", text=f"No results found for '{args['query']}' in the Gold KB.")]
    out = f"Knowledge Base — {len(data)} result(s) for '{args['query']}':\n\n"
    for item in data:
        out += f"- **{item.get('name', '?')}** [{item.get('term_type', '?')}] "
        out += f"— {item.get('book_author', 'Unknown')}, p.{item.get('page_start', '?')} "
        out += f"[ID: {item.get('id')}]\n"
    return [TextContent(type="text", text=out)]


async def search_concepts(args: dict) -> list[TextContent]:
    params = {"q": args["query"], "limit": args.get("limit", 10)}
    r = requests.get(f"{API_BASE}/kb/concepts/search", params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    if not data:
        return [TextContent(type="text", text=f"No concepts found for '{args['query']}'.")]
    out = "Mathematical Concepts Found:\n\n"
    for c in data:
        out += f"- **{c['name']}** [ID: {c['id']}]\n"
        if c.get("description"):
            out += f"  {c['description'][:100]}...\n"
    return [TextContent(type="text", text=out)]


async def list_concept_terms(args: dict) -> list[TextContent]:
    params = {"concept_id": args["concept_id"], "limit": 100, "q": "*"}
    if args.get("kind") and args["kind"] != "all":
        params["kind"] = args["kind"]
    
    r = requests.get(f"{API_BASE}/kb/terms/search", params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    if not data:
        return [TextContent(type="text", text="No terms associated with this concept.")]
    out = f"Terms for Concept {args['concept_id']}:\n\n"
    for item in data:
        out += f"- {item.get('name', '?')} ({item.get('term_type', '?')}) | Source: ID {item.get('book_id')}, p.{item.get('page_start', '?')}\n"
    return [TextContent(type="text", text=out)]


async def request_book_scan(args: dict) -> list[TextContent]:
    # Call the real background scan queue
    r = requests.post(f"{API_BASE}/books/{args['book_id']}/scan", timeout=10)
    if r.status_code == 409:
        return [TextContent(type="text", text=f"✓ Book {args['book_id']} is already being scanned or in queue.")]
    if not r.ok:
        return [TextContent(type="text", text=f"✗ Scan request failed: {r.text}")]
    
    data = r.json()
    pos = data.get("queue_position", "?")
    return [TextContent(type="text", text=f"✓ Book {args['book_id']} ('{data.get('book_title', '?')}') has been queued for a full pipeline scan. Position in queue: {pos}.")]


async def get_kb_term(args: dict) -> list[TextContent]:
    r = requests.get(f"{API_BASE}/kb/terms/{args['term_id']}", timeout=10)
    if not r.ok:
        return [TextContent(type="text", text="Term not found in Knowledge Base.")]
    t = r.json()
    out = f"# {t['name']} ({t['term_type']})\n"
    out += f"**Source:** {t.get('book_title', '?')} by {t.get('book_author', '?')}, p.{t.get('page_start', '?')}\n\n"
    if t.get("used_terms"):
        try:
            kws = json.loads(t["used_terms"]) if isinstance(t["used_terms"], str) else t["used_terms"]
        except Exception:
            kws = [k.strip() for k in t["used_terms"].split(",")]
        out += "**Keywords:** " + ", ".join(kws) + "\n\n"
    
    out += "### Content (LaTeX)\n"
    out += "```latex\n"
    out += t.get("latex_content", "% No LaTeX content")
    out += "\n```\n"
    return [TextContent(type="text", text=out)]


async def get_system_state(args: dict) -> list[TextContent]:
    state_path = Path(__file__).parent.parent / "current_state.json"
    if not state_path.exists():
        return [TextContent(type="text", text="No active UI state.")]
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
