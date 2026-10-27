# Development

## Prerequisites

- Python 3.9+ (backend)
- Node.js 18+ (frontend, dev orchestration)
- Optional: Redis, Chrome + chromedriver (only for `selenium` crawl mode)

## One-time setup

```bash
# Backend virtualenv (the npm scripts expect backend/venv)
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd ..

# Frontend deps
npm install                       # root: installs `concurrently`
npm install --prefix frontend

# Optional: local semantic embeddings (heavy; TF-IDF is used otherwise)
pip install sentence-transformers
```

Environment: copy `.env.example` to `.env` as needed. Useful vars:

| Var | Effect |
|-----|--------|
| `FLASK_PORT` | Backend port (dev script sets `8080`) |
| `SCRAPEE_SQLITE_PATH` / `SQLITE_DB_PATH` | Override the SQLite location (default `backend/db/docs.db`) |
| `REDIS_URL` / Vercel `KV_URL` | Enable Redis mirroring of the DB |
| `NEXT_PUBLIC_API_URL` | Frontend → backend base URL (default `http://localhost:8080`) |
| `SCRAPEE_BASE_URL` | CLI → backend base URL (default `https://scrapee-api.vercel.app`) |
| `GITHUB_TOKEN` | Higher GitHub API rate limit for `github_engine` |
| `SCRAPEE_BOOTSTRAP_DOCS=1` | Crawl Python / React / FastAPI (and the AutoCrawler's evergreen sites) on boot. Off by default so the index holds only what you load. |

## Run everything

```bash
npm run dev
```

Runs backend and frontend concurrently:

- `dev:backend` — `cd backend && source venv/bin/activate && FLASK_ENV=development FLASK_DEBUG=True FLASK_PORT=8080 python3 app.py` → http://localhost:8080
- `dev:frontend` — `cd frontend && npm run dev` → http://localhost:3000

## Run pieces individually

```bash
# Backend only
cd backend && source venv/bin/activate && FLASK_PORT=8080 python3 app.py

# stdio MCP server (for a local MCP client)
npm run mcp                        # = cd backend && source venv/bin/activate && python3 mcp_stdio.py

# CLI
python3 cli/scrapee.py
```

## Smoke checks

```bash
curl http://localhost:8080/api/health

curl -X POST http://localhost:8080/mcp -H 'Content-Type: application/json' -d '{
  "jsonrpc":"2.0","id":1,"method":"tools/list"
}'

curl -X POST http://localhost:8080/mcp -H 'Content-Type: application/json' -d '{
  "jsonrpc":"2.0","id":2,"method":"tools/call",
  "params":{"name":"get_context","arguments":{"query":"react hooks"}}
}'
```

## Tests

Regression suite (retrieval ranking, the index API, CLI detection). It uses a
throwaway SQLite file and never touches the network:

```bash
backend/venv/bin/python -m unittest discover backend/tests
```

Standalone scripts at the repo root, run with the backend venv active. They
import `mcp_engine` directly, hit the network and write to the configured DB
(`test_new_tools.py` prunes documents) — point `SCRAPEE_SQLITE_PATH` at a copy:

| File | Covers |
|------|--------|
| `test_end_to_end.py` | scrape → index → search on a single page |
| `test_multi_page_crawl.py` | crawl a root URL, discover child pages, search across them |
| `test_new_tools.py` | calls `_tool_*` methods directly on a `MCPServer()` instance (not via MCP dispatch — see `docs/mcp-tools.md`) |
| `test_universal_scraper.py` | crawler behaviour across site types |

```bash
cd backend && source venv/bin/activate && cd ..
python3 test_end_to_end.py
```

## Connecting a local MCP client

`.vscode/mcp.json` defines two servers:

```jsonc
{
  "servers": {
    "scrapee":       { "type": "http",  "url": "https://scrapee-api.vercel.app/mcp" },
    "scrapee-local": {
      "type": "stdio",
      "command": "${workspaceFolder}/backend/venv/bin/python3",
      "args": ["${workspaceFolder}/backend/mcp_stdio.py"]
    }
  }
}
```

Use `scrapee-local` to develop against your own machine; use `scrapee` to hit the
deployed backend. See `docs/mcp-tools.md` for what the server exposes.

## Layout

```
backend/          canonical implementation (Flask + MCP engine + storage + crawlers)
  app.py          HTTP server, Vercel entrypoint
  mcp_engine.py   MCPServer + mcp_server singleton
  mcp_stdio.py    stdio JSON-RPC transport
  storage/        sqlite_store.py, vector_store.py, redis_store.py
  db/docs.db      local SQLite database (gitignored)
cli/scrapee.py    orchestrator CLI
frontend/         Next.js 14 web UI
docs/             this documentation
allmd/            gitignored archive of historical AI-generated notes
```
