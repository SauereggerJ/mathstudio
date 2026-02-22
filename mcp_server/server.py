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
    """List available educational/research prompts."""
    return [
        Prompt(
            name="research_concept",
            description="Command the scholarly agent to research and synthesize a mathematical concept across multiple library sources.",
            arguments=[
                {
                    "name": "concept_name",
                    "description": "The mathematical concept to research (e.g. 'compactness', 'Banach-Steinhaus theorem')",
                    "required": True
                }
            ]
        )
    ]

@app.get_prompt()
async def get_prompt(name: str, arguments: dict | None) -> GetPromptResult:
    """Return the structured instructions for a given prompt."""
    if name != "research_concept":
        raise ValueError(f"Unknown prompt: {name}")

    concept = (arguments or {}).get("concept_name", "a complex mathematical concept")
    
    prompt_text = f"""I want you to research the mathematical concept: {concept}

Follow these exact steps:
1. Search our MathStudio library for the best 3-4 sources covering this concept. Try to find sources with different scopes (e.g., topology vs real analysis).
2. Create the concept in the Knowledge Base using `add_concept`.
3. Extract the formal definitions or theorems from the books using `ingest_from_page` or by reading the pages and using `add_entry`. Include the exact source text and page numbers.
4. Compare the formulations. Are they equivalent? Do some require a metric space while others only need a topological space?
5. Write a comprehensive, scholarly synthesis of the concept. Explain the intuition, state the formal variants, and trace the conceptual hierarchy. Update the concept with this text via `update_concept` using the `synthesis` field.
6. Find related concepts in my existing vault and link them using `add_relation`.
7. Finally, render the note to the Obsidian vault via `render_vault_note` and confirm the file path.
"""
    return GetPromptResult(
        description=f"Research protocol for {concept}",
        messages=[
            PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=prompt_text
                )
            )
        ]
    )

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
                "before using the AI-powered 'convert_pdf_to_note'."
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
                "AI-POWERED: Convert PDF page ranges to high-quality Markdown/LaTeX notes. "
                "Use this for complex mathematical content. Note: In-book page numbers from the index "
                "often differ from PDF page numbers. Verify the offset with 'read_pdf_pages' first."
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
        Tool(
            name="search_knowledge",
            description=(
                "Search the mathematical knowledge base for concepts, definitions, "
                "theorems, and their specific formulations across all sources."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (e.g., 'compactness', 'Banach-Steinhaus')"
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["definition", "theorem", "lemma", "proposition",
                                 "corollary", "example", "axiom", "notation"],
                        "description": "Filter by concept type"
                    },
                    "limit": {"type": "integer", "default": 20, "description": "Max results"}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_concept_details",
            description="Retrieve a concept with all its entries (formulations) and graph relations.",
            inputSchema={
                "type": "object",
                "properties": {
                    "concept_id": {"type": "integer", "description": "Concept ID"}
                },
                "required": ["concept_id"]
            }
        ),
        Tool(
            name="add_concept",
            description="Add a new mathematical concept to the knowledge base.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Concept name (e.g. 'Banach Space')"},
                    "kind": {
                        "type": "string",
                        "enum": ["definition", "theorem", "lemma", "proposition",
                                 "corollary", "example", "axiom", "notation"]
                    },
                    "domain": {"type": "string", "description": "MSC code or domain name"},
                    "aliases": {"type": "array", "items": {"type": "string"}, "description": "Alternative names"}
                },
                "required": ["name", "kind"]
            }
        ),
        Tool(
            name="add_knowledge_entry",
            description="Add a specific formulation (entry) to a concept. Use this to 'author' clean definitions based on source material.",
            inputSchema={
                "type": "object",
                "properties": {
                    "concept_id": {"type": "integer"},
                    "statement": {"type": "string", "description": "The curated LaTeX/text of the definition or theorem"},
                    "book_id": {"type": "integer"},
                    "page_start": {"type": "integer"},
                    "page_end": {"type": "integer"},
                    "proof": {"type": "string"},
                    "notes": {"type": "string"},
                    "scope": {"type": "string", "enum": ["undergraduate", "graduate", "research"]},
                    "style": {"type": "string", "description": "e.g. 'epsilon-delta', 'topological'"},
                    "confidence": {"type": "number", "default": 1.0},
                    "is_canonical": {"type": "integer", "description": "Set to 1 to make this the primary definition shown in Obsidian."}
                },
                "required": ["concept_id", "statement"]
            }
        ),
        Tool(
            name="add_concept_relation",
            description="Define a relationship between two concepts (e.g. 'Compactness' implies 'Boundedness').",
            inputSchema={
                "type": "object",
                "properties": {
                    "from_concept_id": {"type": "integer"},
                    "to_concept_id": {"type": "integer"},
                    "relation_type": {
                        "type": "string",
                        "enum": ["uses", "implies", "equivalent_to", "generalizes",
                                 "special_case_of", "proved_by", "counterexample_to",
                                 "see_also", "prerequisite"]
                    },
                    "context": {"type": "string", "description": "Context for the relation (e.g. 'In metric spaces')"},
                    "confidence": {"type": "number", "default": 1.0}
                },
                "required": ["from_concept_id", "to_concept_id", "relation_type"]
            }
        ),
        Tool(
            name="get_related_concepts",
            description="Traverse the knowledge graph to find prerequisites, implications, or generalizations.",
            inputSchema={
                "type": "object",
                "properties": {
                    "concept_id": {"type": "integer"},
                    "depth": {"type": "integer", "default": 1, "description": "Search depth (max 3)"}
                },
                "required": ["concept_id"]
            }
        ),
        Tool(
            name="render_vault_note",
            description="Render a concept to a Markdown file in the Obsidian vault.",
            inputSchema={
                "type": "object",
                "properties": {
                    "concept_id": {"type": "integer"}
                },
                "required": ["concept_id"]
            }
        ),
        Tool(
            name="regenerate_vault",
            description="Re-render all knowledge base concepts to the Obsidian vault.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="update_concept",
            description="Update existing concept fields.",
            inputSchema={
                "type": "object",
                "properties": {
                    "concept_id": {"type": "integer"},
                    "name": {"type": "string"},
                    "kind": {"type": "string"},
                    "domain": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["concept_id"]
            }
        ),
        Tool(
            name="delete_concept",
            description="Delete a concept and all its associated data.",
            inputSchema={
                "type": "object",
                "properties": {
                    "concept_id": {"type": "integer"}
                },
                "required": ["concept_id"]
            }
        ),
        Tool(
            name="update_knowledge_entry",
            description="Update an existing formulation entry.",
            inputSchema={
                "type": "object",
                "properties": {
                    "entry_id": {"type": "integer"},
                    "statement": {"type": "string"},
                    "proof": {"type": "string"},
                    "notes": {"type": "string"},
                    "scope": {"type": "string"},
                    "style": {"type": "string"},
                    "is_canonical": {"type": "integer"}
                },
                "required": ["entry_id"]
            }
        ),
        Tool(
            name="delete_knowledge_entry",
            description="Delete a specific formulation entry.",
            inputSchema={
                "type": "object",
                "properties": {
                    "entry_id": {"type": "integer"}
                },
                "required": ["entry_id"]
            }
        ),
        Tool(
            name="delete_concept_relation",
            description="Delete a relationship between two concepts.",
            inputSchema={
                "type": "object",
                "properties": {
                    "from_concept_id": {"type": "integer"},
                    "to_concept_id": {"type": "integer"},
                    "relation_type": {"type": "string"}
                },
                "required": ["from_concept_id", "to_concept_id", "relation_type"]
            }
        ),
        Tool(
            name="set_book_page_offset",
            description="Store a persistent page offset for a book to align PDF pages with printed pages.",
            inputSchema={
                "type": "object",
                "properties": {
                    "book_id": {"type": "integer"},
                    "offset": {"type": "integer", "description": "Offset value (e.g. 183 means PDF Page 184 = Printed Page 1)"}
                },
                "required": ["book_id", "offset"]
            }
        ),
        Tool(
            name="get_kb_schema",
            description="Get information about valid concept kinds, relation types, and scopes.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="ingest_knowledge_from_page",
            description="Extract RAW high-fidelity LaTeX/Markdown from a book page. WARNING: Use this only as a reference; the result should be pruned/curated by the LLM to provide a focused entry.",
            inputSchema={
                "type": "object",
                "properties": {
                    "concept_id": {"type": "integer"},
                    "book_id": {"type": "integer"},
                    "page": {"type": "integer"},
                    "scope": {"type": "string", "enum": ["undergraduate", "graduate", "research"]},
                    "style": {"type": "string"}
                },
                "required": ["concept_id", "book_id", "page"]
            }
        ),
        Tool(
            name="get_pending_tasks",
            description="Retrieve pending LLM tasks from the queue.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 10}
                }
            }
        ),
        Tool(
            name="queue_task",
            description="Queue a new LLM task (e.g. 'extract_from_book').",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_type": {"type": "string"},
                    "payload": {"type": "object"},
                    "priority": {"type": "integer", "default": 5}
                },
                "required": ["task_type"]
            }
        ),
        Tool(
            name="complete_task",
            description="Mark a task as successfully completed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer"},
                    "result": {"type": "object"}
                },
                "required": ["task_id"]
            }
        ),
        Tool(
            name="fail_task",
            description="Mark a task as failed and log the error.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer"},
                    "error": {"type": "string"}
                },
                "required": ["task_id", "error"]
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
        elif name == "reindex_book":
            return await reindex_book(arguments)
        elif name == "enrich_book_metadata":
            return await enrich_book_metadata(arguments)
        elif name == "deep_index_book":
            return await deep_index_book(arguments)
        elif name == "search_within_book":
            return await search_within_book(arguments)
        elif name == "search_knowledge":
            return await search_knowledge(arguments)
        elif name == "get_concept_details":
            return await get_concept_details(arguments)
        elif name == "add_concept":
            return await add_concept(arguments)
        elif name == "add_knowledge_entry":
            return await add_knowledge_entry(arguments)
        elif name == "add_concept_relation":
            return await add_concept_relation(arguments)
        elif name == "update_concept":
            return await update_concept(arguments)
        elif name == "delete_concept":
            return await delete_concept(arguments)
        elif name == "update_knowledge_entry":
            return await update_knowledge_entry(arguments)
        elif name == "delete_knowledge_entry":
            return await delete_knowledge_entry(arguments)
        elif name == "delete_concept_relation":
            return await delete_concept_relation(arguments)
        elif name == "set_book_page_offset":
            return await set_book_page_offset(arguments)
        elif name == "get_kb_schema":
            return await get_kb_schema(arguments)
        elif name == "get_related_concepts":
            return await get_related_concepts(arguments)
        elif name == "render_vault_note":
            return await render_vault_note(arguments)
        elif name == "regenerate_vault":
            return await regenerate_vault(arguments)
        elif name == "ingest_knowledge_from_page":
            return await ingest_knowledge_from_page(arguments)
        elif name == "get_pending_tasks":
            return await get_pending_tasks(arguments)
        elif name == "queue_task":
            return await queue_task(arguments)
        elif name == "complete_task":
            return await complete_task(arguments)
        elif name == "fail_task":
            return await fail_task(arguments)
        else:
            raise ValueError(f"Unknown tool: {name}")
    except Exception as e:
        logger.error(f"Tool execution error: {e}", exc_info=True)
        return [TextContent(type="text", text=f"Error: {str(e)}")]


