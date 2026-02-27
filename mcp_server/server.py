#!/usr/bin/env python3
"""
MathStudio MCP Server

Exposes the MathStudio API v1 as an MCP server for LLM integration.
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
    INTERNAL_ERROR,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mathstudio-mcp")

# Load configuration
CONFIG_PATH = Path(__file__).parent / "config.json"
with open(CONFIG_PATH) as f:
    config = json.load(f)

API_BASE = config["api_base_url"]
SERVER_NAME = config["server_name"]
SERVER_VERSION = config["server_version"]

# Initialize MCP server
app = Server(SERVER_NAME)


# --- Prompts ---

@app.list_prompts()
async def list_prompts() -> list[Prompt]:
    """List available educational, research, and usage prompts."""
    return [
        Prompt(
            name="usage_manifesto",
            description="Guidelines for using the MathStudio library effectively.",
            arguments=[]
        ),
        Prompt(
            name="researcher_workflow",
            description="The optimal 5-step discovery-synthesis pipeline.",
            arguments=[]
        ),
        Prompt(
            name="note_creation_workflow",
            description="Instructions for creating high-fidelity research notes from specific book sources (e.g. definitions, theorems).",
            arguments=[
                {
                    "name": "source_request",
                    "description": "The user's request (e.g. 'Definition 2.3 from Amann Escher')",
                    "required": True
                }
            ]
        )
    ]

@app.get_prompt()
async def get_prompt(name: str, arguments: dict | None) -> GetPromptResult:
    """Return the structured instructions for a given prompt."""
    if name == "usage_manifesto":
        return GetPromptResult(
            description="MathStudio Usage Manifesto (Agentic RAG)",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=(
                            "You are an Agentic RAG assistant for the MathStudio Research Library.\n\n"
                            "**THE GUIDING PRINCIPLE (Leitidee)**: The Knowledge Base is a theorem/definition location index. "
                            "Every concept maps to book pages where it appears, with cached LaTeX content.\n\n"
                            "**THE WORKFLOW**:\n"
                            "1. **Consult KB First**: Use `search_knowledge` or `get_concept_details` to find existing entries.\n"
                            "2. **Library Fallback**: If not in KB, use `search_books` or `search_within_book` to find primary sources.\n"
                            "3. **Read Pages**: Use `get_book_pages_latex` to read the exact pages once you find the right page number. This automatically caches the LaTeX AND discovers theorems on those pages (pushing them to the user review queue).\n"
                            "4. **Answer & Cite**: Answer the user with the exact LaTeX content from the library.\n\n"
                            "**CRITICAL RULE 1**: NEVER use `get_book_pages_latex` or `read_pdf_pages` to blindly read the Table of Contents or Index pages. This wastes AI resources and pollutes the proposal queue. Always use `search_within_book` to find the correct page numbers first.\n"
                            "**CRITICAL RULE 2**: NEVER make assumptions. Always base your answers on extracted library text.\n"
                            "**CRITICAL RULE 3**: UNDERSTAND PDF PAGE OFFSETS. The page number in a book (e.g., 'Page 10') is rarely the absolute PDF page number (which might be 24 due to Roman numeral prefaces). If `search_within_book` gives you a page, use the cheap `read_pdf_pages` tool to quickly peek at the absolute PDF page to see its printed number. Calculate the offset (e.g., +14 pages) and apply it to find the true page. Try up to 2 times, but DO NOT infinitely loop."
                        )
                    )
                )
            ]
        )
    elif name == "researcher_workflow":
        return GetPromptResult(
            description="The simplified research discovery pipeline",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=(
                            "To answer a mathematical question or find a specific proof:\n\n"
                            "1. **KB Query**: Use `search_knowledge` to check existing entries.\n"
                            "2. **Library Search**: Use `search_books` or `search_within_book` to find sources.\n"
                            "3. **Read & Cache**: Use `get_book_pages_latex` to read the page. The system automatically:\n"
                            "   - Converts the page to high-quality LaTeX (with retry + text fallback)\n"
                            "   - Caches the LaTeX for future use\n"
                            "   - Discovers theorems/definitions and creates proposals for user review\n"
                            "4. **Review Proposals**: Use `list_kb_proposals` to see what's been auto-discovered. The user reviews these in the UI.\n"
                            "5. **Answer**: Present findings from the actual LaTeX content.\n\n"
                            "CRITICAL: Do not use `get_book_pages_latex` to parse the Table of Contents or Index. Always use Search first.\n"
                            "CRITICAL: Be aware of PDF Page Offsets. The printed page number is usually lower than the absolute PDF page index. Use `read_pdf_pages` to peek at a page, see its printed number, calculate the offset difference, and jump to the correct absolute PDF page. Do this at most twice before stopping."
                        )
                    )
                )
            ]
        )
    elif name == "note_creation_workflow":
        request = (arguments or {}).get("source_request", "a specific mathematical source")
        prompt_text = f"""I want you to create or improve a high-fidelity research note based on this request: {request}

Follow this exact multi-phase protocol:

### PHASE 1: RESEARCH & PROPOSAL (The "Zwischenschritt")
1. **Locate & Extract**: 
   - Find the book(s) using `search_books`.
   - Use `get_book_pages_latex` to retrieve high-quality, reusable LaTeX for the relevant pages.
2. **Analysis**: Compare the source material with any existing notes if applicable.
3. **The Proposal**: Stop and present a clear summary to the user:
   - **Title & Metadata**: Proposed title, tags, MSC code, and book links.
   - **Content Strategy**: What will be included in the note? (Definitions, Proofs, Intuition).
   - **Structure**: How the Markdown and LaTeX will be organized. Note: Markdown should be formatted as a beautiful, standalone document (like a nice version of the PDF), AVOIDING Obsidian-specific syntax like [[double brackets]].
   - **Wait for Approval**: Do not proceed to Phase 2 until the user gives the green light.

### PHASE 2: AUTONOMOUS EXECUTION (After Approval)
Once approved, execute the following WITHOUT further hints:
1. **File Generation**:
   - Create the note using `create_note`. You MUST provide both `markdown` and `latex` content.
   - Format the Markdown content as a polished scholarly document.
   - The system will automatically place technical metadata in a footer at the end of the file for portability.
   - The system will automatically generate the `.md` and `.tex` files.
2. **Metadata & Linking**:
   - Use `add_note_book_relation` to link the note to the primary source book and page.
   - Ensure the `tags`, `msc`, and `title` are set during creation or updated via `update_note_metadata`.
3. **Compilation**:
   - Immediately call `compile_note` to generate the `.pdf` version.
4. **Final Delivery**:
   - Confirm the Note ID and verify that all three formats (MD, LaTeX, PDF) are active and correctly linked.

