# MCP tools

Scrapee speaks JSON-RPC 2.0 over two transports, both backed by the same engine
singleton `mcp_engine.mcp_server`:

- **HTTP** — `POST /mcp` on `backend/app.py`
- **stdio** — `python3 backend/mcp_stdio.py` (newline-delimited JSON-RPC)

## Tools exposed at runtime (8)

`tools/list` and the `tools/call` dispatch table in `backend/mcp_engine.py`
(`_handle_tools_list`, `_handle_tools_call`) register these:

| Tool | Input | What it does |
|------|-------|--------------|
| `get_context` | `query` (string, required) | The main tool. Classifies intent, searches the query (BM25 over FTS5, every term required, then a guarded any-term pass), widens with query expansions only when that finds fewer than 3 pages, ranks by text relevance with source authority and learned feedback as tie-breakers, and returns the top 5 as cited passages with their matching code blocks. Returns `{ status, intent, context, sources[], count }`. `status` is `ready`; `learning` when nothing indexed answers but the query names a known stack — a background crawl of its docs site (`DOMAIN_HINTS`, returned as `seed`) starts; or `not_found`, telling the client to call `scrape_url` with the right site. |
| `report_feedback` | `query`, `sources` (string[]), `success` (bool) — all required | Feeds the adaptive ranker: `true` boosts those sources for similar queries, `false` demotes them. |
| `scrape_url` | `url` (required), `mode` (`smart`\|`ultrafast`\|`selenium`), `max_depth` | Crawls and indexes a site on demand. |
| `search_and_get` | `query` (required), `limit`, `snippet_length` | Matching passages (title, snippet, url, domain); triggers a background crawl when nothing matches. |
| `search_docs` | `query` (required), `limit` | Matching URLs only, no crawling. |
| `search_code` | `query` (required), `language`, `limit` | Code blocks with their source URL. |
| `list_docs` | `limit` | Stored URLs plus index statistics. |
| `get_doc` | `url` (required) | Full stored content of one page. |

`get_context`'s `context` is a series of blocks separated by `\n\n---\n\n`:

````
## <page title>
[SOURCE: <url>]

<the ~900-character passage densest in the query's terms>

```<lang>
<a code block from that page that mentions a query term>
```
````

`initialize` also returns an `instructions` string that pushes the client to call
`get_context` before answering and to cite `[SOURCE: url]`.

`resources/list` exposes `docs://stats` and `docs://domains`; `prompts/list`
offers `build_feature`, `debug_code` and `explain_api`.

## Search behaviour

`SQLiteStore.search_docs` (`backend/storage/sqlite_store.py`):

1. FTS5 `MATCH` with every term required, `ORDER BY bm25()` (title weighted 4×).
2. Any-term `MATCH`, kept only when a page contains the query's rarest term
   (usually the library or API name) and at least 60% of its terms.
3. A `LIKE` substring match on the whole query.

It returns an empty list when nothing matches, never unrelated recent pages:
an empty result is what tells `get_context` and `search_and_get` to crawl.

## Methods defined but not exposed

`MCPServer` also defines `_tool_*` methods with no MCP entry point
(`batch_scrape_urls`, `ensure_context`, `understand_repo`, `answer`, ...). Some
are used internally — `/api/scrape` routes GitHub repo URLs through
`_tool_understand_repo` — and `test_new_tools.py` calls several directly on an
`MCPServer()` instance.

To expose one, add an entry to the `tools` array in `_handle_tools_list` (name,
description, `inputSchema`) **and** to the `tools` dict in `_handle_tools_call`.