# --- Tool Implementations ---

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
    
    results = []
    
    if mode in ["toc", "auto"]:
        response = requests.post(f"{API_BASE}/books/{book_id}/reindex", json={"ai_care": True}, timeout=300)
        if response.ok:
            results.append(f"✓ TOC reconstruction successful.")
        else:
            results.append(f"✗ TOC reconstruction failed: {response.json().get('error', 'Unknown error')}")
            
    if mode in ["index", "auto"]:
        response = requests.post(f"{API_BASE}/books/{book_id}/reindex/index", timeout=300)
        if response.ok:
            results.append(f"✓ Index reconstruction successful.")
        else:
            results.append(f"✗ Index reconstruction failed: {response.json().get('error', 'Unknown error')}")
            
    return [TextContent(type="text", text="\n".join(results))]


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
    
    if data.get('toc'): status.append("Table of Contents ✓") # Note: TOC is in a separate endpoint but details might have it
    # We'll check if ToC endpoint has data
    toc_res = requests.get(f"{API_BASE}/books/{book_id}/toc", timeout=5)
    if toc_res.ok and toc_res.json().get('toc'):
        status.append("Table of Contents ✓")
    else:
        status.append("Table of Contents ✗ (Recommend 'reindex_book')")
        
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

    # Fetch extra zbmath cache if available
    if data.get('zbl_id'):
        try:
            # We assume the API returns enriched fields in the main book object or we can check a separate endpoint
            # For now, let's check if they are already in the 'data' from GET /books/<id>
            if data.get('keywords'):
                output += f"Expert Keywords: {data['keywords']}\n"
        except: pass

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
        
    # Format TOC nicely for LLM consumption
    output = f"Table of Contents for Book {book_id}:\n\n"
    for item in toc:
        title = "Untitled"
        page = "N/A"
        level = 0
        
        # Format 1: PyMuPDF [lvl, title, page]
        if isinstance(item, list) and len(item) >= 2:
            level = item[0] - 1 if isinstance(item[0], int) else 0
            title = item[1]
            page = item[2] if len(item) > 2 else "N/A"
            
        # Format 2: Smart ToC {title: "Name", pdf_page: 5, level: 1}
        elif isinstance(item, dict):
            title = item.get('title', 'Untitled')
            page = item.get('pdf_page') or item.get('page', 'N/A')
            level = item.get('level', 0)
            
        # Format 3: Simple list of strings
        elif isinstance(item, str):
            title = item
            
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