IMPORTANT: Aim for the highest scholarly standard. The note should be a permanent, high-fidelity artifact.
"""
        return GetPromptResult(
            description=f"High-fidelity note creation protocol for {request}",
            messages=[PromptMessage(role="user", content=TextContent(type="text", text=prompt_text))]
        )
    
    raise ValueError(f"Unknown prompt: {name}")

# --- Tool Definitions ---

@app.list_tools()
async def list_tools() -> list[Tool]:
    """List all available tools."""
    return [
        Tool(
            name="search_books",
            description=(
                "Search the mathematical library using hybrid vector + full-text search. "
                "Supports optional AI-powered query expansion and result reranking. "
                "Returns books and papers with metadata, snippets, and relevance scores."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (e.g., 'linear algebra', 'topology')"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return",
                        "default": 10
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Pagination offset (start index)",
                        "default": 0
                    },
                    "use_fts": {
                        "type": "boolean",
                        "description": "Enable full-text search (BM25)",
                        "default": True
                    },
                    "use_vector": {
                        "type": "boolean",
                        "description": "Enable vector similarity search",
                        "default": True
                    },
                    "use_rerank": {
                        "type": "boolean",
                        "description": "Enable Gemini 2.0 AI reranking (slower, higher quality)",
                        "default": False
                    },
                    "use_translate": {
                        "type": "boolean",
                        "description": "Enable AI query expansion with mathematical synonyms",
                        "default": False
                    },
                    "field": {
                        "type": "string",
                        "enum": ["all", "title", "author", "index"],
                        "description": "Target specific field (index search is highly recommended for terms)",
                        "default": "all"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_book_details",
            description=(
                "Retrieve comprehensive metadata for a specific book, including page count, "
                "summary, MSC classification, and similar books. Essential for probing offsets."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {
                        "type": "integer",
                        "description": "Book ID from search results"
                    }
                },
                "required": ["book_id"]
            }
        ),
        Tool(
            name="read_pdf_pages",
            description=(
                "Extract raw, unformatted text from PDF page ranges. "
                "FREE/COST-EFFICIENT. Use this to verify page offsets (finding the printed page number) "
                "before using the AI-powered 'get_book_pages_latex'.\n"
                "WARNING: DO NOT use this to blindly read the entire Table of Contents. Use 'search_within_book' instead."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {
                        "type": "integer",
                        "description": "Book ID"
                    },
                    "pages": {
                        "type": "string",
                        "description": "Page range (e.g., '10', '10-15', '10,12,15')"
                    }
                },
                "required": ["book_id", "pages"]
            }
        ),
        Tool(
            name="convert_pdf_to_note",
            description=(
                "DEPRECATED: Use 'get_book_pages_latex' for research and content extraction. "
                "This tool creates a permanent research note from PDF pages. Use it ONLY if you "
                "specifically want to create a new, standalone entry in the notes database."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {
                        "type": "integer",
                        "description": "Book ID"
                    },
                    "pages": {
                        "type": "string",
                        "description": "Page range (e.g., '10', '10-15')"
                    }
                },
                "required": ["book_id", "pages"]
            }
        ),
        Tool(
            name="get_book_pages_latex",
            description=(
                "REUSABLE HIGH-QUALITY LATEX: Retrieve or trigger AI conversion of book pages into beautiful LaTeX. "
                "WARNING: DO NOT use this tool on Table of Contents (TOC) pages or the Index. "
                "Using this on TOC pages wastes massive AI resources and hallucinate garbage Knowledge Base proposals. "
                "Only use this tool ONCE YOU ALREADY KNOW the exact page number that contains the actual theorem or math content you need."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer"},
                    "pages": {"type": "string", "description": "Page range (e.g., '10-12')"},
                    "refresh": {"type": "boolean", "description": "Force a new AI conversion even if cached", "default": False},
                    "min_quality": {"type": "number", "description": "Minimum acceptable quality score (0.0-1.0)", "default": 0.7}
                },
                "required": ["book_id", "pages"]
            }
        ),
        Tool(
            name="trigger_ingestion",
            description=(
                "Trigger the book ingestion pipeline to process new PDFs and DjVu files. "
                "This admin tool scans the 'Unsorted' directory, extracts metadata using Gemini, "
                "performs deduplication, and routes files to the appropriate library folders."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "dry_run": {
                        "type": "boolean",
                        "description": "Preview changes without executing (recommended: true)",
                        "default": True
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="get_book_toc",
            description=(
                "Retrieve the structured Table of Contents (TOC) for a book. "
                "Use this to understand the book's structure and finding logical page numbers."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {
                        "type": "integer",
                        "description": "Book ID"
                    }
                },
                "required": ["book_id"]
            }
        ),
        Tool(
            name="get_system_state",
            description=(
                "Retrieve the current state of the MathStudio Web UI. "
                "Tells you which book the user is currently looking at or which action was last performed."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="update_metadata",
            description=(
                "Update the metadata for a specific book. "
                "Use this to fix typos, update summaries, or apply AI-suggested metadata."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer", "description": "The ID of the book to update"},
                    "title": {"type": "string"},
                    "author": {"type": "string"},
                    "publisher": {"type": "string"},
                    "year": {"type": "integer"},
                    "isbn": {"type": "string"},
                    "msc_class": {"type": "string"},
                    "summary": {"type": "string"},
                    "tags": {"type": "string"},
                    "level": {"type": "string"},
                    "audience": {"type": "string"}
                },
                "required": ["book_id"]
            }
        ),
        Tool(
            name="deep_index_book",
            description=(
                "Perform page-level indexing for a specific book. This enables highly accurate "
                "search within the book's content. Use this when you need to find specific "
                "definitions or theorems in a book that doesn't have a reliable TOC."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {
                        "type": "integer",
                        "description": "Book ID"
                    }
                },
                "required": ["book_id"]
            }
        ),
        Tool(
            name="search_within_book",
            description=(
                "Search for a term or phrase within a specific book. Returns page numbers and snippets. "
                "For best results, run 'deep_index_book' first if the book hasn't been deep-indexed."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {
                        "type": "integer",
                        "description": "Book ID"
                    },
                    "query": {
                        "type": "string",
                        "description": "Term or phrase to search for"
                    }
                },
                "required": ["book_id", "query"]
            }
        ),
        Tool(
            name="reindex_book",
            description=(
                "Trigger AI-driven reconstruction of a book's structure. "
                "Use this when the Table of Contents (TOC) is missing or the Back-of-Book Index is empty. "
                "Modes:\n"
                "- 'toc': Reconstructs the TOC from the first 20 pages (using Gemini).\n"
                "- 'index': Reconstructs the Index from the last 50 pages (using Gemini).\n"
                "- 'auto': Performs both."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer", "description": "Book ID"},
                    "mode": {
                        "type": "string",
                        "enum": ["toc", "index", "auto"],
                        "default": "auto"
                    }
                },
                "required": ["book_id"]
            }
        ),
        Tool(
            name="browse_library",
            description="Browse library by metadata filters: author, msc, year, keyword.",
            inputSchema={
                "type": "object",
                "properties": {
                    "author": {"type": "string"},
                    "msc": {"type": "string", "description": "MSC code (e.g. '11', '11R', '11R23')"},
                    "year": {"type": "integer"},
                    "keyword": {"type": "string"},
                    "limit": {"type": "integer", "default": 100}
                }
            }
        ),
        Tool(
            name="get_msc_stats",
            description="Returns book counts per MSC code at all levels.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="get_msc_tree",
            description="Retrieve the full MSC 2020 hierarchy.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="scan_bibliography",
            description="Scans book pages for bibliography entries using Vision LLM.",
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer"}
                },
                "required": ["book_id"]
            }
        ),
        Tool(
            name="resolve_citations",
            description="Triggers background resolution of citations for a book.",
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer"}
                },
                "required": ["book_id"]
            }
        ),
        Tool(
            name="list_notes",
            description="List structured notes from the database.",
            inputSchema={
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["transcription", "handwritten", "converted"]},
                    "book_id": {"type": "integer"},
                    "limit": {"type": "integer", "default": 50}
                }
            }
        ),
        Tool(
            name="search_notes",
            description="Full-text search over structured notes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 50}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_note_details",
            description="Retrieve detailed metadata and paths for a specific note.",
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {"type": "integer"}
                },
                "required": ["note_id"]
            }
        ),
        Tool(
            name="get_note_content",
            description="Retrieve the full markdown and latex content of a note.",
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {"type": "integer"}
                },
                "required": ["note_id"]
            }
        ),
        Tool(
            name="update_note_content",
            description="Update the markdown and/or latex content of a note.",
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {"type": "integer"},
                    "markdown": {"type": "string", "description": "New markdown content"},
                    "latex": {"type": "string", "description": "New latex content"}
                },
                "required": ["note_id"]
            }
        ),
        Tool(
            name="update_note_metadata",
            description="Update note metadata such as title, tags, and msc classification.",
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {"type": "integer"},
                    "title": {"type": "string"},
                    "tags": {"type": "string", "description": "Comma-separated tags"},
                    "msc": {"type": "string"}
                },
                "required": ["note_id"]
            }
        ),
        Tool(
            name="get_note_metadata",
            description="Alias for get_note_details. Retrieve note metadata.",
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {"type": "integer"}
                },
                "required": ["note_id"]
            }
        ),
        Tool(
            name="get_note_pdf",
            description="Retrieve information about a note's compiled PDF file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {"type": "integer"}
                },
                "required": ["note_id"]
            }
        ),
        Tool(
            name="add_note_book_relation",
            description="Link a note to a specific book and page number. This creates a persistent connection between a research note and its primary source.",
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {"type": "integer"},
                    "book_id": {"type": "integer"},
                    "page": {"type": "integer", "description": "Optional page number in the book"},
                    "relation_type": {"type": "string", "default": "references"}
                },
                "required": ["note_id", "book_id"]
            }
        ),
        Tool(
            name="create_note",
            description=(
                "Create a new mathematical research note (essay, derivation, synthesis). "
                "Automatically triggers PDF compilation if LaTeX is provided. "
                "FOR ATOMIC MATHEMATICAL FACTS (Definitions, Theorems), use `ingest_kb_draft` instead."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "A descriptive title for the note"},
                    "markdown": {"type": "string", "description": "High-quality Markdown content (Obsidian-flavored)"},
                    "latex": {"type": "string", "description": "Clean LaTeX code for PDF generation"},
                    "tags": {"type": "string", "description": "Comma-separated keywords"},
                    "msc": {"type": "string", "description": "Likely MSC classification code"},
                    "book_id": {"type": "integer", "description": "Optional ID of the source book"},
                    "compile": {"type": "boolean", "default": True, "description": "Immediately trigger PDF compilation"}
                },
                "required": ["title", "markdown"]
            }
        ),
        Tool(
            name="compile_note",
            description="Trigger LaTeX compilation for a specific note to generate its PDF representation.",
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
            description="Upload an image scan of a handwritten note to transcribe and store.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Local path to the image file"}
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="compile_notes",
            description="Triggers compilation of LaTeX notes into category and master PDFs.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="refresh_book_metadata",
            description="Triggers the Universal Vision-Reflection Pipeline to refresh book metadata.",
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer"}
                },
                "required": ["book_id"]
            }
        ),
        Tool(
            name="preview_metadata_refresh",
            description="Generates a metadata update proposal using the pipeline (no save).",
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer"}
                },
                "required": ["book_id"]
            }
        ),
        Tool(
            name="batch_enrich_books",
            description="Triggers batch enrichment for raw books using external sources.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 50}
                }
            }
        ),
        Tool(
            name="get_library_stats",
            description="Returns general library statistics (total books, categories, publishers).",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="rebuild_fts_index",
            description="Rebuilds the books_fts search index.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="run_sanity_fix",
            description="Runs library sanity checks and attempts to fix common issues.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="manage_wishlist",
            description="Add or list items in the book wishlist.",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["add", "list"]},
                    "title": {"type": "string"},
                    "author": {"type": "string"},
                    "doi": {"type": "string"}
                },
                "required": ["action"]
            }
        ),
        Tool(
            name="open_external_file",
            description="Opens a file using the system's default handler (Desktop mode).",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path from library root"}
                },
                "required": ["path"]
            }
        ),
        Tool(
            name="enrich_book_metadata",
            description=(
                "Connect to zbMATH Open API to enrich a book with professional metadata, "
                "MSC classifications, and expert reviews. Requires a DOI or Zbl ID to be present."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer", "description": "Book ID"}
                },
                "required": ["book_id"]
            }
        ),
        Tool(
            name="manage_bookmarks",
            description=(
                "Manage persistent bookmarks for key pages or problems. "
                "Actions: 'create', 'list', 'delete'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "list", "delete"],
                        "description": "Action to perform"
                    },
                    "book_id": {
                        "type": "integer",
                        "description": "Book ID (required for create/list)"
                    },
                    "page_range": {
                        "type": "string",
                        "description": "Page range (e.g., '10-15') (for create)"
                    },
                    "tags": {
                        "type": "string",
                        "description": "Comma-separated tags (for create/list)"
                    },
                    "notes": {
                        "type": "string",
                        "description": "Notes or comments (for create)"
                    },
                    "bookmark_id": {
                        "type": "integer",
                        "description": "Bookmark ID (required for delete)"
                    }
                },
                "required": ["action"]
            }
        ),
        # --- Knowledge Base Tools ---
        Tool(
            name="search_knowledge",
            description="Search the mathematical knowledge base for theorems, definitions, and concepts. Returns matching concepts with their location counts.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search term (e.g. 'Banach Fixed Point')"},
                    "kind": {"type": "string", "enum": ["definition", "theorem", "lemma", "proposition", "corollary", "example", "axiom", "notation"]},
                    "limit": {"type": "integer", "default": 20}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_concept_details",
            description="Retrieve a concept with all its book locations and cached LaTeX content. Shows where this theorem/definition appears across the library.",
            inputSchema={
                "type": "object",
                "properties": {
                    "concept_id": {"type": "integer"}
                },
                "required": ["concept_id"]
            }
        ),

        Tool(
            name="list_kb_proposals",
            description="List pending auto-discovered theorems/definitions that need human review. These are found during PDF-to-LaTeX conversion.",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "default": "pending", "enum": ["pending", "approved", "merged", "rejected"]},
                    "limit": {"type": "integer", "default": 50}
                }
            }
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Execute a tool."""
    try:
        if name == "search_books":
            return await search_books(arguments)
        elif name == "get_book_details":
            return await get_book_details(arguments)
        elif name == "read_pdf_pages":
            return await read_pdf_pages(arguments)
        elif name == "convert_pdf_to_note":
            return await convert_pdf_to_note(arguments)
        elif name == "get_book_pages_latex":
            return await get_book_pages_latex(arguments)
        elif name == "trigger_ingestion":
            return await trigger_ingestion(arguments)
        elif name == "get_book_toc":
            return await get_book_toc(arguments)
        elif name == "get_system_state":
            return await get_system_state(arguments)
        elif name == "update_metadata":
            return await update_metadata(arguments)
        elif name == "manage_bookmarks":
            return await manage_bookmarks(arguments)
        elif name == "browse_library":
            return await browse_library(arguments)
        elif name == "get_msc_stats":
            return await get_msc_stats(arguments)
        elif name == "get_msc_tree":
            return await get_msc_tree(arguments)
        elif name == "scan_bibliography":
            return await scan_bibliography(arguments)
        elif name == "resolve_citations":
            return await resolve_citations(arguments)
        elif name == "list_notes":
            return await list_notes(arguments)
        elif name == "search_notes":
            return await search_notes(arguments)
        elif name == "get_note_details":
            return await get_note_details(arguments)
        elif name == "get_note_content":
            return await get_note_content(arguments)
        elif name == "update_note_content":
            return await update_note_content(arguments)
        elif name == "update_note_metadata":
            return await update_note_metadata_note(arguments)
        elif name == "get_note_metadata":
            return await get_note_details(arguments)
        elif name == "get_note_pdf":
            return await get_note_pdf(arguments)
        elif name == "add_note_book_relation":
            return await add_note_book_relation(arguments)
        elif name == "create_note":
            return await create_note(arguments)
        elif name == "compile_note":
            return await compile_note(arguments)
        elif name == "upload_note_scan":
            return await upload_note_scan(arguments)
        elif name == "compile_notes":
            return await compile_notes(arguments)
        elif name == "refresh_book_metadata":
            return await refresh_book_metadata(arguments)
        elif name == "preview_metadata_refresh":
            return await preview_metadata_refresh(arguments)
        elif name == "batch_enrich_books":
            return await batch_enrich_books(arguments)
        elif name == "get_library_stats":
            return await get_library_stats(arguments)
        elif name == "rebuild_fts_index":
            return await rebuild_fts_index(arguments)
        elif name == "run_sanity_fix":
            return await run_sanity_fix(arguments)
        elif name == "manage_wishlist":
            return await manage_wishlist(arguments)
        elif name == "open_external_file":
            return await open_external_file(arguments)
        elif name == "reindex_book":
            return await reindex_book(arguments)
        elif name == "enrich_book_metadata":
            return await enrich_book_metadata(arguments)
        elif name == "deep_index_book":
            return await deep_index_book(arguments)
        elif name == "search_within_book":
            return await search_within_book(arguments)
        # --- Knowledge Base Tools ---
        elif name == "search_knowledge":
            return await search_knowledge(arguments)
        elif name == "get_concept_details":
            return await get_concept_details(arguments)

        elif name == "list_kb_proposals":
            return await list_kb_proposals(arguments)
        else:
            raise ValueError(f"Unknown tool: {name}")
    except Exception as e:
        logger.error(f"Tool execution error: {e}", exc_info=True)
        return [TextContent(type="text", text=f"Error: {str(e)}")]


