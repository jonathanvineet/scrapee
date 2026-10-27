# Architecture

Scrapee turns any website into an MCP server. You paste a URL, the backend crawls
the whole site, runs it through an intelligence pipeline, stores it in SQLite, and
exposes it over the Model Context Protocol so an AI client answers questions
grounded in that site's real, current docs.

As of the September 2026 consolidation there is **one implementation**: the
`backend/` package. The old root `mcp_server/` package, `start_mcp.py`,
`init_db.py`, `backend/api/`, `backend/api.py`, `backend/mcp_handlers.py`, and
`backend/mcp_get_context_fixed.py` were deleted. `backend/mcp.py` was renamed to
`backend/mcp_engine.py` because the old name shadowed the official `mcp` PyPI
package.

## Components

| Component | Path | Purpose |
|-----------|------|---------|
| Flask app | `backend/app.py` | HTTP server. Hosts REST endpoints and the `POST /mcp` JSON-RPC endpoint. Also the Vercel entrypoint. Runs on port 8080 in dev. |
| MCP engine | `backend/mcp_engine.py` | `class MCPServer` + singleton `mcp_server`. `handle_request(dict) -> dict` dispatches `initialize`, `tools/list`, `tools/call`, `resources/*`, `prompts/*`. Holds every `_tool_*` method and the cognitive-routing `get_context` pipeline. |
| stdio transport | `backend/mcp_stdio.py` | Newline-delimited JSON-RPC 2.0 over stdin/stdout. Delegates to `mcp_engine.mcp_server`. Entrypoint for local MCP clients (`python3 backend/mcp_stdio.py` / `npm run mcp`). |
| SQLite store | `backend/storage/sqlite_store.py` | Canonical storage. `class SQLiteStore` + `get_sqlite_store()`. FTS5 full-text index with BM25 + triggers, LIKE / fuzzy fallback, adaptive (feedback-driven) ranking, optional Redis mirroring. |
| Vector store | `backend/storage/vector_store.py` | Semantic search. Uses `sentence-transformers` when installed, falls back to scikit-learn TF-IDF. Embeddings stored as JSON blobs in the same SQLite DB. |
| Redis store | `backend/storage/redis_store.py` | Optional. Mirrors the whole SQLite file to Redis / Vercel KV so serverless cold starts keep their data. |
| Content filter | `backend/content_filter.py` | Quality gate. Scores each crawled page 0-100 on structural signals (link/paragraph ratio, prose volume, CTA density, code presence) and drops nav pages, marketing pages, and empty states before indexing. |
| URL intelligence | `backend/url_intelligence.py` | Universal URL blocking (auth/commercial/legal/nav path segments, tracking params, binary extensions) and 0-100 URL scoring used to order the crawl frontier. |
| Crawlers | `backend/smart_crawler.py`, `backend/selenium_crawler.py`, `backend/pipeline_crawler.py`, `backend/smart_scraper.py`, `backend/auto_crawler.py` | `smart` (scored priority queue, default), `selenium` (JS rendering), `ultrafast` (HTTP only). `smart_scraper.py` does HTML/code-block extraction. |
| GitHub engine | `backend/github_engine.py` | `class GitHubRepoEngine`. Fetches a repo's file tree via the GitHub API, reads README + entry points + key files, and stores a structured repo summary in the index. |
| CLI | `cli/scrapee.py` | Orchestrator (v3.0.0). Boots, detects the project (`package.json`, `requirements.txt`, `Cargo.toml`, ...), auto-loads matching docs from `DOC_MAP`, reads local imports (`IMPORT_MAP`), writes `.vscode/mcp.json`, then a `/load /status /reset` REPL. Talks to the backend over HTTP; it does **not** answer questions itself. |
| Frontend | `frontend/` | Next.js 14 app. `app/page.js` + `components/` (ScraperForm, ResultsDisplay, History). Talks to the backend at `NEXT_PUBLIC_API_URL` (default `http://localhost:8080`). |

## Data flow — paste a link

```
URL (CLI /load, web UI, or scrape_url MCP call)
        │
        ▼
POST /api/scrape  (or mcp_server._tool_scrape_url)
        │
        ▼
Crawler (smart | selenium | ultrafast)
  • fetch seed page, extract links
  • url_intelligence: block junk, score 0-100
  • priority queue: crawl highest-scored URLs first
  • github_engine when the host is github.com
  • early-exit once enough good docs found
        │
        ▼
smart_scraper: extract prose, headings, code blocks
        │
        ▼
content_filter: score 0-100, drop nav / marketing / empty pages
        │
        ▼
SQLiteStore.save_doc()
  • docs + code_blocks tables (backend/db/docs.db)
  • FTS5 index kept in sync by triggers
  • vector_store embeds on first use
  • redis_store mirrors the DB file (if REDIS_URL / KV set)
```

## Data flow — ask a question

```
AI client (Copilot / Claude / Cursor)
        │  JSON-RPC 2.0
        ├─ HTTP:  POST /mcp            → app.py → mcp_server.handle_request
        └─ stdio: backend/mcp_stdio.py → mcp_server.handle_request
        │
        ▼
tools/call → get_context  (cognitive routing pipeline)
  1. classify intent (debug / tutorial / concept / reference / general)
  2. expand query into ~6 variations
  3. search each variation: FTS5 → LIKE → fuzzy/recent fallback
  4. dedupe by URL
  5. rank by source authority + intent + learned feedback scores
  6. diversify (balance docs / github / community)
  7. structure the merged context by intent
        │
        ▼
{ status, intent, context, sources[], count }   ← client answers using only this
        │
        ▼
report_feedback (tool) or POST /api/mcp/feedback (web UI)
  → SQLiteStore updates learned_score for (query, source) pairs
  → next get_context for a similar query re-ranks accordingly
```

## Storage location

`backend/storage/sqlite_store._default_db_path()`:

- Local: `backend/db/docs.db`
- Vercel (any `VERCEL*` env var present): `/tmp/scrapee/docs.db`, mirrored to Redis/KV
- Override: `SCRAPEE_SQLITE_PATH` or `SQLITE_DB_PATH`

## HTTP surface (`backend/app.py`)

| Route | Purpose |
|-------|---------|
| `GET /api/health` | DB status, doc count, import errors, crawler availability |
| `POST /api/scrape` | Crawl + index a URL (`url`, `mode`, `max_depth`, `max_pages`) |
| `POST /api/scrape/validate-urls` | Check URL reachability before scraping |
| `POST /api/debug-scrape` | Step-by-step single-URL scrape output |
| `GET` / `POST /mcp` | MCP JSON-RPC 2.0 endpoint |
| `POST /api/mcp/feedback` | Web UI feedback into adaptive ranking |
| `POST /api/internal/background_scrape` | Fire-and-forget scrape triggered when `get_context` finds nothing |
| `GET /api/stats` | Index + cache + learned-domain analytics |