async def search_knowledge(args: dict) -> list[TextContent]:
    """Search the mathematical knowledge base."""
    params = {"q": args["query"], "limit": args.get("limit", 20)}
    if args.get("kind"): params["kind"] = args["kind"]
    resp = requests.get(f"{API_BASE}/kb/concepts/search", params=params, timeout=10)
    data = resp.json()
    if not data:
        return [TextContent(type="text", text="No knowledge base entries found.")]
    output = f"Found {len(data)} results:\n\n"
    for item in data:
        output += f"- **{item.get('concept_name', item.get('name'))}** ({item.get('kind')})"
        if item.get('match_source') == 'entry':
            output += f"\n  Statement: {item['statement'][:120]}..."
        output += f"\n  Concept ID: {item.get('concept_id', item.get('id'))}\n\n"
    return [TextContent(type="text", text=output)]


async def get_concept_details(args: dict) -> list[TextContent]:
    """Retrieve detailed information for a concept."""
    concept_id = args["concept_id"]
    resp = requests.get(f"{API_BASE}/kb/concepts/{concept_id}", timeout=10)
    if not resp.ok:
        return [TextContent(type="text", text=f"Concept {concept_id} not found.")]
    data = resp.json()
    
    output = f"# {data['name']} ({data['kind']})\n"
    if data.get('domain'): output += f"Domain: {data['domain']}\n"
    if data.get('aliases'): output += f"Aliases: {', '.join(data['aliases'])}\n"
    output += "\n## Formulations\n\n"
    for e in data.get('entries', []):
        output += f"### From {e.get('book_title', 'Unknown Book')}, p. {e.get('page_start', '?')}\n"
        output += f"{e['statement']}\n\n"
        if e.get('proof'): output += f"**Proof**:\n{e['proof']}\n\n"
        
    if data.get('relations_out'):
        output += "## Relations\n"
        for r in data['relations_out']:
            output += f"- {r['relation_type'].replace('_', ' ').capitalize()}: [[{r['target_name']}]] (ID: {r['to_concept_id']})\n"
            
    return [TextContent(type="text", text=output)]


