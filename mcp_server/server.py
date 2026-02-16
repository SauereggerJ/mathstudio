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
        elif name == "manage_bookmarks":
            return await manage_bookmarks(arguments)
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


async def get_book_details(args: dict) -> list[TextContent]:
    """Get detailed book information."""
    book_id = args["book_id"]
    response = requests.get(f"{API_BASE}/books/{book_id}", timeout=10)
    response.raise_for_status()
    data = response.json()
    
    output = f"# {data['title']}\n"
    output += f"Author: {data['author']}\n"
    output += f"ID: {data['id']} | Pages: {data.get('page_count', 'Unknown')}\n\n"
    if data.get('summary'):
        output += f"## Summary\n{data['summary']}\n\n"
    if data.get('tags'):
        output += f"Tags: {data['tags']}\n"
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
    """Get book TOC."""
    book_id = args["book_id"]
    response = requests.get(f"{API_BASE}/books/{book_id}/toc", timeout=10)
    response.raise_for_status()
    data = response.json()
    
    toc = data.get("toc", [])
    if not toc:
        return [TextContent(type="text", text="No Table of Contents available.")]
        
    # Format TOC nicely
    output = f"Table of Contents for Book {book_id}:\n\n"
    for item in toc:
        # Assuming PyMuPDF format: [lvl, title, page]
        if isinstance(item, list) and len(item) >= 3:
            lvl, title, page = item[0], item[1], item[2]
            indent = "  " * (lvl - 1)
            output += f"{indent}- {title} (p. {page})\n"
            
    return [TextContent(type="text", text=output)]


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
