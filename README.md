# Scrapee - Production-Grade Documentation Scraper & MCP Server

A full-stack web scraping and document search system with Model Context Protocol (MCP) integration, Flask REST API, SQLite full-text search, and multiple crawling strategies. Built for production deployment on Vercel with comprehensive debugging and fallback mechanisms.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Architecture](#architecture)
3. [Tools & API](#tools--api)
4. [Storage & Search](#storage--search)
5. [Web Scrapers](#web-scrapers)
6. [Deployment](#deployment)
7. [Configuration](#configuration)
8. [Testing & Debugging](#testing--debugging)

---

## System Overview

Scrapee is a multi-tier system that scrapes web documentation, indexes it with full-text search, and exposes search/retrieval through both REST API and MCP (Model Context Protocol) endpoints.

### Core Technologies

- **Backend**: Python Flask + SQLite3 with FTS5 (Full-Text Search 5)
- **Protocol**: JSON-RPC 2.0 for MCP, REST JSON for HTTP
- **Search**: SQLite FTS5 with Levenshtein fallback (LIKE queries)
- **Crawlers**: SmartCrawler (intelligent), SeleniumCrawler (JavaScript support), UltraFastCrawler (baseline)
- **Transport**: Vercel serverless deployment with `/tmp` persistent storage

### What Scrapee Does

1. **Scrapes URLs** → Fetches HTML, parses content, extracts code blocks
2. **Stores Documents** → Saves to SQLite with title, content, URL, metadata
3. **Indexes with FTS5** → Creates searchable full-text index for fast queries
4. **Searches** → FTS5 boolean queries with OR logic, falls back to LIKE if needed
5. **Serves Results** → Via REST API or MCP protocol to AI agents

---

## Architecture

### Project Structure

```
scrapee/
├── backend/                          # Flask HTTP layer + MCP server
│   ├── app.py                       # Flask application entry point
│   ├── mcp.py                       # MCPServer class with tool handlers
│   ├── api.py                       # Legacy API endpoints (reference)
│   ├── smart_scraper.py             # HTML parsing utilities
│   ├── smart_crawler.py             # Intelligent crawling strategy
│   ├── selenium_crawler.py          # JavaScript-enabled crawler
│   ├── pipeline_crawler.py          # Multi-stage pipeline crawler
│   ├── storage/
│   │   ├── sqlite_store.py          # ⭐ Core database/search engine
│   │   └── redis_store.py           # (Optional) Redis persistence for Vercel
│   ├── index/
│   │   └── vector_search.py         # Semantic search support
│   └── utils/
│       └── normalize.py             # URL normalization
│
├── frontend/                         # Next.js React UI
│   ├── app/
│   │   ├── layout.js
│   │   └── page.js
│   ├── components/
│   │   ├── ScraperForm.js
│   │   ├── ResultsDisplay.js
│   │   ├── History.js
│   │   └── LoadingSpinner.js
│   └── styles/globals.css
│
├── mcp_server/                      # Standalone MCP server module
│   ├── server.py                    # Launches MCP server
│   ├── protocol.py                  # JSON-RPC 2.0 handling
│   ├── config.py                    # Environment & paths
│   ├── logging_utils.py             # Structured logging
│   ├── tools/
│   │   └── registry.py              # Tool definitions
│   ├── resources/
│   │   └── registry.py              # Resource definitions
│   └── storage/
│       └── sqlite_store.py          # Database for MCP
│
├── app.py                           # Legacy entry point (reference)
├── start_mcp.py                     # MCP server launcher
├── init_db.py                       # Database initialization
├── requirements.txt                 # Python dependencies
├── package.json                     # Node.js dependencies (frontend)
├── vercel.json                      # Vercel deployment config
└── README.md                        # This file
```

### System Data Flow

```
User Query / URL
       ↓
    Flask Route
       ↓
   MCPServer Request Handler
       ↓
   ┌─────────────────────────────┐
   │  Tool Handler Selected:     │
   │  - search_and_get          │
   │  - scrape_url              │
   │  - search_docs             │
   │  - search_code             │
   └─────────────────────────────┘
       ↓
   SQLiteStore
       ├── Search FTS5 Index
       ├── OR/AND Query Logic
       └── Fallback to LIKE Queries
       ↓
   Results Returned (JSON)
       ↓
   Response to Client
```

---

## Tools & API

### MCP Tools

Scrapee provides four primary tools accessible via JSON-RPC:

#### 1. **search_and_get** (Main Search Tool)
Searches indexed documents and auto-ingests URLs if search returns no results.

```json
{
  "method": "tools/call",
  "params": {
    "name": "search_and_get",
    "arguments": {
      "query": "python decorators",
      "limit": 5
    }
  }
}
```

**Parameters:**
- `query` (string, required): Search term(s) - tokenized and matched with OR logic
- `limit` (integer, optional): Max results to return (default: 5)

**Returns:**
- Array of document objects with `title`, `content`, `url`
- Auto-ingests matching docs if initial search is empty

**Logic Flow:**
1. Tokenize query: "python decorators" → `["python", "decorators"]`
2. Create FTS query: `"python"* OR "decorators"*`
3. Search `docs_fts` virtual table
4. If < limit results, use LIKE fallback
5. If still empty, heuristically detect doc URL and auto-scrape
6. Return merged results

#### 2. **scrape_url** (URL Scraping)
Fetches and indexes a URL with configurable crawling strategy.

```json
{
  "method": "tools/call",
  "params": {
    "name": "scrape_url",
    "arguments": {
      "url": "https://docs.python.org",
      "max_depth": 2,
      "max_pages": 50,
      "mode": "smart"
    }
  }
}
```

**Parameters:**
- `url` (string, required): Starting URL to scrape
- `max_depth` (integer, optional): How deep to follow links (default: 1)
- `max_pages` (integer, optional): Maximum pages to scrape (default: 10)
- `mode` (string, optional): Crawler strategy - `fast` | `smart` | `pipeline` (default: `smart`)

**Crawler Modes:**
- **fast**: UltraFastCrawler - basic HTTP GET, no JavaScript, minimal parsing
- **smart**: SmartCrawler - intelligent link following, heuristic depth control
- **pipeline**: PipelineMultiCrawler - multi-stage processing, best for complex sites

**Returns:**
- `scraped_count`: Number of pages successfully scraped
- `indexed_count`: Number added to search index
- `failed_urls`: Array of URLs that failed
- `sample_docs`: First 3 indexed documents with metadata

#### 3. **search_docs** (Full-Text Search)
Direct full-text search without auto-ingestion.

```json
{
  "method": "tools/call",
  "params": {
    "name": "search_docs",
    "arguments": {
      "query": "async await",
      "limit": 10
    }
  }
}
```

**Parameters:**
- `query` (string, required): Search term(s)
- `limit` (integer, optional): Max results (default: 10)

**Returns:**
- Array of matching documents sorted by relevance
- Includes content preview, title, URL, domain

**Search Logic:**
1. FTS5 MATCH query with OR-joined tokens
2. If FTS fails, fallback to LIKE with wildcard matching
3. If LIKE also fails, return empty array

#### 4. **search_code** (Code Search)
Searches extracted code blocks by language and snippet content.

```json
{
  "method": "tools/call",
  "params": {
    "name": "search_code",
    "arguments": {
      "query": "async def",
      "language": "python",
      "limit": 5
    }
  }
}
```

**Parameters:**
- `query` (string, required): Code snippet search term
- `language` (string, optional): Filter by language (python, javascript, etc.)
- `limit` (integer, optional): Max results (default: 5)

**Returns:**
- Array of code blocks with `snippet`, `context`, `language`, `title`, `url`
- Full code block and surrounding context included

### REST API Endpoints

#### `POST /api/scrape`
HTTP endpoint for scraping URLs.

```bash
curl -X POST http://localhost:5000/api/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://docs.example.com", "mode": "smart"}'
```

**Request Body:**
```json
{
  "url": "https://example.com",
  "mode": "smart",
  "max_depth": 2,
  "max_pages": 20
}
```

**Response:**
```json
{
  "success": true,
  "scraped_count": 15,
  "indexed_count": 14,
  "failed_urls": [],
  "duration_seconds": 23.45,
  "sample_docs": [
    {
      "title": "Example Page",
      "url": "https://example.com/page",
      "content": "..."
    }
  ]
}
```

#### `POST /api/debug-scrape`
Step-by-step debug output for a single URL (for troubleshooting).

```bash
curl -X POST http://localhost:5000/api/debug-scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

#### `POST /api/scrape/validate-urls`
Validates URL accessibility before scraping.

```bash
curl -X POST http://localhost:5000/api/scrape/validate-urls \
  -H "Content-Type: application/json" \
  -d '{"urls": ["https://example.com", "https://docs.example.com"]}'
```

#### `GET /api/health`
System diagnostics and version info.

```bash
curl http://localhost:5000/api/health
```

**Response:**
```json
{
  "status": "healthy",
  "database": "connected",
  "db_file": "/path/to/docs.db",
  "doc_count": 342,
  "timestamp": "2025-04-02T10:30:00Z"
}
```

#### `POST /mcp`
JSON-RPC 2.0 endpoint for MCP protocol requests.

```bash
curl -X POST http://localhost:5000/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "search_docs",
      "arguments": {"query": "example"}
    }
  }'
```

---

## Storage & Search

### SQLite Database Schema

The system uses SQLite3 with FTS5 (Full-Text Search 5) virtual tables.

#### **docs Table** (Main Storage)
```sql
CREATE TABLE docs (
  id INTEGER PRIMARY KEY,
  url TEXT UNIQUE NOT NULL,
  title TEXT,
  content TEXT NOT NULL,
  domain TEXT,
  status TEXT DEFAULT 'active',
  scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### **docs_fts Table** (FTS5 Virtual Index)
```sql
CREATE VIRTUAL TABLE docs_fts USING fts5(
  title,
  content,
  url UNINDEXED,
  tokenize='porter unicode61'
);
```

- **tokenize='porter unicode61'**: 
  - `porter`: Stemming algorithm (reduces words to roots)
  - `unicode61`: Full Unicode support with special character handling

#### **code_blocks Table**
```sql
CREATE TABLE code_blocks (
  id INTEGER PRIMARY KEY,
  doc_id INTEGER,
  snippet TEXT NOT NULL,
  language TEXT,
  context TEXT,
  FOREIGN KEY (doc_id) REFERENCES docs(id)
);
```

#### **code_fts Table** (Code Search Index)
```sql
CREATE VIRTUAL TABLE code_fts USING fts5(
  snippet,
  context,
  language UNINDEXED,
  url UNINDEXED,
  title UNINDEXED,
  tokenize='porter unicode61'
);
```

### Search Query Processing

#### Query Tokenization
Input: `"python async await"`

**Tokens Extracted:**
```python
tokens = ["python", "async", "await"]
```

#### FTS Query Construction (OR Logic)
**From:** Single AND-based query (too restrictive)
**To:** OR-based query (current - more forgiving)

```python
# Current implementation (OR logic)
prepared = '"python"* OR "async"* OR "await"*'
```

**Why OR instead of AND?**
- AND requires ALL tokens in same document → Often returns 0 results
- OR requires ANY token in document → Returns relevant documents
- User experience: More results, not fewer

#### Search Execution

```
┌──────────────────────────┐
│   Input Query            │
│   "python decorators"    │
└──────────────────────────┘
           ↓
┌──────────────────────────┐
│   Tokenize & Prepare     │
│   '"python"* OR "deco*"'│
└──────────────────────────┘
           ↓
┌──────────────────────────┐
│   FTS5 MATCH Search      │
│   (Fast, indexed)        │
└──────────────────────────┘
           ↓
      ┌─ Found Results?
      │  ├─ Yes → Return them (maybe add LIKE results)
      │  └─ No → Fall through
      │
      ↓
┌──────────────────────────┐
│   LIKE Fallback Search   │
│   (Slower, unindexed)    │
│   WHERE content LIKE '%python%' OR ...
└──────────────────────────┘
           ↓
┌──────────────────────────┐
│   Merge & Return Results │
└──────────────────────────┘
```

#### Fallback Chain

1. **FTS5 Search** (Primary)
   - Fast: Uses index
   - Boolean: `"python"* OR "async"*`
   - Returns: Exact matches with relevance scoring

2. **LIKE Fallback** (Secondary)
   - Slower: Full table scan
   - Pattern: `content LIKE '%python%' OR content LIKE '%async%'`
   - Returns: Any document containing tokens

3. **Empty Result Fallback**
   - If both FTS and LIKE return < limit results
   - Try to auto-ingest related documentation
   - Example: Search for "scrapee" → auto-scrape scrapee GitHub/docs

### Debug Logging

All search and storage operations include comprehensive debug logs:

```
[DEBUG] Searching for: 'python' → FTS: '"python"*'
[DEBUG] FTS found 42 results
[DEBUG] LIKE found 5 additional results
[DEBUG] Total: 47 results
[DEBUG] Saving doc: 'https://example.com' with title: 'Example', content length: 5432
[DEBUG] Created new doc id=123
[DEBUG] Indexed in FTS5 with rowid=123
```

---

## Web Scrapers

Scrapee includes multiple scraping strategies for different use cases.

### SmartCrawler (Recommended)

Intelligent crawling with heuristic depth control and link prioritization.

**Features:**
- Intelligent link discovery and prioritization
- Automatic depth limiting based on URL structure
- Handles 404s and redirects gracefully
- Extracts title, metadata, content
- Parses code blocks with language detection
- Retry logic for transient failures

**Strategy:**
1. Start from seed URL
2. Extract all links from page
3. Filter: Internal links only, avoid duplicates
4. Prioritize: Breadth-first with relevance hinting
5. Stop when: Max pages reached OR depth limit
6. Return: Parsed documents with extracted code

### SeleniumCrawler

JavaScript-enabled crawling using Selenium WebDriver.

**Features:**
- Renders JavaScript-heavy sites
- Waits for dynamic content loading
- Handles client-side rendering
- Cookie/session support
- Screenshots and DOM state capture
- More resource-intensive

**Use Cases:**
- React/Vue/Angular documentation
- SPA (Single Page Application) sites
- JavaScript-heavy content

**Limitations:**
- Slower than SmartCrawler (browser overhead)
- Requires chromedriver/geckodriver
- Higher CPU/memory usage

### UltraFastCrawler

Minimal baseline crawler for speed.

**Features:**
- HTTP GET only, no rendering
- Basic HTML parsing (BeautifulSoup)
- No JavaScript execution
- Minimal retries
- Fastest option

**Use Cases:**
- Simple HTML pages
- Documentation with no JS
- High-volume scraping

**Trade-offs:**
- Won't capture JS-rendered content
- May miss dynamic elements
- Less intelligent link following

---

## Deployment

### Local Development

#### Prerequisites
```bash
python 3.8+
pip install -r requirements.txt
npm install  # For frontend
```

#### Start Backend
```bash
python app.py
# Server runs on http://localhost:5000
```

#### Start Frontend (Optional)
```bash
cd frontend
npm run dev
# UI runs on http://localhost:3000
```

#### Test MCP Server (Standalone)
```bash
python -m mcp_server.server
# Or: python start_mcp.py
```

#### Run Tests
```bash
# Full stack test
python test_mcp_production.py

# API endpoint test
python test_api_endpoint.py

# Direct crawl test
python test_direct_crawl.py
```

### Vercel Deployment

#### Configuration (vercel.json)
```json
{
  "buildCommand": "pip install -r requirements.txt && npm install --prefix frontend",
  "outputDirectory": "frontend/.next",
  "framework": "nextjs",
  "env": {
    "DB_PATH": "/tmp/scrapee"
  }
}
```

#### Database Handling
- **Primary**: `/tmp` directory (serverless writable storage)
- **Fallback**: Redis persistence (optional, configured in redis_store.py)
- **Created automatically** on first request if directory missing

#### Environment Variables
```bash
FLASK_ENV=production
LOG_LEVEL=INFO
DB_PATH=/tmp/scrapee
REDIS_URL=<optional>
```

#### Deployment Steps
```bash
# 1. Push to GitHub
git add .
git commit -m "deployment: ready for vercel"
git push origin main

# 2. Vercel auto-deploys (if connected)
# Or manually:
vercel deploy --prod
```

---

## Configuration

### Environment Variables

#### Required
- `FLASK_ENV`: Development or production
- `DB_PATH`: Where to store SQLite database

#### Optional
- `LOG_LEVEL`: DEBUG | INFO | WARNING | ERROR
- `REDIS_URL`: For distributed caching
- `MAX_SCRAPE_PAGES`: Default 10, maximum pages per scrape
- `MAX_SCRAPE_DEPTH`: Default 2, maximum recursion depth

### SQLiteStore Configuration

#### Database File Location
```python
# Default location (configurable)
db_path = os.getenv('DB_PATH', '/tmp/scrapee/docs.db')

# Automatic directory creation
os.makedirs(os.path.dirname(db_path), exist_ok=True)
```

#### Connection Pooling
```python
# SQLiteStore uses persistent connection
self.conn = sqlite3.connect(db_path, check_same_thread=False)
```

#### FTS5 Configuration
```python
# Tokenizer settings
tokenize='porter unicode61'

# Supports:
# - Phrase queries: "exact phrase"
# - Prefix queries: token*
# - Boolean: AND OR NOT
# - Grouping: (query1 OR query2) AND query3
```

---

## Testing & Debugging

### Manual Testing

#### Test Search
```bash
curl -X POST http://localhost:5000/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "search_docs",
      "arguments": {"query": "python"}
    }
  }'
```

#### Test Scraping
```bash
curl -X POST http://localhost:5000/api/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://docs.python.org",
    "mode": "smart",
    "max_pages": 5
  }'
```

#### Test Health
```bash
curl http://localhost:5000/api/health
```

### Debug Logging

Enable debug logs in backend:

```python
# In app.py or mcp.py
import logging
logging.basicConfig(level=logging.DEBUG)
```

Watch logs during operations:
```bash
tail -f /var/log/app.log  # Or wherever you redirect logs
```

### Key Debug Points

1. **Search Pipeline**
   - `[DEBUG] Searching for: 'query'` - Initial input
   - `[DEBUG] FTS found N results` - FTS5 success
   - `[DEBUG] LIKE fallback found M results` - Secondary search
   - `[DEBUG] Total results: X` - Final count

2. **Document Storage**
   - `[DEBUG] Saving doc: 'url'` - Before storage
   - `[DEBUG] Created new doc id=X` - New document
   - `[DEBUG] Updated existing doc id=X` - Duplicate URL
   - `[DEBUG] Indexed in FTS5 with rowid=X` - Indexing complete

3. **Scraping**
   - `[INFO] Scraping: URL` - Start
   - `[DEBUG] Extracted N links` - Link discovery
   - `[INFO] Following link: URL` - Recursion
   - `[ERROR] Failed to scrape: URL` - Failure
   - `[INFO] Scraped N pages, indexed M` - Complete

### Common Issues & Solutions

| Issue | Cause | Solution |
|-------|-------|----------|
| Search returns empty | Query too restrictive or no docs indexed | Check logs for `[DEBUG] FTS found 0 results`, run scrape first |
| Scraping fails | Network error, timeout, or bad URL | Use `/api/debug-scrape` for step-by-step, check `[ERROR]` logs |
| Database locked | Concurrent write attempts | Ensure only one process writing; use Redis for distributed access |
| Memory overload on Vercel | Too many pages scraped | Reduce `max_pages` and `max_depth` parameters |
| JavaScript content missing | Using fast crawler | Switch mode to `smart` or `pipeline` |

---

## Performance Notes

### Search Performance
- **FTS5 Queries**: ~10-50ms for indexed content
- **LIKE Fallback**: ~200-1000ms depending on database size
- **With 10K+ documents**: Consider pagination and limit

### Scraping Performance
- **SmartCrawler**: ~500ms per page (including parsing)
- **SeleniumCrawler**: ~2-5s per page (JS rendering)
- **UltraFastCrawler**: ~100-200ms per page (minimal parsing)

### Database Size
- **Typical**: 1MB per 500-1000 documents
- **FTS5 Index**: Adds 1.5-2x overhead
- **Code blocks**: Additional 0.5-1MB per 100 docs

---

## Architecture Decisions

### Why SQLite + FTS5?
- No external dependencies (vs. Elasticsearch, Solr)
- Works in serverless (vs. distributed search engines)
- Sufficient for up to 100K+ documents
- Automatic fallback mechanisms (LIKE queries)
- Built-in transaction support

### Why OR Logic in FTS Queries?
- AND logic was too restrictive (0 results common)
- OR + limit is more forgiving
- LIKE fallback catches edge cases
- Better user experience: more results > fewer results

### Why Multiple Crawlers?
- Different use cases (simple vs. JS-heavy)
- Trade-off flexibility: speed vs. completeness
- Allows graceful degradation
- Testing and comparison

### Why Vercel?
- Serverless scales to zero (cost)
- `/tmp` provides persistent storage per instance
- Cold start < 1s for Python
- Redis optional for multi-instance sync

---

## Code Examples

### Using via Python

```python
from backend.storage.sqlite_store import SQLiteStore
from backend.smart_crawler import SmartCrawler

# Initialize store
store = SQLiteStore('/path/to/docs.db')

# Scrape a URL
crawler = SmartCrawler()
urls = crawler.crawl('https://docs.example.com', max_pages=10)
for url, content in urls:
    doc = {
        'title': extract_title(content),
        'content': extract_text(content),
        'url': url
    }
    doc_id = store.save_doc(
        url=url,
        title=doc['title'],
        content=doc['content']
    )
    print(f"Saved doc {doc_id}")

# Search
results = store.search_docs('python', limit=5)
for doc in results:
    print(f"{doc['title']}: {doc['url']}")
```

### Using via REST API

```python
import requests

# Scrape
response = requests.post('http://localhost:5000/api/scrape', json={
    'url': 'https://docs.example.com',
    'mode': 'smart',
    'max_pages': 20
})
print(response.json()['scraped_count'])

# Search
response = requests.post('http://localhost:5000/mcp', json={
    'jsonrpc': '2.0',
    'id': 1,
    'method': 'tools/call',
    'params': {
        'name': 'search_docs',
        'arguments': {'query': 'example', 'limit': 5}
    }
})
results = response.json()['result']
```

### Using as MCP Server

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "search_and_get",
    "arguments": {
      "query": "documentation",
      "limit": 10
    }
  }
}
```

---

## Future Improvements

- [ ] Semantic search using embeddings
- [ ] Advanced caching with Redis
- [ ] Incremental crawling (skip already-indexed URLs)
- [ ] Image extraction and OCR
- [ ] Multi-language support
- [ ] Distributed crawling
- [ ] Custom CSS selectors for parsing
- [ ] User authentication and rate limiting
- [ ] Webhook notifications on scrape completion
- [ ] GraphQL API support

---

## Contributing

1. Fork and clone the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make changes and test locally
4. Commit: `git commit -m "feature: description"`
5. Push: `git push origin feature/your-feature`
6. Open a Pull Request

---

## License

MIT - See LICENSE file for details

---

## Support

For issues, questions, or contributions:
- GitHub Issues: [Create an issue](https://github.com/your-repo/issues)
- Documentation: See inline code comments and docstrings
- Debug Logs: Enable `LOG_LEVEL=DEBUG` for detailed output

---

**Last Updated**: April 2, 2025
**Status**: Production Ready
**Version**: 2.0.0
