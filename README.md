# Scrapee MCP Server (Production Rebuild)
Local, production-grade MCP server for developer workflows with strict JSON-RPC 2.0 handling and a clean tools/resources split.
## What this server supports
- Full MCP lifecycle:
  - `initialize`
  - `tools/list`
  - `tools/call`
  - `resources/list`
  - `resources/read`
- Agent-friendly tools:
  - `search_docs(query)`
  - `get_document(uri|source_url)`
  - `scrape_url(url, max_depth, max_pages)`
  - `search_code(query, language?)`
- Resource-first retrieval:
  - `docs://...` for full document content
  - `code://...` for code snippets
- Structured ingestion:
  - scraper retries + URL validation
  - SQLite persistence + FTS search
  - automatic ingestion when doc search misses
## New architecture
```
scrapee/
├── mcp_server/
│   ├── server.py
│   ├── protocol.py
│   ├── config.py
│   ├── tools/
│   ├── resources/
│   ├── storage/
│   ├── scraper/
│   └── ingestion/
├── start_mcp.py
└── test_mcp_production.py
```
## Run (STDIO transport)
```bash
python -m mcp_server.server
```
or
```bash
python start_mcp.py
```
## VS Code MCP config
`.vscode/mcp.json`:
```json
{
  "servers": {
    "scrapee": {
      "command": "python",
      "args": ["-m", "mcp_server.server"]
    }
  },
  "inputs": []
}
```
## Validate locally
```bash
python test_mcp_production.py
```
This runs deterministic end-to-end MCP flow checks and prints example JSON requests/responses.
