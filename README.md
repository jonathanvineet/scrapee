# Scrapee

**Turn any website into an MCP server.**

Paste a URL. Scrapee crawls the whole site, runs it through an intelligence
pipeline (FTS5 full-text search + vector embeddings + a content-quality filter +
URL scoring + GitHub repo understanding + feedback-driven adaptive ranking),
stores it in SQLite, and exposes it over the [Model Context
Protocol](https://modelcontextprotocol.io). Any MCP client — GitHub Copilot,
Claude, Cursor — then answers questions grounded in that specific site's real,
current documentation instead of stale training data.

## How it works

```
             paste a URL
   CLI  /  Web UI  /  scrape_url MCP call
                  │
                  ▼
   crawl the site ─ url scoring, junk filtering, GitHub-aware
                  ▼
   quality filter ─ drop nav / marketing / empty pages
                  ▼
   index ─ SQLite: FTS5 + vector embeddings + code blocks
                  ▼
   serve over MCP ── HTTP  POST /mcp
                 └── stdio backend/mcp_stdio.py
                  │
                  ▼
   AI client calls get_context → answers with cited sources
                  │
   report_feedback ─→ adaptive ranking learns which sources are best
```

The CLI is an **orchestrator**, not a chatbot: it loads docs and wires up your
editor. The AI client does the reasoning.

## Quick start

### Install

```bash
# Backend
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cd ..

# Node tooling + frontend
npm install
npm install --prefix frontend
```

### Run

```bash
npm run dev
```

Starts both services with `concurrently`:

- backend (Flask) — http://localhost:8080
- frontend (Next.js) — http://localhost:3000

### Web UI

One screen at http://localhost:3000:

- **Add a docs site** — paste a URL, pick a page budget, crawl. The result lists
  every page indexed with its word and code-block counts (and a JSON download).
- **Indexed sites** — every domain in the index with page and code counts; expand
  a row to see its pages, or remove the site.
- **What your AI gets** — ask a question and see the exact `get_context` answer
  an MCP client receives, with matched terms highlighted. Yes/No feeds the
  adaptive ranker.
- **Connect your editor** — the `.vscode/mcp.json` snippet and a one-click VS
  Code install.

### CLI

```bash
python3 cli/scrapee.py            # interactive; auto-loads your stack's docs
python3 cli/scrapee.py --help
```

```
scrapee› /load react.dev/learn 60    # crawl + index a site (page budget optional)
scrapee› /ask useEffect cleanup      # preview what your AI client receives
scrapee› /sources                    # indexed sites with page / code counts
scrapee› /remove react.dev           # drop a site from the index
scrapee› /status                     # backend, editor link, index summary
scrapee› /connect                    # rewrite .vscode/mcp.json
scrapee› /reset [all]                # clear local context (all: empty the index, asks first)
scrapee› /exit
```

One-shot form, for scripts: `scrapee load <url> [--pages N]`, `scrapee ask
"<question>"`, `scrapee sources`, `scrapee status`, `scrapee remove <domain>`,
`scrapee connect`.

On boot the CLI detects your stack (`package.json` dependencies,
`requirements.txt` / `pyproject.toml`, `Cargo.toml`, `go.mod`, plus the imports
in your source files), crawls the docs it doesn't have yet, and merges a
`scrapee` entry into `.vscode/mcp.json` (other servers are kept). Skip the
auto-load with `--no-auto`. Point it at a deployed backend with
`export SCRAPEE_BASE_URL="https://<deployment>"`.

## Connect an AI client

Scrapee serves MCP over two transports, both backed by the same engine.

**HTTP** — add to `.vscode/mcp.json` (or your client's MCP config):

```jsonc
{
  "servers": {
    "scrapee": { "type": "http", "url": "http://localhost:8080/mcp" }
  }
}
```

**stdio** — spawn a local server:

```jsonc
{
  "servers": {
    "scrapee-local": {
      "type": "stdio",
      "command": "${workspaceFolder}/backend/venv/bin/python3",
      "args": ["${workspaceFolder}/backend/mcp_stdio.py"]
    }
  }
}
```

or `npm run mcp`. Then ask your AI client a question about the site you loaded —
it calls `get_context` and answers with `[SOURCE: url]` citations.

The server exposes **8 MCP tools**: `get_context`, `report_feedback`,
`scrape_url`, `search_and_get`, `search_docs`, `search_code`, `list_docs`,
`get_doc`. See [docs/mcp-tools.md](docs/mcp-tools.md) for inputs, the context
format and how search ranks pages.

The engine no longer crawls Python / React / FastAPI docs on every boot; set
`SCRAPEE_BOOTSTRAP_DOCS=1` to restore that.

## Architecture

One implementation, the `backend/` package:

| Piece | Path |
|-------|------|
| Flask HTTP server + `/mcp` endpoint + Vercel entrypoint | `backend/app.py` |
| MCP engine (`class MCPServer`, singleton `mcp_server`) | `backend/mcp_engine.py` |
| stdio JSON-RPC transport | `backend/mcp_stdio.py` |
| SQLite storage — FTS5, vectors, adaptive ranking, Redis mirror | `backend/storage/sqlite_store.py` |
| Content-quality filter | `backend/content_filter.py` |
| URL scoring / junk blocking | `backend/url_intelligence.py` |
| Crawlers — `smart` (default), `selenium`, `ultrafast` | `backend/smart_crawler.py`, `backend/selenium_crawler.py`, ... |
| GitHub repo understanding | `backend/github_engine.py` |
| Orchestrator CLI | `cli/scrapee.py` |
| Next.js web UI | `frontend/` |

Local database: `backend/db/docs.db` (override with `SCRAPEE_SQLITE_PATH`).

Full component table and data-flow diagrams: **[docs/architecture.md](docs/architecture.md)**.

## Documentation

- [docs/architecture.md](docs/architecture.md) — components, data flow, HTTP surface
- [docs/mcp-tools.md](docs/mcp-tools.md) — MCP tools exposed vs. defined
- [docs/development.md](docs/development.md) — setup, `npm run dev`, venv, ports, tests
- [docs/deployment.md](docs/deployment.md) — Vercel + KV/Redis persistence

## Deployment

The backend deploys to Vercel as one Python function; both `vercel.json` (repo
root) and `backend/vercel.json` point at `backend/app.py`. Persistence uses
Vercel KV / Redis because serverless `/tmp` does not survive between deployments.
See [docs/deployment.md](docs/deployment.md) and `VERCEL_SETUP.sh`.

## License

MIT