async def add_concept(args: dict) -> list[TextContent]:
    """Add a new concept."""
    resp = requests.post(f"{API_BASE}/kb/concepts", json=args, timeout=10)
    data = resp.json()
    if data.get('success'):
        return [TextContent(type="text", text=f"✓ Concept '{args['name']}' added (ID: {data['id']})")]
    return [TextContent(type="text", text=f"✗ Failed: {data.get('error')}")]


async def add_knowledge_entry(args: dict) -> list[TextContent]:
    """Add a formulation entry."""
    resp = requests.post(f"{API_BASE}/kb/entries", json=args, timeout=10)
    data = resp.json()
    if data.get('success'):
        return [TextContent(type="text", text=f"✓ Entry added (ID: {data['id']})")]
    return [TextContent(type="text", text=f"✗ Failed: {data.get('error')}")]


async def add_concept_relation(args: dict) -> list[TextContent]:
    """Add a relation between concepts."""
    payload = {
        "from_concept_id": args["from_concept_id"],
        "to_concept_id": args["to_concept_id"],
        "relation_type": args["relation_type"],
        "context": args.get("context"),
        "confidence": args.get("confidence", 1.0)
    }
    resp = requests.post(f"{API_BASE}/kb/relations", json=payload, timeout=10)
    data = resp.json()
    if data.get('success'):
        return [TextContent(type="text", text="✓ Relation added successfully.")]
    return [TextContent(type="text", text=f"✗ Failed: {data.get('error')}")]