# --- Tool Implementations ---

async def browse_library(args: dict) -> list[TextContent]:
    """Browse the library by metadata."""
    params = {
        "author": args.get("author"),
        "msc": args.get("msc"),
        "year": args.get("year"),
        "keyword": args.get("keyword"),
        "limit": args.get("limit", 100)
    }
    # Filter out None values
    params = {k: v for k, v in params.items() if v is not None}
    
    response = requests.get(f"{API_BASE}/browse", params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    
    results = data.get("results", [])
    if not results:
        return [TextContent(type="text", text="No books found matching the criteria.")]
        
    output = f"Browsing results ({data.get('filter', 'N/A')}):\n\n"
    for i, book in enumerate(results, 1):
        output += f"{i}. **{book['title']}** by {book['author']} (ID: {book['id']})\n"
        
    return [TextContent(type="text", text=output)]


async def get_msc_stats(args: dict) -> list[TextContent]:
    """Get MSC statistics."""
    response = requests.get(f"{API_BASE}/msc-stats", timeout=10)
    response.raise_for_status()
    return [TextContent(type="text", text=json.dumps(response.json(), indent=2))]


async def get_msc_tree(args: dict) -> list[TextContent]:
    """Get full MSC hierarchy."""
    response = requests.get(f"{API_BASE}/msc-tree", timeout=10)
    response.raise_for_status()
    return [TextContent(type="text", text="MSC Tree retrieved (JSON). Use this for classification hierarchy.")]


async def scan_bibliography(args: dict) -> list[TextContent]:
    """Scan book bibliography."""
    book_id = args["book_id"]
    response = requests.post(f"{API_BASE}/tools/bib-scan", json={"book_id": book_id}, timeout=300)
    
    if response.ok:
        # The API returns rendered HTML in some cases, but for MCP we want the data
        # Note: api_v1.py bib_scan_tool currently returns render_template('bib_results.html')
        # This might be a problem for MCP. I should check if it can return JSON.
        # Actually, looking at api_v1.py, it returns render_template.
        # I'll suggest a fix for that later or just return a success message here.
        return [TextContent(type="text", text=f"✓ Bibliography scan triggered for book {book_id}. View results in Web UI or wait for resolution.")]
    else:
        return [TextContent(type="text", text=f"✗ Scan failed: {response.text}")]


async def resolve_citations(args: dict) -> list[TextContent]:
    """Resolve book citations."""
    book_id = args["book_id"]
    response = requests.post(f"{API_BASE}/books/{book_id}/citations/resolve", timeout=300)
    response.raise_for_status()
    return [TextContent(type="text", text=f"✓ Citation resolution completed for book {book_id}.")]


async def list_notes(args: dict) -> list[TextContent]:
    """List structured notes."""
    params = {
        "type": args.get("type"),
        "book_id": args.get("book_id"),
        "limit": args.get("limit", 50)
    }
    response = requests.get(f"{API_BASE}/notes", params=params, timeout=10)
    response.raise_for_status()
    notes = response.json()
    
    if not notes:
        return [TextContent(type="text", text="No notes found.")]
        
    output = "Structured Notes:\n\n"
    for n in notes:
        output += f"- [ID {n['id']}] **{n['title']}** ({n.get('source_type', 'N/A')})\n"
        
    return [TextContent(type="text", text=output)]


async def search_notes(args: dict) -> list[TextContent]:
    """Search structured notes."""
    params = {"q": args["query"], "limit": args.get("limit", 50)}
    response = requests.get(f"{API_BASE}/notes/search", params=params, timeout=10)
    response.raise_for_status()
    results = response.json()
    
    if not results:
        return [TextContent(type="text", text=f"No notes found for '{args['query']}'.")]
        
    output = f"Search results for notes: '{args['query']}':\n\n"
    for r in results:
        output += f"- [ID {r['id']}] **{r['title']}**\n"
        if r.get('snippet'):
            output += f"  Snippet: {r['snippet']}\n"
            
    return [TextContent(type="text", text=output)]


async def get_note_details(args: dict) -> list[TextContent]:
    """Get note details."""
    note_id = args["note_id"]
    response = requests.get(f"{API_BASE}/notes/{note_id}", timeout=10)
    response.raise_for_status()
    n = response.json()
    
    output = f"# {n['title']}\n"
    output += f"ID: {n['id']} | Type: {n['source_type']} | Created: {n['created_at']}\n"
    if n.get('tags'): output += f"Tags: {n['tags']}\n"
    if n.get('msc'): output += f"MSC: {n['msc']}\n"
    output += "\n"
    
    if n.get('markdown_path'):
        output += f"- Markdown: {n['markdown_path']}\n"
    if n.get('latex_path'):
        output += f"- LaTeX: {n['latex_path']}\n"
    if n.get('pdf_path'):
        output += f"- PDF: {n['pdf_path']}\n"
        
    return [TextContent(type="text", text=output)]


async def get_note_content(args: dict) -> list[TextContent]:
    """Get the full content of a note."""
    note_id = args["note_id"]
    response = requests.get(f"{API_BASE}/notes/{note_id}/content", timeout=10)
    response.raise_for_status()
    data = response.json()
    
    output = ""
    if data.get('markdown'):
        output += "### Markdown Content\n"
        output += "```markdown\n"
        output += data['markdown']
        output += "\n```\n\n"
        
    if data.get('latex'):
        output += "### LaTeX Content\n"
        output += "```latex\n"
        output += data['latex']
        output += "\n```\n"
        
    if not output:
        return [TextContent(type="text", text="Note has no markdown or latex content.")]
        
    return [TextContent(type="text", text=output)]


async def update_note_content(args: dict) -> list[TextContent]:
    """Update note content."""
    note_id = args["note_id"]
    payload = {
        "markdown": args.get("markdown"),
        "latex": args.get("latex")
    }
    response = requests.patch(f"{API_BASE}/notes/{note_id}/content", json=payload, timeout=10)
    response.raise_for_status()
    return [TextContent(type="text", text=f"✓ Content for note {note_id} updated successfully.")]


async def update_note_metadata_note(args: dict) -> list[TextContent]:
    """Update note metadata."""
    note_id = args.pop("note_id")
    response = requests.patch(f"{API_BASE}/notes/{note_id}/metadata", json=args, timeout=10)
    response.raise_for_status()
    return [TextContent(type="text", text=f"✓ Metadata for note {note_id} updated successfully.")]


async def get_note_pdf(args: dict) -> list[TextContent]:
    """Get note PDF information."""
    note_id = args["note_id"]
    response = requests.get(f"{API_BASE}/notes/{note_id}", timeout=10)
    response.raise_for_status()
    n = response.json()
    
    if not n.get('pdf_path'):
        return [TextContent(type="text", text=f"Note {note_id} does not have a compiled PDF yet. Use 'compile_notes' to generate it.")]
        
    return [TextContent(type="text", text=f"PDF Path: {n['pdf_path']}\nYou can download it via: {API_BASE}/notes/{note_id}/pdf")]


async def add_note_book_relation(args: dict) -> list[TextContent]:
    """Link a note to a book."""
    note_id = args["note_id"]
    payload = {
        "book_id": args["book_id"],
        "page": args.get("page"),
        "type": args.get("relation_type", "references")
    }
    response = requests.post(f"{API_BASE}/notes/{note_id}/books", json=payload, timeout=10)
    response.raise_for_status()
    return [TextContent(type="text", text=f"✓ Persistent connection created: Note {note_id} linked to Book {args['book_id']}.")]


async def create_note(args: dict) -> list[TextContent]:
    """Create a new note."""
    response = requests.post(f"{API_BASE}/notes", json=args, timeout=30)
    response.raise_for_status()
    data = response.json()
    return [TextContent(type="text", text=f"✓ Note created successfully (ID: {data['id']}).")]


async def compile_note(args: dict) -> list[TextContent]:
    """Compile a note to PDF."""
    note_id = args["note_id"]
    response = requests.post(f"{API_BASE}/notes/{note_id}/compile", timeout=120)
    
    if response.ok:
        data = response.json()
        return [TextContent(type="text", text=f"✓ Compilation successful. PDF generated at: {data['pdf_path']}")]
    else:
        error_msg = response.json().get('error', 'Unknown error')
        return [TextContent(type="text", text=f"✗ Compilation failed: {error_msg}")]


async def upload_note_scan(args: dict) -> list[TextContent]:
    """Upload and transcribe a note scan."""
    file_path = Path(args["file_path"])
    if not file_path.exists():
        return [TextContent(type="text", text=f"Error: File not found at {file_path}")]
        
    with open(file_path, 'rb') as f:
        files = {'file': (file_path.name, f, 'image/jpeg')}
        response = requests.post(f"{API_BASE}/notes/upload", files=files, timeout=60)
        
    if response.ok:
        data = response.json()
        return [TextContent(type="text", text=f"✓ Note uploaded and transcribed (ID: {data['id']}).\n\nTranscription:\n{data['transcription']}")]
    else:
        return [TextContent(type="text", text=f"✗ Upload failed: {response.text}")]


async def compile_notes(args: dict) -> list[TextContent]:
    """Compile all notes."""
    response = requests.post(f"{API_BASE}/notes/compile", timeout=300)
    response.raise_for_status()
    data = response.json()
    return [TextContent(type="text", text=f"✓ Compilation complete: {data.get('message', 'Check logs')}")]


async def refresh_book_metadata(args: dict) -> list[TextContent]:
    """Refresh book metadata via pipeline."""
    book_id = args["book_id"]
    response = requests.post(f"{API_BASE}/books/{book_id}/metadata/refresh", timeout=180)
    response.raise_for_status()
    return [TextContent(type="text", text=f"✓ Metadata refreshed for book {book_id}.")]


async def preview_metadata_refresh(args: dict) -> list[TextContent]:
    """Preview metadata refresh."""
    book_id = args["book_id"]
    response = requests.post(f"{API_BASE}/books/{book_id}/metadata/refresh/preview", timeout=180)
    response.raise_for_status()
    return [TextContent(type="text", text=json.dumps(response.json(), indent=2))]


async def batch_enrich_books(args: dict) -> list[TextContent]:
    """Batch enrich books."""
    payload = {"limit": args.get("limit", 50)}
    response = requests.post(f"{API_BASE}/admin/enrich/batch", json=payload, timeout=600)
    response.raise_for_status()
    return [TextContent(type="text", text=f"✓ Batch enrichment completed. {json.dumps(response.json(), indent=2)}")]


async def get_library_stats(args: dict) -> list[TextContent]:
    """Get library statistics."""
    response = requests.get(f"{API_BASE}/admin/stats", timeout=10)
    response.raise_for_status()
    return [TextContent(type="text", text=json.dumps(response.json(), indent=2))]


async def rebuild_fts_index(args: dict) -> list[TextContent]:
    """Rebuild FTS index."""
    response = requests.post(f"{API_BASE}/admin/indexer", timeout=300)
    response.raise_for_status()
    return [TextContent(type="text", text=f"✓ FTS index rebuilt: {response.json().get('message')}")]


async def run_sanity_fix(args: dict) -> list[TextContent]:
    """Run sanity fix."""
    response = requests.post(f"{API_BASE}/admin/sanity/fix", timeout=300)
    response.raise_for_status()
    return [TextContent(type="text", text=f"✓ Sanity fix completed. {json.dumps(response.json(), indent=2)}")]


async def manage_wishlist(args: dict) -> list[TextContent]:
    """Manage wishlist."""
    action = args["action"]
    if action == "add":
        payload = {
            "title": args["title"],
            "author": args.get("author"),
            "doi": args.get("doi")
        }
        response = requests.post(f"{API_BASE}/wishlist", json=payload, timeout=10)
        response.raise_for_status()
        return [TextContent(type="text", text=f"✓ Added to wishlist (ID: {response.json().get('id')})")]
    else:
        # Note: There isn't a dedicated GET /wishlist in api_v1.py yet, but let's assume it exists or use stats
        return [TextContent(type="text", text="Listing wishlist items is currently only available via Web UI or direct DB access.")]


async def open_external_file(args: dict) -> list[TextContent]:
    """Open file externally."""
    params = {"path": args["path"]}
    response = requests.get(f"{API_BASE}/tools/open-external", params=params, timeout=10)
    response.raise_for_status()
    return [TextContent(type="text", text=f"✓ Opened {args['path']} externally.")]


async def search_books(args: dict) -> list[TextContent]:
    """Search the library."""
    params = {
        "q": args["query"],
        "limit": args.get("limit", 10),
        "offset": args.get("offset", 0),
        "fts": "true" if args.get("use_fts", True) else "false",
        "vec": "true" if args.get("use_vector", True) else "false",
        "rank": "true" if args.get("use_rerank", False) else "false",
        "trans": "true" if args.get("use_translate", False) else "false",
        "field": args.get("field", "all"),
    }
    
    response = requests.get(f"{API_BASE}/search", params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    
    # Format results for LLM consumption
    results = data.get("results", [])
    total = data.get("total_count", 0)
    
    if not results:
        return [TextContent(type="text", text=f"No results found for '{args['query']}'.")]
    
    output = f"Found {total} results for '{args['query']}'.\n\n"
    for i, book in enumerate(results, 1):
        output += f"{i}. **{book['title']}** by {book['author']}\n"
        output += f"   - ID: {book['id']}\n"
        output += f"   - Score: {book.get('score', 'N/A'):.2f}\n"
        if book.get('year'):
            output += f"   - Year: {book['year']}\n"
        if book.get('summary'):
            output += f"   - Summary: {book['summary'][:150]}...\n"
        output += "\n"
    
    return [TextContent(type="text", text=output)]


async def reindex_book(args: dict) -> list[TextContent]:
    """Trigger AI re-indexing (TOC or Index)."""
    book_id = args["book_id"]
    mode = args.get("mode", "auto")
    
    response = requests.post(f"{API_BASE}/books/{book_id}/reindex/{mode}", timeout=300)
    
    if response.ok:
        data = response.json()
        results = data.get("results", {})
        output = f"✓ Re-indexing ({mode}) triggered successfully.\n"
        for k, v in results.items():
            status = "Success" if (isinstance(v, dict) and v.get('success')) or (isinstance(v, bool) and v) else "Check Logs"
            output += f"- {k.upper()}: {status}\n"
        return [TextContent(type="text", text=output)]
    else:
        error_msg = response.json().get('error', 'Unknown error')
        return [TextContent(type="text", text=f"✗ Re-indexing failed: {error_msg}")]


async def enrich_book_metadata(args: dict) -> list[TextContent]:
    """Trigger zbMATH enrichment via API."""
    book_id = args["book_id"]
    response = requests.post(f"{API_BASE}/books/{book_id}/enrich", timeout=60)
    
    if response.ok:
        data = response.json()
        return [TextContent(type="text", text=f"✓ Enrichment successful for Zbl {data.get('zbl_id')}. Status: {data.get('status')}, Trust Score: {data.get('trust_score'):.2f}")]
    else:
        error_msg = response.json().get('error', 'Unknown error')
        return [TextContent(type="text", text=f"✗ Enrichment failed: {error_msg}")]


async def get_book_details(args: dict) -> list[TextContent]:
    """Get detailed book information."""
    book_id = args["book_id"]
    response = requests.get(f"{API_BASE}/books/{book_id}", timeout=10)
    response.raise_for_status()
    data = response.json()
    
    output = f"# {data['title']}\n"
    output += f"Author: {data['author']}\n"
    output += f"ID: {data['id']} | Pages: {data.get('page_count', 'Unknown')}\n"
    
    # Indexing Status
    status = []
    if data.get('has_index'): status.append("Back-of-Book Index ✓")
    else: status.append("Back-of-Book Index ✗ (Recommend 'reindex_book')")
    
    if data.get('has_toc'): status.append("Table of Contents ✓")
    else: status.append("Table of Contents ✗ (Recommend 'reindex_book')")
        
    if data.get('is_deep_indexed'):
        status.append("Page-level FTS ✓")
    else:
        status.append("Page-level FTS ✗ (Recommend 'deep_index_book')")
        
    output += "Status: " + " | ".join(status) + "\n"
    
    page_offset = data.get('page_offset', 0)
    if page_offset:
        output += f"Page Offset: {page_offset} (PDF Page 1 = Printed Page {1 - page_offset})\n"
    
    output += "\n"
    
    if data.get('summary'):
        output += f"## Summary\n{data['summary']}\n\n"
    
    if data.get('msc_class'):
        output += f"MSC Classification: {data['msc_class']}\n"
        
    if data.get('tags'):
        output += f"Tags: {data['tags']}\n"

    # Expert metadata from zbMATH cache
    if data.get('keywords'):
        output += f"Expert Keywords: {data['keywords']}\n"
    
    if data.get('zb_review'):
        output += f"\n## Expert Review (zbMATH)\n{data['zb_review'][:500]}...\n"

    # Bibliography Summary
    if data.get('bibliography'):
        output += f"\n## Bibliography ({len(data['bibliography'])} entries)\n"
        output += "Use 'scan_bibliography' or 'resolve_citations' to manage.\n"

    if data.get('similar_books'):
        output += "\n## Similar Books\n"
        for b in data['similar_books']:
            output += f"- {b['title']} (ID: {b['id']})\n"
            
    return [TextContent(type="text", text=output)]


async def read_pdf_pages(args: dict) -> list[TextContent]:
    """Extract raw text from PDF ranges."""
    payload = {
        "book_id": args["book_id"],
        "pages": args["pages"]
    }
    
    response = requests.post(f"{API_BASE}/tools/pdf-to-text", json=payload, timeout=30)
    response.raise_for_status()
    data = response.json()
    
    if data.get("success"):
        return [TextContent(type="text", text=data.get("text", ""))]
    else:
        return [TextContent(type="text", text=f"Error: {data.get('error', 'Unknown error')}")]


async def convert_pdf_to_note(args: dict) -> list[TextContent]:
    """Convert PDF range to notes."""
    payload = {
        "book_id": args["book_id"],
        "pages": args["pages"]
    }
    
    response = requests.post(
        f"{API_BASE}/tools/pdf-to-note",
        json=payload,
        timeout=180
    )
    response.raise_for_status()
    data = response.json()
    
    if data.get("success"):
        filename = data.get("filename", "unknown")
        content = data.get("content", "")
        return [TextContent(
            type="text",
            text=f"✓ Note created: {filename}\n\nContent:\n{content}"
        )]
    else:
        error = data.get("error", "Unknown error")
        return [TextContent(type="text", text=f"✗ Conversion failed: {error}")]


async def get_book_pages_latex(args: dict) -> list[TextContent]:
    """Retrieve high-quality reusable LaTeX for book pages."""
    params = {
        "pages": args["pages"],
        "refresh": "true" if args.get("refresh") else "false",
        "min_quality": args.get("min_quality", 0.7)
    }
    
    response = requests.get(
        f"{API_BASE}/books/{args['book_id']}/pages/latex",
        params=params,
        timeout=300
    )
    response.raise_for_status()
    data = response.json()
    
    results = data.get("pages", [])
    output = f"## Reusable LaTeX for Book {args['book_id']} (Pages: {args['pages']})\n\n"
    
    for r in results:
        p = r['page']
        if 'error' in r:
            output += f"### Page {p}\nError: {r['error']}\n\n"
        else:
            output += f"### Page {p} (Quality: {r.get('quality', 0):.2f}, Source: {r.get('source', 'unknown')})\n"
            output += "```latex\n"
            output += r.get('latex') or "% No LaTeX recovered for this page"
            output += "\n```\n\n"
            
    return [TextContent(type="text", text=output)]


async def trigger_ingestion(args: dict) -> list[TextContent]:
    """Trigger book ingestion pipeline."""
    payload = {"dry_run": args.get("dry_run", True)}
    
    response = requests.post(
        f"{API_BASE}/admin/ingest",
        json=payload,
        timeout=300
    )
    response.raise_for_status()
    data = response.json()
    
    if data.get("success"):
        mode = "DRY RUN" if payload["dry_run"] else "EXECUTION"
        stdout = data.get("stdout", "")
        return [TextContent(
            type="text",
            text=f"✓ Ingestion {mode} completed.\n\nOutput:\n{stdout[:1000]}"
        )]
    else:
        stderr = data.get("stderr", "Unknown error")
        return [TextContent(type="text", text=f"✗ Ingestion failed:\n{stderr[:500]}")]


async def get_book_toc(args: dict) -> list[TextContent]:
    """Get book TOC from API."""
    book_id = args["book_id"]
    response = requests.get(f"{API_BASE}/books/{book_id}/toc", timeout=10)
    response.raise_for_status()
    data = response.json()
    
    toc = data.get("toc", [])
    if not toc:
        return [TextContent(type="text", text="No Table of Contents available.")]
        
    output = f"Table of Contents for Book {book_id}:\n\n"
    for item in toc:
        # Format from services/search.py: 
        # (title, level, page, msc, topics)
        if isinstance(item, (list, tuple)) and len(item) >= 3:
            title = item[0]
            level = item[1]
            page = item[2]
            indent = "  " * level
            output += f"{indent}- {title} (p. {page})\n"
        # Fallback for other potential formats
        elif isinstance(item, dict):
            title = item.get('title', 'Untitled')
            page = item.get('pdf_page') or item.get('page', 'N/A')
            level = item.get('level', 0)
            indent = "  " * level
            output += f"{indent}- {title} (p. {page})\n"
            
    return [TextContent(type="text", text=output)]


async def update_metadata(args: dict) -> list[TextContent]:
    """Updates a book's metadata via API."""
    book_id = args.pop("book_id")
    
    response = requests.patch(
        f"{API_BASE}/books/{book_id}/metadata", 
        json=args, 
        timeout=10
    )
    
    if response.ok:
        return [TextContent(type="text", text=f"✓ Metadata for book {book_id} updated successfully.")]
    else:
        error_msg = response.json().get('error', 'Unknown error')
        return [TextContent(type="text", text=f"✗ Metadata update failed: {error_msg}")]


async def get_system_state(args: dict) -> list[TextContent]:
    """Retrieve the current system state (what the user is looking at in the UI)."""
    # The state file is located in the parent directory of the mcp_server folder
    state_path = Path(__file__).parent.parent / "current_state.json"
    
    if not state_path.exists():
        return [TextContent(type="text", text="No active system state found. The user might not be using the Web UI right now.")]
    
    try:
        with open(state_path, "r") as f:
            state = json.load(f)
        
        output = "### Current System State (Web UI)\n"
        output += f"- **Action**: {state.get('action')}\n"
        output += f"- **Timestamp**: {state.get('timestamp')}\n"
        
        if state.get("book_id"):
            output += f"- **Active Book ID**: {state.get('book_id')}\n"
            
        extra = state.get("extra", {})
        if extra:
            for k, v in extra.items():
                output += f"- **{k.capitalize()}**: {v}\n"
                
        return [TextContent(type="text", text=output)]
    except Exception as e:
        return [TextContent(type="text", text=f"Error reading system state: {str(e)}")]


async def deep_index_book(args: dict) -> list[TextContent]:
    """Trigger deep indexing for a book."""
    book_id = args["book_id"]
    response = requests.post(f"{API_BASE}/books/{book_id}/deep-index", timeout=300)
    
    if response.ok:
        data = response.json()
        return [TextContent(type="text", text=f"✓ Deep indexing complete: {data['message']}")]
    else:
        error_msg = response.json().get('error', 'Unknown error')
        return [TextContent(type="text", text=f"✗ Deep indexing failed: {error_msg}")]


async def search_within_book(args: dict) -> list[TextContent]:
    """Search within a book."""
    book_id = args["book_id"]
    query = args["query"]
    
    params = {"q": query}
    response = requests.get(f"{API_BASE}/books/{book_id}/search", params=params, timeout=30)
    
    if response.ok:
        data = response.json()
        matches = data.get("matches", [])
        is_deep = data.get("is_deep_indexed", False)
        
        if not matches:
            return [TextContent(type="text", text=f"No matches found for '{query}' in book {book_id}.")]
            
        output = f"Matches for '{query}' in book {book_id} "
        output += "(Deep Indexed):\n\n" if is_deep else "(Snippet Based - Recommend 'deep_index_book'):\n\n"
        
        for m in matches:
            output += f"- p. {m['page']}: {m['snippet']}\n"
            
        return [TextContent(type="text", text=output)]
    else:
        error_msg = response.json().get('error', 'Unknown error')
        return [TextContent(type="text", text=f"✗ Search within book failed: {error_msg}")]


async def manage_bookmarks(args: dict) -> list[TextContent]:
    """Manage bookmarks."""
    action = args["action"]
    
    if action == "create":
        payload = {
            "book_id": args.get("book_id"),
            "page_range": args.get("page_range"),
            "tags": args.get("tags"),
            "notes": args.get("notes")
        }
        response = requests.post(f"{API_BASE}/bookmarks", json=payload, timeout=5)
        response.raise_for_status()
        data = response.json()
        return [TextContent(type="text", text=f"✓ Bookmark created (ID: {data['id']})")]
        
    elif action == "list":
        params = {}
        if args.get("book_id"): params["book_id"] = args["book_id"]
        if args.get("tags"): params["tag"] = args["tags"]
        
        response = requests.get(f"{API_BASE}/bookmarks", params=params, timeout=5)
        response.raise_for_status()
        bookmarks = response.json()
        
        if not bookmarks:
            return [TextContent(type="text", text="No bookmarks found.")]
            
        output = "Bookmarks:\n\n"
        for b in bookmarks:
            output += f"[ID {b['id']}] {b['book_title']} (p. {b['page_range']})\n"
            if b.get('tags'): output += f"  Tags: {b['tags']}\n"
            if b.get('notes'): output += f"  Notes: {b['notes']}\n"
            output += "\n"
        return [TextContent(type="text", text=output)]
        
    elif action == "delete":
        bid = args.get("bookmark_id")
        if not bid: return [TextContent(type="text", text="Error: bookmark_id required for delete.")]
        
        response = requests.delete(f"{API_BASE}/bookmarks/{bid}", timeout=5)
        response.raise_for_status()
        return [TextContent(type="text", text=f"✓ Bookmark {bid} deleted.")]
        
    return [TextContent(type="text", text=f"Unknown action: {action}")]


# --- Knowledge Base Handlers ---

async def search_knowledge(args: dict) -> list[TextContent]:
    params = {"q": args["query"], "limit": args.get("limit", 20)}
    if args.get("kind"): params["kind"] = args["kind"]
    resp = requests.get(f"{API_BASE}/kb/concepts/search", params=params, timeout=10)
    data = resp.json()
    if not data: return [TextContent(type="text", text="No knowledge base entries found.")]
    output = f"Found {len(data)} results:\n\n"
    for item in data:
        name = item.get('name', item.get('concept_name', 'Unknown'))
        locs = item.get('location_count', 0)
        output += f"- **{name}** ({item.get('kind')}) — {locs} location(s) [ID: {item.get('id')}]\n"
    return [TextContent(type="text", text=output)]

async def get_concept_details(args: dict) -> list[TextContent]:
    resp = requests.get(f"{API_BASE}/kb/concepts/{args['concept_id']}", timeout=10)
    if not resp.ok: return [TextContent(type="text", text="Concept not found.")]
    c = resp.json()
    output = f"# {c['name']} ({c['kind']})\n"
    if c.get('aliases'): output += f"Aliases: {', '.join(c['aliases'])}\n"
    if c.get('domain'): output += f"Domain: {c['domain']}\n\n"
    
    output += f"## Found in {len(c['entries'])} book(s)\n\n"
    for e in c['entries']:
        book_info = e.get('book_title', 'Unknown Book')
        author = e.get('book_author', '')
        if author: book_info = f"{author} — {book_info}"
        page = e.get('page_start', '?')
        output += f"### {book_info}, p. {page}\n"
        if e.get('has_latex') and e.get('latex_content'):
            output += f"```latex\n{e['latex_content'][:2000]}\n```\n"
        elif e.get('statement'):
            output += f"Statement: {e['statement'][:500]}\n"
        else:
            output += f"*(LaTeX not yet cached for this page)*\n"
        output += "\n"
    
    return [TextContent(type="text", text=output)]


async def list_kb_proposals(args: dict) -> list[TextContent]:
    params = {"status": args.get("status", "pending"), "limit": args.get("limit", 50)}
    resp = requests.get(f"{API_BASE}/kb/proposals", params=params, timeout=10)
    data = resp.json()
    if not data: return [TextContent(type="text", text=f"No proposals found with status '{params['status']}'.")]
    output = f"Pending Proposals ({len(data)}):\n\n"
    for p in data:
        merge_note = ""
        if p.get('merge_target_name'):
            merge_note = f" → suggested merge with '{p['merge_target_name']}'"
        output += f"- [ID {p['id']}] **{p['concept_name']}** ({p['kind']}) — {p.get('book_title', 'Unknown')}, p.{p['page_number']}{merge_note}\n"
    output += "\n*Review and approve/merge/reject these proposals in the Knowledge Base UI.*"
    return [TextContent(type="text", text=output)]


# --- Resource Definitions ---

@app.list_resources()
async def list_resources() -> list[Resource]:
    """List available resources."""
    return [
        Resource(
            uri="mathstudio://api/docs",
            name="API Documentation",
            mimeType="text/markdown",
            description="Complete API documentation with endpoints, parameters, and examples"
        ),
        Resource(
            uri="mathstudio://library/stats",
            name="Library Statistics",
            mimeType="application/json",
            description="Current library statistics (total books, papers, notes)"
        )
    ]


@app.read_resource()
async def read_resource(uri: str) -> str:
    """Read a resource."""
    if uri == "mathstudio://api/docs":
        return """# MathStudio API Documentation

## 1. Discovery & Search
- `search_books(query, ...)`: Hybrid search (Vector + FTS).
- `browse_library(author, msc, year, ...)`: Filtered browsing.
- `get_msc_stats()`: Distribution of books by MSC code.
- `get_msc_tree()`: The full MSC 2020 classification tree.

## 2. Book Processing & Structure
- `get_book_details(book_id)`: Comprehensive metadata and flags.
- `get_book_toc(book_id)`: Structured Table of Contents.
- `reindex_book(book_id, mode)`: AI-driven TOC/Index reconstruction.
- `deep_index_book(book_id)`: Enable page-level FTS search.
- `search_within_book(book_id, query)`: Search content or deep index.

## 3. Notes & Vision
- `list_notes(type, book_id, limit)`: List all notes.
- `search_notes(query)`: Full-text search over note content.
- `get_note_details(note_id)`: Metadata and paths for a note.
- `get_note_content(note_id)`: Retrieve MD and LaTeX content.
- `update_note_content(note_id, markdown, latex)`: Write new content.
- `update_note_metadata(note_id, title, tags, msc)`: Update metadata.
- `create_note(title, markdown, latex, ...)`: Create a note from scratch.
- `add_note_book_relation(note_id, book_id, page)`: Link note to a book source.
- `compile_note(note_id)`: Compile a single note to PDF.
- `get_note_pdf(note_id)`: Get path to compiled PDF.
- `upload_note_scan(file_path)`: Transcribe handwritten notes.
- `convert_pdf_to_note(book_id, pages)`: AI-transcribe book segments.
- `get_book_pages_latex(book_id, pages, refresh, min_quality)`: Get reusable high-quality LaTeX fragments.
- `read_pdf_pages(book_id, pages)`: Raw text extraction (for verification).
- `compile_notes()`: Compile all LaTeX notes to PDFs.

## 4. Bibliography
- `scan_bibliography(book_id)`: Vision-first extraction of citations.
- `resolve_citations(book_id)`: Resolve citations to library or zbMATH.

## 5. Administration
- `trigger_ingestion(dry_run)`: Process new files in Unsorted.
- `get_library_stats()`: General library health and distribution.
- `run_sanity_fix()`: Attempt to fix database/path issues.
"""
    elif uri == "mathstudio://library/stats":
        response = requests.get(f"{API_BASE}/admin/stats", timeout=10)
        response.raise_for_status()
        return json.dumps(response.json(), indent=2)
    else:
        raise ValueError(f"Unknown resource: {uri}")


# --- Main Entry Point ---

async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
