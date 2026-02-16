# MathStudio MCP Server

An MCP (Model Context Protocol) server that exposes the MathStudio API v1 for LLM integration.

## Features

### Tools
- **`search_books`**: Search the mathematical library using hybrid vector + FTS search with optional AI reranking
- **`get_book_details`**: Retrieve detailed metadata for a specific book
- **`convert_pdf_to_note`**: Extract and convert PDF pages to Markdown/LaTeX notes using Gemini 2.5
- **`trigger_ingestion`**: Admin tool to process new books from the Unsorted directory

### Resources
- **`mathstudio://api/docs`**: Complete API documentation
- **`mathstudio://library/stats`**: Library statistics

## Installation

```bash
cd mcp_server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Edit `config.json` to set the API endpoint:

```json
{
  "api_base_url": "http://192.168.178.2:5002/api/v1",
  "server_name": "MathStudio Library Server",
  "server_version": "1.0.0"
}
```

## Usage

### Running the Server

```bash
python3 server.py
```

The server communicates via stdio and is designed to be used with MCP-compatible clients.

### Claude Desktop Integration

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "mathstudio": {
      "command": "python3",
      "args": ["/absolute/path/to/mathstudio/mcp_server/server.py"]
    }
  }
}
```

### Testing with MCP Inspector

```bash
npx @modelcontextprotocol/inspector python3 server.py
```

## Example Prompts

Once connected to an LLM client:

- "Search for books about topology"
- "Convert page 5 of book 1122 to notes"
- "Show me the API documentation"
- "Trigger a dry-run ingestion to see what new books are available"

## Architecture

The server acts as a bridge between LLMs and the MathStudio API:

```
LLM Client (Claude) <--> MCP Server <--> MathStudio API v1 <--> Docker Container
```

All tool calls are translated to HTTP requests to the API running on the server.