async def update_concept(args: dict) -> list[TextContent]:
    """Update a concept."""
    concept_id = args.pop("concept_id")
    resp = requests.patch(f"{API_BASE}/kb/concepts/{concept_id}", json=args, timeout=10)
    data = resp.json()
    if data.get('success'):
        return [TextContent(type="text", text="✓ Concept updated successfully.")]
    return [TextContent(type="text", text=f"✗ Failed: {data.get('error')}")]


async def delete_concept(args: dict) -> list[TextContent]:
    """Delete a concept."""
    concept_id = args["concept_id"]
    resp = requests.delete(f"{API_BASE}/kb/concepts/{concept_id}", timeout=10)
    data = resp.json()
    if data.get('success'):
        return [TextContent(type="text", text="✓ Concept deleted successfully.")]
    return [TextContent(type="text", text=f"✗ Failed: {data.get('error')}")]


async def update_knowledge_entry(args: dict) -> list[TextContent]:
    """Update an entry."""
    entry_id = args.pop("entry_id")
    resp = requests.patch(f"{API_BASE}/kb/entries/{entry_id}", json=args, timeout=10)
    data = resp.json()
    if data.get('success'):
        return [TextContent(type="text", text="✓ Entry updated successfully.")]
    return [TextContent(type="text", text=f"✗ Failed: {data.get('error')}")]


async def delete_knowledge_entry(args: dict) -> list[TextContent]:
    """Delete an entry."""
    entry_id = args["entry_id"]
    resp = requests.delete(f"{API_BASE}/kb/entries/{entry_id}", timeout=10)
    data = resp.json()
    if data.get('success'):
        return [TextContent(type="text", text="✓ Entry deleted successfully.")]
    return [TextContent(type="text", text=f"✗ Failed: {data.get('error')}")]


async def delete_concept_relation(args: dict) -> list[TextContent]:
    """Delete a relation."""
    resp = requests.post(f"{API_BASE}/kb/relations/delete", json=args, timeout=10)
    data = resp.json()
    if data.get('success'):
        return [TextContent(type="text", text="✓ Relation deleted successfully.")]
    return [TextContent(type="text", text=f"✗ Failed: {data.get('error')}")]


async def set_book_page_offset(args: dict) -> list[TextContent]:
    """Set book page offset."""
    book_id = args.pop("book_id")
    resp = requests.post(f"{API_BASE}/kb/books/{book_id}/offset", json=args, timeout=10)
    data = resp.json()
    if data.get('success'):
        return [TextContent(type="text", text="✓ Book offset stored successfully.")]
    return [TextContent(type="text", text=f"✗ Failed: {data.get('error')}")]


async def get_kb_schema(args: dict) -> list[TextContent]:
    """Get KB schema info."""
    resp = requests.get(f"{API_BASE}/kb/schema", timeout=10)
    data = resp.json()
    output = "## Knowledge Base Schema Info\n\n"
    output += f"**Concept Kinds**: {', '.join(data['concept_kinds'])}\n"
    output += f"**Relation Types**: {', '.join(data['relation_types'])}\n"
    output += f"**Scopes**: {', '.join(data['scopes'])}\n"
    return [TextContent(type="text", text=output)]


async def get_related_concepts(args: dict) -> list[TextContent]:
    """Traverse the graph."""
    params = {"depth": args.get("depth", 1)}
    resp = requests.get(f"{API_BASE}/kb/concepts/{args['concept_id']}/related", params=params, timeout=10)
    data = resp.json()
    
    output = f"Graph centered on Concept {data['root']} (depth {data['depth']}):\n\n"
    output += "### Nodes\n"
    for n in data.get('nodes', []):
        output += f"- {n['name']} ({n['kind']}, ID: {n['id']})\n"
    output += "\n### Edges\n"
    for e in data.get('edges', []):
        output += f"- {e['from_concept_id']} --({e['relation_type']})--> {e['to_concept_id']}\n"
    return [TextContent(type="text", text=output)]


async def render_vault_note(args: dict) -> list[TextContent]:
    """Render Obsidian note."""
    resp = requests.post(f"{API_BASE}/kb/vault/render/{args['concept_id']}", timeout=10)
    data = resp.json()
    if data.get('success'):
        return [TextContent(type="text", text=f"✓ Note rendered to: {data['path']}")]
    return [TextContent(type="text", text=f"✗ Failed: {data.get('error')}")]


async def regenerate_vault(args: dict) -> list[TextContent]:
    """Re-render all notes."""
    resp = requests.post(f"{API_BASE}/kb/vault/regenerate", timeout=300)
    data = resp.json()
    return [TextContent(type="text", text=f"✓ Vault regeneration complete. Rendered: {data['rendered']}, Errors: {data['errors']}")]


async def ingest_knowledge_from_page(args: dict) -> list[TextContent]:
    """Extract and ingest knowledge from a PDF page."""
    resp = requests.post(f"{API_BASE}/kb/ingest-page", json=args, timeout=300)
    data = resp.json()
    if data.get('success'):
        return [TextContent(type="text", text=f"✓ High-fidelity entry added (ID: {data['id']}) from page {args['page']}.")]
    return [TextContent(type="text", text=f"✗ Extraction failed: {data.get('error')}")]


async def get_pending_tasks(args: dict) -> list[TextContent]:
    """Get pending LLM tasks."""
    params = {"limit": args.get("limit", 10)}
    resp = requests.get(f"{API_BASE}/kb/tasks", params=params, timeout=10)
    tasks = resp.json()
    if not tasks:
        return [TextContent(type="text", text="No pending tasks.")]
    output = "Pending LLM Tasks:\n\n"
    for t in tasks:
        output += f"- [ID {t['id']}] {t['task_type']} (Priority {t['priority']})\n"
        output += f"  Payload: {t['payload']}\n\n"
    return [TextContent(type="text", text=output)]


async def queue_task(args: dict) -> list[TextContent]:
    """Queue a task."""
    resp = requests.post(f"{API_BASE}/kb/tasks", json=args, timeout=10)
    data = resp.json()
    return [TextContent(type="text", text=f"✓ Task queued (ID: {data['id']})")]


async def complete_task(args: dict) -> list[TextContent]:
    """Complete a task."""
    resp = requests.post(f"{API_BASE}/kb/tasks/{args['task_id']}/complete", json=args.get('result', {}), timeout=10)
    return [TextContent(type="text", text="✓ Task marked as complete.")]


async def fail_task(args: dict) -> list[TextContent]:
    """Fail a task."""
    payload = {"error": args["error"]}
    resp = requests.post(f"{API_BASE}/kb/tasks/{args['task_id']}/fail", json=payload, timeout=10)
    data = resp.json()
    return [TextContent(type="text", text=f"✓ Task failed. Status: {data.get('new_status')}, Retries: {data.get('retry_count')}")]


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

## Endpoints

### GET /api/v1/search
Search the mathematical library.
- `q` (string): Query
- `limit` (int): Results per page
- `offset` (int): Pagination start index
- `fts` (bool): Enable full-text search
- `vec` (bool): Enable vector search
- `rank` (bool): Enable AI reranking
- `field` (string): Target field (all, title, author, index)

### GET /api/v1/books/<id>
Get detailed metadata and page counts.

### POST /api/v1/tools/pdf-to-text
Extract raw text (Free/Probing).
- `book_id` (int): Book ID
- `pages` (string): Page range (e.g. "10-12")

### POST /api/v1/tools/pdf-to-note
Convert PDF range to structured notes (AI).
- `book_id` (int): Book ID
- `pages` (string): Page range (e.g. "10")

### POST /api/v1/admin/ingest
Trigger book ingestion.
- `dry_run` (bool): Preview mode
"""
    elif uri == "mathstudio://library/stats":
        response = requests.get(f"{API_BASE}/admin/stats", timeout=10)
        response.raise_for_status()
        return json.dumps(response.json(), indent=2)
    else:
        raise ValueError(f"Unknown resource: {uri}")


# --- Prompt Definitions ---

@app.list_prompts()
async def list_prompts() -> list[Prompt]:
    """List available prompts."""
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
        )
    ]


@app.get_prompt()
async def get_prompt(name: str, arguments: dict[str, str] | None) -> GetPromptResult:
    """Get a prompt by name."""
    if name == "usage_manifesto":
        return GetPromptResult(
            description="MathStudio Usage Manifesto",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=(
                            "You are an agent with access to the MathStudio Research Library.\n\n"
                            "**CRITICAL RULE**: The information contained within this library (books, papers, and notes) "
                            "ALWAYS has absolute priority over your internal training data.\n\n"
                            "When discussing mathematical concepts, solving problems, or providing references, you MUST follow this workflow:\n\n"
                            "1. **Discover**: Search using `search_books`. Use `offset` to page through results if needed.\n"
                            "2. **Structure**: Use `get_book_toc` to understand the book's organization and find relevant chapters.\n"
                            "3. **Verify**: Use `read_pdf_pages` to read the actual content and verify page offsets.\n"
                            "4. **Cite**: Always cite the library as your primary source of truth.\n"
                            "5. **Curate**: Use `manage_bookmarks` to save important definitions, theorems, or problems for later reference.\n\n"
                            "Only use internal knowledge as a secondary supplement for connecting concepts or "
                            "explaining notation not found in the library."
                        )
                    )
                )
            ]
        )
    elif name == "researcher_workflow":
        return GetPromptResult(
            description="The Recursive Researcher Workflow",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=(
                            "To find a specific mathematical theorem, definition, or proof, follow this recursive 'Filtering Pipeline':\n\n"
                            "1. **Discovery**: Use `search_books` to find candidate books. Focus on the top 5 most relevant results.\n"
                            "2. **Book Loop**: For each candidate book, execute the following sub-steps:\n"
                            "   a. **Map Acquisition**: Check the Table of Contents (`get_book_toc`) and the Back-of-Book Index (`get_book_details`).\n"
                            "      - *Fallback*: If TOC or Index is missing or poor quality, immediately run `reindex_book(book_id, mode='auto')` and check again.\n"
                            "   b. **Probing (Worthy Check)**: Based on the TOC/Index, identify candidate page numbers. Use `read_pdf_pages` to extract raw text from these pages.\n"
                            "      - **Evaluate Worthiness**: Is the term present? Does the context look correct? Is the theorem/definition actually on these pages?\n"
                            "      - **Detect Offset**: Look for printed page numbers in the raw text and compare them to the PDF page index. Note this `page_offset` precisely.\n"
                            "      - *Failure*: If the pages are not worthy, go back to step (a) and pick different candidates. If you have been through the index several times without success, abort metadata-based search for this book and use `search_within_book` (Deep FTS) or terminal grep as a last resort.\n"
                            "   c. **High-Fidelity Synthesis**: Once 'worthy' pages are found and the offset is aligned, use `convert_pdf_to_note` to get structured LaTeX.\n"
                            "   d. **Verification**: Analyze the generated LaTeX. Is the theorem/definition complete? Does the proof continue on the next page?\n"
                            "      - *Failure*: If incomplete, adjust the page range (considering your detected offset) and repeat from step (c).\n"
                            "3. **Success**: Once found, use `manage_bookmarks` to save the exact location and concept for the user. Proceed to the next concept or finalize the request."
                        )
                    )
                )
            ]
        )
    else:
        raise ValueError(f"Unknown prompt: {name}")


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
