"""
Production MCP Server — JSON-RPC 2.0 compliant.

Implements all required MCP methods:
  initialize, tools/list, tools/call,
  resources/list, resources/read,
  prompts/list, prompts/get

All routing lives here; app.py delegates /mcp → mcp_server.handle_request().
"""
import ipaddress
import json
import os
import re
import signal
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from storage.sqlite_store import get_sqlite_store
from smart_scraper import create_scraper
from utils.normalize import normalize_url


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "🦇 Scrapee"
SERVER_VERSION = "1.0.0"
SCRAPE_TIMEOUT_SECONDS = 8


IMPORT_ERRORS: Dict[str, str] = {}

try:
    from smart_crawler import SmartCrawler
    SMART_CRAWLER_AVAILABLE = True
except Exception as exc:
    SmartCrawler = None
    SMART_CRAWLER_AVAILABLE = False
    IMPORT_ERRORS["smart_crawler"] = str(exc)

try:
    from selenium_crawler import SeleniumCrawler
    SELENIUM_AVAILABLE = True
except Exception as exc:
    SeleniumCrawler = None
    SELENIUM_AVAILABLE = False
    IMPORT_ERRORS["selenium_crawler"] = str(exc)

try:
    from pipeline_crawler import UltraFastCrawler
    ULTRAFAST_AVAILABLE = True
except Exception as exc:
    UltraFastCrawler = None
    ULTRAFAST_AVAILABLE = False
    IMPORT_ERRORS["pipeline_crawler"] = str(exc)


class TimeoutException(Exception):
    """Raised when a scrape exceeds the configured timeout."""


def _timeout_handler(signum, frame):
    raise TimeoutException()


if hasattr(signal, "SIGALRM"):
    signal.signal(signal.SIGALRM, _timeout_handler)


class CacheLayer:
    """Simple in-process TTL cache for deterministic read operations."""

    def __init__(self, ttl_seconds: int = 300):
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        cached = self._cache.get(key)
        if not cached:
            return None
        expires_at, value = cached
        if expires_at < time.monotonic():
            self._cache.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._cache[key] = (time.monotonic() + self.ttl_seconds, value)

    def clear(self) -> None:
        self._cache.clear()


class MCPServer:
    """Single JSON-RPC MCP server for the backend.

    Handles all method dispatch; Flask app.py provides the HTTP transport.
    """

    # Internal hostnames / suffixes to block from scraping
    blocked_hostnames = {"localhost", "0.0.0.0", "127.0.0.1", "::1"}
    blocked_suffixes = (".local", ".internal")

    # Heuristics: map common topic keywords to likely doc domains for auto-ingestion
    DOMAIN_HINTS: Dict[str, str] = {
        "python": "https://docs.python.org/3/",
        "react": "https://react.dev/learn",
        "nextjs": "https://nextjs.org/docs",
        "fastapi": "https://fastapi.tiangolo.com/",
        "flask": "https://flask.palletsprojects.com/",
        "sqlite": "https://www.sqlite.org/docs.html",
        "docker": "https://docs.docker.com",
        "kubernetes": "https://kubernetes.io/docs",
        "solana": "https://solana.com/docs",
        "hedera": "https://docs.hedera.com",
        "rust": "https://doc.rust-lang.org",
    }

    def __init__(self):
        self.store = get_sqlite_store()
        self.scraper = create_scraper()
        self.cache = CacheLayer(ttl_seconds=300)
        self.name = SERVER_NAME
        self.version = SERVER_VERSION
        
        # Bootstrap essential documentation on startup (in a background thread)
        threading.Thread(target=self._bootstrap_docs, daemon=True).start()

    def _bootstrap_docs(self):
        """Preload key documentation if not already in the index."""
        bootstrap_sources = [
            "https://docs.python.org/3/",
            "https://react.dev/learn",
            "https://fastapi.tiangolo.com/",
        ]
        
        for url in bootstrap_sources:
            try:
                # Need to strip the URL since get_doc expects an exact match
                if not self.store.get_doc(url) and not self.store.get_doc(url.rstrip("/")):
                    print(f"[MCP] Bootstrapping documentation: {url}")
                    # Run synchronously in the background thread
                    self._tool_scrape_url({"url": url, "mode": "smart", "max_depth": 1})
            except Exception as e:
                print(f"[MCP] Failed to bootstrap {url}: {e}")

    # ------------------------------------------------------------------ #
    # Public entry point                                                    #
    # ------------------------------------------------------------------ #

    def handle_request(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Dispatch a JSON-RPC 2.0 request to the appropriate handler."""
        if not isinstance(data, dict):
            return self._error_response(None, -32600, "Invalid Request")

        method = data.get("method")
        request_id = data.get("id")
        params = data.get("params") or {}

        if not method:
            return self._error_response(request_id, -32600, "Method is required")

        # Notifications have no id — silently drop
        if request_id is None and method.startswith("notifications/"):
            return None

        handlers = {
            "initialize": self._handle_initialize,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
            "resources/list": self._handle_resources_list,
            "resources/read": self._handle_resources_read,
            "prompts/list": self._handle_prompts_list,
            "prompts/get": self._handle_prompts_get,
        }

        handler = handlers.get(method)
        if handler is None:
            if request_id is None:
                return None
            return self._error_response(request_id, -32601, f"Method not found: {method}")

        try:
            return handler(request_id, params)
        except Exception as exc:
            return self._error_response(request_id, -32603, f"Internal error: {exc}")

    # ------------------------------------------------------------------ #
    # Method handlers                                                       #
    # ------------------------------------------------------------------ #

    def _handle_initialize(self, request_id: Any, params: Optional[Dict] = None) -> Dict:
        return self._success_response(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {},
                    "resources": {},
                    "prompts": {},
                },
                "serverInfo": {
                    "name": self.name,
                    "title": self.name,
                    "version": self.version,
                },
            },
        )

    def _handle_tools_list(self, request_id: Any, params: Optional[Dict] = None) -> Dict:
        return self._success_response(
            request_id,
            {
                "tools": [
                    {
                        "name": "search_and_get",
                        "description": (
                            "Search indexed documentation and return relevant snippets for answering "
                            "technical questions. Automatically fetches and indexes missing documentation "
                            "when the index is empty. Prefer this over multiple separate tool calls."
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "description": "Search query"},
                                "limit": {"type": "integer", "default": 5, "description": "Max results to return"},
                                "snippet_length": {"type": "integer", "default": 400, "description": "Max chars per snippet"},
                            },
                            "required": ["query"],
                        },
                    },
                    {
                        "name": "scrape_url",
                        "description": (
                            "Fetch and index documentation from a URL. Use when a required document is "
                            "missing and needs to be fetched and indexed before searching."
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "url": {"type": "string", "description": "URL to scrape"},
                                "mode": {
                                    "type": "string",
                                    "enum": ["smart", "ultrafast", "selenium"],
                                    "default": "smart",
                                },
                                "max_depth": {"type": "integer", "default": 0},
                            },
                            "required": ["url"],
                        },
                    },
                    {
                        "name": "search_docs",
                        "description": (
                            "Search only stored documentation and return matching document identifiers. "
                            "Use when you only need document URLs before a separate fetch step."
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                                "limit": {"type": "integer", "default": 10},
                            },
                            "required": ["query"],
                        },
                    },
                    {
                        "name": "search_code",
                        "description": (
                            "Search indexed code blocks extracted from scraped documentation. "
                            "Use when you need code examples for a specific language or pattern."
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                                "language": {"type": "string", "description": "Optional language filter (e.g. 'python')"},
                                "limit": {"type": "integer", "default": 5},
                            },
                            "required": ["query"],
                        },
                    },
                    {
                        "name": "list_docs",
                        "description": (
                            "Return an overview of all indexed documentation including URLs and storage stats. "
                            "Use when you need to know what documentation is available."
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "limit": {"type": "integer", "default": 50},
                            },
                        },
                    },
                    {
                        "name": "get_doc",
                        "description": (
                            "Return the full content of a stored document by its exact URL. "
                            "Use when you already know the document URL and need its complete text."
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "url": {"type": "string"},
                            },
                            "required": ["url"],
                        },
                    },
                    {
                        "name": "batch_scrape_urls",
                        "description": (
                            "Scrape and index multiple URLs in parallel. Use this to rapidly ingest "
                            "multiple documentation sources at once. Much faster than scrape_url called multiple times."
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "urls": {"type": "array", "items": {"type": "string"}, "description": "Array of URLs to scrape"},
                                "max_concurrent": {"type": "integer", "default": 3, "description": "Max parallel scrapes"},
                                "max_depth": {"type": "integer", "default": 0},
                            },
                            "required": ["urls"],
                        },
                    },
                    {
                        "name": "search_with_filters",
                        "description": (
                            "Search indexed documentation with advanced filtering by domain, language, "
                            "content type, and date range. Returns higher-quality results than basic search."
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                                "domain": {"type": "string", "description": "Filter by domain (e.g. 'github.com')"},
                                "language": {"type": "string", "description": "Filter by code language"},
                                "content_type": {"type": "string", "enum": ["code", "text", "heading"], "description": "Filter by content type"},
                                "date_after": {"type": "string", "description": "ISO 8601 date (YYYY-MM-DD)"},
                                "limit": {"type": "integer", "default": 10},
                            },
                            "required": ["query"],
                        },
                    },
                    {
                        "name": "extract_structured_data",
                        "description": (
                            "Parse a URL and extract structured data like tables, API schemas, and config examples. "
                            "Use when you need structured formats from documentation."
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "url": {"type": "string"},
                                "extract_tables": {"type": "boolean", "default": True},
                                "extract_api_schemas": {"type": "boolean", "default": True},
                                "extract_config_examples": {"type": "boolean", "default": True},
                            },
                            "required": ["url"],
                        },
                    },
                    {
                        "name": "analyze_code_dependencies",
                        "description": (
                            "Analyze code snippets to extract imports, dependencies, and function signatures. "
                            "Use to understand code requirements and structure."
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "code_snippets": {"type": "array", "items": {"type": "string"}},
                                "language": {"type": "string"},
                                "extract_imports": {"type": "boolean", "default": True},
                                "extract_types": {"type": "boolean", "default": True},
                            },
                            "required": ["code_snippets", "language"],
                        },
                    },
                    {
                        "name": "delete_document",
                        "description": (
                            "Delete a single document by URL from the index. Use when a document is no longer relevant."
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "url": {"type": "string"},
                            },
                            "required": ["url"],
                        },
                    },
                    {
                        "name": "prune_docs",
                        "description": (
                            "Remove stale documentation older than N days, or all docs from a specific domain. "
                            "Use to maintain index freshness and manage storage."
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "older_than_days": {"type": "integer", "description": "Delete docs scraped > N days ago"},
                                "domain": {"type": "string", "description": "Delete all docs from this domain (e.g. 'old-api.example.com')"},
                            },
                        },
                    },
                    {
                        "name": "get_index_stats",
                        "description": (
                            "Get detailed analytics about the search index including document count, "
                            "code block count by language, top domains, and index size."
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {},
                        },
                    },
                    {
                        "name": "search_and_summarize",
                        "description": (
                            "Search documentation and automatically generate a brief summary of results. "
                            "Use for quick answers without reading full documentation."
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                                "summary_length": {"type": "string", "enum": ["short", "medium", "long"], "default": "medium"},
                                "include_code_examples": {"type": "boolean", "default": True},
                                "limit": {"type": "integer", "default": 5},
                            },
                            "required": ["query"],
                        },
                    },
                    {
                        "name": "compare_documents",
                        "description": (
                            "Find differences between two documents (e.g. old vs new API docs). "
                            "Returns added, removed, and changed sections."
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "url1": {"type": "string"},
                                "url2": {"type": "string"},
                            },
                            "required": ["url1", "url2"],
                        },
                    },
                    {
                        "name": "export_index",
                        "description": (
                            "Export the entire search index as a backup. Returns metadata about the export."
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "format": {"type": "string", "enum": ["json", "sqlite"], "default": "json"},
                            },
                        },
                    },
                    {
                        "name": "validate_urls",
                        "description": (
                            "Batch check if stored document URLs are still live and accessible. "
                            "Use to identify broken or redirected documentation links."
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "limit": {"type": "integer", "default": 20, "description": "Check up to N URLs"},
                            },
                        },
                    },
                ]
            },
        )

    def _handle_tools_call(self, request_id: Any, params: Dict) -> Dict:
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}

        tools = {
            "search_and_get": self._tool_search_and_get,
            "scrape_url": self._tool_scrape_url,
            "search_docs": self._tool_search_docs,
            "search_code": self._tool_search_code,
            "list_docs": self._tool_list_docs,
            "get_doc": self._tool_get_doc,
            "batch_scrape_urls": self._tool_batch_scrape_urls,
            "search_with_filters": self._tool_search_with_filters,
            "extract_structured_data": self._tool_extract_structured_data,
            "analyze_code_dependencies": self._tool_analyze_code_dependencies,
            "delete_document": self._tool_delete_document,
            "prune_docs": self._tool_prune_docs,
            "get_index_stats": self._tool_get_index_stats,
            "search_and_summarize": self._tool_search_and_summarize,
            "compare_documents": self._tool_compare_documents,
            "export_index": self._tool_export_index,
            "validate_urls": self._tool_validate_urls,
        }

        handler = tools.get(tool_name)
        if handler is None:
            return self._error_response(request_id, -32602, f"Unknown tool: {tool_name}")

        result = handler(arguments)
        return self._success_response(
            request_id,
            {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
                "structuredContent": result,
            },
        )

    def _handle_resources_list(self, request_id: Any, params: Optional[Dict] = None) -> Dict:
        stats = self.store.get_stats()
        docs = self.store.get_doc_summaries(limit=25)
        resources = [
            {
                "uri": "docs://stats",
                "name": "Storage stats",
                "description": "SQLite-backed index statistics and crawler availability.",
                "mimeType": "application/json",
            },
            {
                "uri": "docs://domains",
                "name": "Indexed domains",
                "description": "List of indexed domains and document counts.",
                "mimeType": "application/json",
            },
        ]

        for doc in docs:
            url = doc.get("url", "")
            resources.append(
                {
                    # URI format: docs://{url}  (spec requirement §10)
                    "uri": f"docs://{url}",
                    "name": doc.get("title") or url,
                    "description": f"Stored document for {url}",
                    "mimeType": "text/plain",
                }
            )

        return self._success_response(request_id, {"resources": resources, "stats": stats})

    def _handle_resources_read(self, request_id: Any, params: Dict) -> Dict:
        uri = params.get("uri", "")

        if uri == "docs://stats":
            content = {
                "stats": self.store.get_stats(),
                "crawlers": self._crawler_status(),
                "import_errors": IMPORT_ERRORS,
            }
            return self._success_response(
                request_id,
                {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "application/json",
                            "text": json.dumps(content, ensure_ascii=False, indent=2),
                        }
                    ]
                },
            )

        if uri == "docs://domains":
            content = self.store.list_domains()
            return self._success_response(
                request_id,
                {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "application/json",
                            "text": json.dumps(content, ensure_ascii=False, indent=2),
                        }
                    ]
                },
            )

        # docs://{url} — strip the scheme prefix to recover the original URL
        if uri.startswith("docs://"):
            doc_url = uri[len("docs://"):]
            # Restore the URL scheme if stripped (http:// or https://)
            if not doc_url.startswith("http"):
                # Try both schemes
                doc = self.store.get_doc(f"https://{doc_url}") or self.store.get_doc(f"http://{doc_url}")
            else:
                doc = self.store.get_doc(doc_url)

            if not doc:
                return self._error_response(request_id, -32602, f"Unknown resource: {uri}")

            return self._success_response(
                request_id,
                {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "text/plain",
                            "text": doc.get("content", ""),
                        }
                    ]
                },
            )

        return self._error_response(request_id, -32602, f"Unknown resource: {uri}")

    def _handle_prompts_list(self, request_id: Any, params: Optional[Dict] = None) -> Dict:
        return self._success_response(
            request_id,
            {
                "prompts": [
                    {
                        "name": "build_feature",
                        "description": (
                            "Generate an implementation plan for a new feature using indexed documentation "
                            "and code examples as grounding context."
                        ),
                        "arguments": [
                            {"name": "feature", "description": "Feature or task to implement", "required": True}
                        ],
                    },
                    {
                        "name": "debug_code",
                        "description": (
                            "Diagnose and fix a code error by searching relevant documentation and "
                            "similar code patterns from the indexed knowledge base."
                        ),
                        "arguments": [
                            {"name": "code", "description": "The code snippet that has an error", "required": True},
                            {"name": "error", "description": "The error message or unexpected behaviour", "required": True},
                        ],
                    },
                    {
                        "name": "explain_api",
                        "description": (
                            "Explain an API, library, or concept using indexed documentation. "
                            "Returns a structured summary with usage examples."
                        ),
                        "arguments": [
                            {"name": "api_name", "description": "API or library name to explain", "required": True}
                        ],
                    },
                ]
            },
        )

    def _handle_prompts_get(self, request_id: Any, params: Dict) -> Dict:
        name = params.get("name", "")
        arguments = params.get("arguments") or {}

        if name == "build_feature":
            feature = str(arguments.get("feature", "")).strip()
            docs = self.store.search_and_get(feature, limit=3, snippet_length=500)
            code = self.store.search_code(feature, limit=3)
            text = self._render_prompt(
                header=f"You are implementing: {feature}\n\nUse the documentation and code examples below as your grounding context.",
                docs=docs,
                code=code,
            )
            return self._prompt_response(request_id, text)

        if name == "debug_code":
            code_snippet = str(arguments.get("code", "")).strip()
            error_msg = str(arguments.get("error", "")).strip()
            query = f"{error_msg} {code_snippet[:200]}"
            docs = self.store.search_and_get(query, limit=3, snippet_length=400)
            code_examples = self.store.search_code(error_msg or code_snippet[:100], limit=2)
            header = (
                f"Debug the following error:\n\nError: {error_msg}\n\nCode:\n```\n{code_snippet}\n```\n\n"
                "Use the documentation references below to diagnose and fix the problem."
            )
            text = self._render_prompt(header=header, docs=docs, code=code_examples)
            return self._prompt_response(request_id, text)

        if name == "explain_api":
            api_name = str(arguments.get("api_name", "")).strip()
            docs = self.store.search_and_get(api_name, limit=4, snippet_length=500)
            code = self.store.search_code(api_name, limit=3)
            text = self._render_prompt(
                header=f"Explain the '{api_name}' API using the documentation context below.",
                docs=docs,
                code=code,
            )
            return self._prompt_response(request_id, text)

        return self._error_response(request_id, -32602, f"Unknown prompt: {name}")

    # ------------------------------------------------------------------ #
    # Tool implementations                                                  #
    # ------------------------------------------------------------------ #

    def _tool_batch_scrape_urls(self, args: Dict) -> Dict:
        """Scrape multiple URLs in parallel."""
        import concurrent.futures
        
        urls = args.get("urls", [])
        if not isinstance(urls, list) or not urls:
            return {"error": "urls must be a non-empty array"}
        
        max_concurrent = self._coerce_int(args.get("max_concurrent", 3), 3, 1, 10)
        max_depth = self._coerce_int(args.get("max_depth", 0), 0, 0, 2)
        results = []
        
        def scrape_one(url: str):
            try:
                valid, reason = self._validate_scrape_url(url)
                if not valid:
                    return {"url": url, "success": False, "error": reason}
                
                result = self._run_with_timeout(
                    lambda: self.scraper.scrape(url, max_depth=max_depth),
                    SCRAPE_TIMEOUT_SECONDS
                )
                
                self.store.add_document(
                    url=result.get("url", url),
                    title=result.get("title"),
                    content=result.get("content"),
                    code_blocks=result.get("code_blocks", []),
                    topics=result.get("topics", []),
                )
                self.store._push_to_redis()
                return {"url": url, "success": True, "title": result.get("title")}
            except Exception as e:
                return {"url": url, "success": False, "error": str(e)}
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            results = list(executor.map(scrape_one, urls))
        
        return {
            "total": len(urls),
            "successful": sum(1 for r in results if r.get("success")),
            "results": results
        }

    def _tool_search_with_filters(self, args: Dict) -> Dict:
        """Search with advanced filtering."""
        query = str(args.get("query", "")).strip()
        if not query:
            return {"error": "query is required"}
        
        domain = str(args.get("domain", "")).strip() or None
        language = str(args.get("language", "")).strip() or None
        content_type = str(args.get("content_type", "")).strip() or None
        date_after = str(args.get("date_after", "")).strip() or None
        limit = self._coerce_int(args.get("limit", 10), 10, 1, 100)
        
        results = self.store.search_with_filters(
            query=query,
            domain=domain,
            language=language,
            content_type=content_type,
            date_after=date_after,
            limit=limit
        )
        return {"results": results, "count": len(results)}

    def _tool_extract_structured_data(self, args: Dict) -> Dict:
        """Extract tables, schemas, and config examples from a URL."""
        url = str(args.get("url", "")).strip()
        if not url:
            return {"error": "url is required"}
        
        valid, reason = self._validate_scrape_url(url)
        if not valid:
            return {"error": f"Invalid URL: {reason}"}
        
        extract_tables = bool(args.get("extract_tables", True))
        extract_api_schemas = bool(args.get("extract_api_schemas", True))
        extract_config_examples = bool(args.get("extract_config_examples", True))
        
        try:
            result = self._run_with_timeout(
                lambda: self.scraper.extract_structured(
                    url,
                    extract_tables=extract_tables,
                    extract_api_schemas=extract_api_schemas,
                    extract_config_examples=extract_config_examples
                ),
                SCRAPE_TIMEOUT_SECONDS
            )
            return result
        except Exception as e:
            return {"error": str(e)}

    def _tool_analyze_code_dependencies(self, args: Dict) -> Dict:
        """Analyze code snippets for imports and dependencies."""
        code_snippets = args.get("code_snippets", [])
        language = str(args.get("language", "")).strip().lower()
        extract_imports = bool(args.get("extract_imports", True))
        extract_types = bool(args.get("extract_types", True))
        
        if not isinstance(code_snippets, list) or not code_snippets:
            return {"error": "code_snippets must be a non-empty array"}
        
        if not language:
            return {"error": "language is required"}
        
        results = {
            "language": language,
            "snippets_analyzed": len(code_snippets),
            "imports": [],
            "types": [],
            "functions": []
        }
        
        for snippet in code_snippets:
            if extract_imports:
                imports = self._extract_imports(snippet, language)
                results["imports"].extend(imports)
            
            if extract_types:
                types = self._extract_types(snippet, language)
                results["types"].extend(types)
            
            functions = self._extract_functions(snippet, language)
            results["functions"].extend(functions)
        
        return results

    def _tool_delete_document(self, args: Dict) -> Dict:
        """Delete a single document."""
        url = str(args.get("url", "")).strip()
        if not url:
            return {"error": "url is required"}
        
        deleted = self.store.delete_document(url)
        if deleted:
            self.store._push_to_redis()
            return {"success": True, "deleted": True, "url": url}
        return {"success": False, "deleted": False, "error": "Document not found"}

    def _tool_prune_docs(self, args: Dict) -> Dict:
        """Prune old documents or by domain."""
        older_than_days = args.get("older_than_days")
        domain = str(args.get("domain", "")).strip() or None
        
        if older_than_days is not None:
            count = self.store.delete_old_documents(int(older_than_days))
            self.store._push_to_redis()
            return {"success": True, "deleted_count": count, "reason": f"older than {older_than_days} days"}
        
        if domain:
            count = self.store.delete_domain_documents(domain)
            self.store._push_to_redis()
            return {"success": True, "deleted_count": count, "reason": f"domain: {domain}"}
        
        return {"error": "Either older_than_days or domain is required"}

    def _tool_get_index_stats(self, args: Dict) -> Dict:
        """Get detailed index statistics."""
        return self.store.get_detailed_stats()

    def _tool_search_and_summarize(self, args: Dict) -> Dict:
        """Search and generate a summary."""
        query = str(args.get("query", "")).strip()
        if not query:
            return {"error": "query is required"}
        
        summary_length = str(args.get("summary_length", "medium")).strip().lower()
        include_code = bool(args.get("include_code_examples", True))
        limit = self._coerce_int(args.get("limit", 5), 5, 1, 20)
        
        results = self.store.search_and_get(query, limit=limit, snippet_length=500)
        
        summary = self._generate_summary(results, summary_length)
        
        data = {
            "query": query,
            "summary": summary,
            "result_count": len(results),
            "results": results[:3]
        }
        
        if include_code:
            code_results = self.store.search_code(query, limit=2)
            data["code_examples"] = code_results
        
        return data

    def _tool_compare_documents(self, args: Dict) -> Dict:
        """Compare two documents."""
        url1 = str(args.get("url1", "")).strip()
        url2 = str(args.get("url2", "")).strip()
        
        if not url1 or not url2:
            return {"error": "url1 and url2 are required"}
        
        doc1 = self.store.get_document(url1)
        doc2 = self.store.get_document(url2)
        
        if not doc1:
            return {"error": f"Document not found: {url1}"}
        if not doc2:
            return {"error": f"Document not found: {url2}"}
        
        diff = self._compute_diff(doc1.get("content", ""), doc2.get("content", ""))
        return {
            "url1": url1,
            "url2": url2,
            "similarity": diff.get("similarity", 0),
            "added_lines": diff.get("added", []),
            "removed_lines": diff.get("removed", []),
            "changed_sections": diff.get("changed", [])
        }

    def _tool_export_index(self, args: Dict) -> Dict:
        """Export the index."""
        format_type = str(args.get("format", "json")).strip().lower()
        
        if format_type == "sqlite":
            import os
            try:
                size = os.path.getsize(self.store.db_path)
                return {
                    "format": "sqlite",
                    "path": self.store.db_path,
                    "size_bytes": size,
                    "size_mb": round(size / 1024 / 1024, 2)
                }
            except Exception as e:
                return {"error": str(e)}
        
        # JSON export
        try:
            export_data = self.store.export_as_json()
            return {
                "format": "json",
                "doc_count": export_data.get("doc_count", 0),
                "code_block_count": export_data.get("code_block_count", 0),
                "size_mb": len(json.dumps(export_data)) / 1024 / 1024,
                "preview": {"docs": export_data.get("docs", [])[:2]}
            }
        except Exception as e:
            return {"error": str(e)}

    def _tool_validate_urls(self, args: Dict) -> Dict:
        """Validate stored document URLs."""
        import requests
        
        limit = self._coerce_int(args.get("limit", 20), 20, 1, 100)
        urls = self.store.get_all_document_urls(limit=limit)
        
        results = []
        for url in urls:
            try:
                resp = requests.head(url, timeout=5, allow_redirects=True)
                results.append({
                    "url": url,
                    "status": resp.status_code,
                    "alive": 200 <= resp.status_code < 400,
                    "redirect": resp.url if resp.url != url else None
                })
            except Exception as e:
                results.append({
                    "url": url,
                    "status": None,
                    "alive": False,
                    "error": str(e)
                })
        
        return {
            "checked": len(results),
            "alive": sum(1 for r in results if r.get("alive")),
            "dead": sum(1 for r in results if not r.get("alive")),
            "results": results
        }

    # Helper methods for new tools
    def _extract_imports(self, code: str, language: str) -> List[str]:
        """Extract imports from code."""
        imports = []
        lines = code.split("\n")
        
        if language == "python":
            for line in lines:
                if line.strip().startswith(("import ", "from ")):
                    imports.append(line.strip())
        elif language in ("javascript", "typescript"):
            for line in lines:
                if any(x in line for x in ["import ", "require("]):
                    imports.append(line.strip())
        elif language == "java":
            for line in lines:
                if line.strip().startswith("import "):
                    imports.append(line.strip())
        
        return list(set(imports))

    def _extract_types(self, code: str, language: str) -> List[str]:
        """Extract type definitions from code."""
        types = []
        
        if language == "typescript":
            import re
            type_pattern = r"(?:type|interface)\s+(\w+)"
            types = re.findall(type_pattern, code)
        elif language == "python":
            import re
            class_pattern = r"class\s+(\w+)"
            types = re.findall(class_pattern, code)
        
        return list(set(types))

    def _extract_functions(self, code: str, language: str) -> List[str]:
        """Extract function definitions from code."""
        import re
        functions = []
        
        patterns = {
            "python": r"def\s+(\w+)\s*\(",
            "javascript": r"(?:function|const|let)\s+(\w+)\s*(?:\(|=)",
            "typescript": r"(?:function|const|let)\s+(\w+)\s*(?:\(|:|=)",
            "java": r"(?:public|private|protected)?\s*(?:static)?\s*\w+\s+(\w+)\s*\(",
            "rust": r"fn\s+(\w+)\s*\(",
            "go": r"func\s+(?:\([^)]*\)\s+)?(\w+)\s*\(",
        }
        
        pattern = patterns.get(language)
        if pattern:
            functions = re.findall(pattern, code)
        
        return list(set(functions))

    def _generate_summary(self, results: List[Dict], length: str = "medium") -> str:
        """Generate a summary from search results."""
        if not results:
            return "No results found."
        
        max_chars = {"short": 200, "medium": 500, "long": 1000}.get(length, 500)
        
        summaries = []
        for result in results:
            snippet = result.get("snippet", "")[:max_chars]
            summaries.append(snippet)
        
        summary = " ".join(summaries)[:max_chars]
        return summary + ("..." if len(summary) == max_chars else "")

    def _compute_diff(self, content1: str, content2: str) -> Dict:
        """Compute difference between two documents."""
        import difflib
        
        lines1 = content1.split("\n")
        lines2 = content2.split("\n")
        
        diff = list(difflib.unified_diff(lines1, lines2, lineterm=""))
        
        added = [line[1:] for line in diff if line.startswith("+") and not line.startswith("+++")]
        removed = [line[1:] for line in diff if line.startswith("-") and not line.startswith("---")]
        
        similarity = difflib.SequenceMatcher(None, content1, content2).ratio()
        
        return {
            "similarity": round(similarity * 100, 2),
            "added": added[:10],
            "removed": removed[:10],
            "changed": list(zip(removed[:10], added[:10]))
        }

    def _tool_search_and_get(self, args: Dict) -> Dict:
        """Search indexed docs; auto-ingest if index is empty."""
        query = str(args.get("query", "")).strip()
        limit = self._coerce_int(args.get("limit", args.get("k", 5)), default=5, minimum=1, maximum=10)
        snippet_length = self._coerce_int(args.get("snippet_length", 400), default=400, minimum=100, maximum=2000)
        if not query:
            return {"error": "query is required"}

        cache_key = f"search_and_get:{query}:{limit}:{snippet_length}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        results = self.store.search_and_get(query, limit=limit, snippet_length=snippet_length)

        # ── Auto-ingestion ──────────────────────────────────────────────
        # If the index returned nothing, try to identify a relevant
        # documentation domain and scrape it, then re-run the search.
        if not results:
            seed_url = self._detect_doc_domain(query)
            if seed_url:
                print(f"[MCP] auto-ingesting {seed_url} for query: {query!r}")
                try:
                    # Use depth=2 for initial ingestion as per requirements
                    self._tool_scrape_url({"url": seed_url, "mode": "smart", "max_depth": 2})
                    results = self.store.search_and_get(query, limit=limit, snippet_length=snippet_length)
                except Exception as exc:
                    print(f"[MCP] auto-ingest failed: {exc}")
        # ───────────────────────────────────────────────────────────────

        payload = {"query": query, "total": len(results), "results": results}
        if results:
            self.cache.set(cache_key, payload)
        return payload

    def _tool_scrape_url(self, args: Dict) -> Dict:
        """Fetch a URL, extract text + code blocks, and store it."""
        raw_url = str(args.get("url", "")).strip()
        mode = str(args.get("mode", "smart")).strip().lower() or "smart"
        max_depth = self._coerce_int(args.get("max_depth", 0), default=0, minimum=0, maximum=2)

        if not raw_url:
            return {"error": "url is required"}

        is_valid, error_message = self._validate_scrape_url(raw_url)
        if not is_valid:
            return {"error": error_message, "url": raw_url}

        url = normalize_url(raw_url)
        crawler = self._build_crawler(mode, url, max_depth)
        if crawler is None:
            return {"error": f"crawler mode '{mode}' is unavailable", "url": url, "mode": mode}

        try:
            # SmartCrawler needs seed_url passed to crawl() method
            # Other crawlers store start_url in __init__, so crawl() takes no args
            if isinstance(crawler, SmartCrawler):
                crawl_callback = lambda: crawler.crawl(
                    seed_url=url,
                    max_pages=30,
                    max_depth=max_depth
                )
            else:
                # For other crawlers (Selenium, UltraFast), crawl() is parameter-less
                crawl_callback = crawler.crawl
            
            pages = self._run_with_timeout(crawl_callback, timeout=SCRAPE_TIMEOUT_SECONDS)
        except TimeoutException:
            return {"error": "timeout", "url": url, "mode": mode, "pages_scraped": 0, "stored_urls": [], "skipped": []}
        except Exception as exc:
            return {"error": f"scrape failed: {exc}", "url": url, "mode": mode}

        stored_urls: List[str] = []
        skipped: List[Dict[str, str]] = []

        for page_url, html in (pages or {}).items():
            normalized_page_url = normalize_url(page_url)
            page_valid, page_error = self._validate_scrape_url(normalized_page_url)
            if not page_valid:
                skipped.append({"url": normalized_page_url, "reason": page_error})
                continue

            try:
                parsed = self.scraper.parse_html(html, normalized_page_url)
                self.store.save_doc(
                    normalized_page_url,
                    parsed.get("content", ""),
                    metadata=parsed.get("metadata", {}),
                    code_blocks=parsed.get("code_blocks", []),
                    topics=parsed.get("topics", []),
                )
                stored_urls.append(normalized_page_url)
            except Exception as exc:
                skipped.append({"url": normalized_page_url, "reason": str(exc)})

        self.cache.clear()
        return {
            "url": url,
            "mode": mode,
            "max_depth": max_depth,
            "pages_scraped": len(stored_urls),
            "stored_urls": stored_urls,
            "skipped": skipped,
        }

    def _tool_search_docs(self, args: Dict) -> Dict:
        """Search only stored documentation."""
        query = str(args.get("query", "")).strip()
        limit = self._coerce_int(args.get("limit", 10), default=10, minimum=1, maximum=25)
        if not query:
            return {"error": "query is required"}

        cache_key = f"search_docs:{query}:{limit}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        results = self.store.search_docs(query, limit=limit)
        payload = {
            "query": query,
            "total": len(results),
            "urls": [item["url"] for item in results],
        }
        self.cache.set(cache_key, payload)
        return payload

    def _tool_search_code(self, args: Dict) -> Dict:
        """Search indexed code blocks."""
        query = str(args.get("query", "")).strip()
        language = str(args.get("language", "")).strip() or None
        limit = self._coerce_int(args.get("limit", 5), default=5, minimum=1, maximum=20)
        if not query:
            return {"error": "query is required"}

        cache_key = f"search_code:{query}:{language}:{limit}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        results = self.store.search_code(query, language=language, limit=limit)
        payload = {"query": query, "language": language, "total": len(results), "results": results}
        self.cache.set(cache_key, payload)
        return payload

    def _tool_list_docs(self, args: Dict) -> Dict:
        """Return stored document metadata."""
        limit = self._coerce_int(args.get("limit", 50), default=50, minimum=1, maximum=200)
        docs = self.store.list_docs(limit=limit)
        stats = self.store.get_stats()
        return {"total": stats.get("total_docs", 0), "urls": docs, "stats": stats}

    def _tool_get_doc(self, args: Dict) -> Dict:
        """Return full document contents by URL."""
        url = normalize_url(str(args.get("url", "")).strip())
        if not url:
            return {"error": "url is required"}
        doc = self.store.get_doc(url)
        if not doc:
            return {"error": f"document not found: {url}"}
        return doc

    # ------------------------------------------------------------------ #
    # Auto-ingestion helpers                                                #
    # ------------------------------------------------------------------ #

    def _detect_doc_domain(self, query: str) -> Optional[str]:
        """Return a seed URL to scrape for a given query, or None."""
        q = query.lower()
        
        # Exact keyword match
        for keyword, url in self.DOMAIN_HINTS.items():
            if keyword in q:
                return url
                
        # Fuzzy match tokens e.g. "react hooks"
        words = set(re.findall(r"[a-z0-9]+", q))
        for keyword, url in self.DOMAIN_HINTS.items():
            if keyword in words:
                return url

        # Generic fallback: try to extract a domain-like token from the query
        # e.g. "django orm" → try "https://docs.djangoproject.com/"
        long_words = [w for w in words if len(w) > 4]
        for word in long_words:
            candidate = f"https://docs.{word}.com/"
            is_valid, _ = self._validate_scrape_url(candidate)
            if is_valid:
                return candidate
                
        return None

    # ------------------------------------------------------------------ #
    # Crawler helpers                                                       #
    # ------------------------------------------------------------------ #

    def _build_crawler(self, mode: str, url: str, max_depth: int):
        """
        Build a crawler configured for the given mode.
        
        Modes:
        - 'smart' (GHOST_PROTOCOL): SmartCrawler with scored priority queue, early exit
        - 'pipeline' (SWARM_ROUTINE): UltraFastCrawler with multiple workers, bounded to 50 pages
        - 'selenium' (DEEP_RENDER): SeleniumCrawler with JS rendering
        - 'fast' / other: Fallback to SmartCrawler
        """
        if mode == "selenium" and SELENIUM_AVAILABLE:
            return SeleniumCrawler(start_url=url, max_depth=max_depth)
        
        if mode == "pipeline" and ULTRAFAST_AVAILABLE:
            # SWARM_ROUTINE: Concurrent crawling, bounded to 50 pages max
            # (prevents infinite crawling of large sites)
            crawler = UltraFastCrawler(start_url=url, max_depth=max_depth, max_workers=8)
            crawler.max_pages = 50  # Limit swarm to reasonable page count
            return crawler
        
        if SMART_CRAWLER_AVAILABLE:
            # GHOST_PROTOCOL or fallback: Smart priority queue with early exit
            # Returns crawler ready for crawler.crawl(seed_url, max_pages, max_depth)
            return SmartCrawler(
                timeout=15,
                delay_between_requests=0.3,
                min_good_docs=5,
                cross_domain_budget=3,
            )
        
        return None

    def _validate_scrape_url(self, url: str) -> Tuple[bool, str]:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False, "invalid scheme: only http and https are allowed"
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return False, "url must include a hostname"
        if hostname in self.blocked_hostnames or hostname.endswith(self.blocked_suffixes):
            return False, "blocked internal URL"
        # Block cloud metadata endpoints
        if hostname in {"metadata.google.internal", "169.254.169.254"}:
            return False, "blocked metadata endpoint"
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False, "blocked internal IP range"
        except ValueError:
            pass
        return True, ""

    def _run_with_timeout(self, callback: Callable[[], Any], timeout: int) -> Any:
        if not hasattr(signal, "SIGALRM") or threading.current_thread() is not threading.main_thread():
            return callback()
        previous = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, _timeout_handler)
        try:
            signal.alarm(timeout)
            return callback()
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)

    # ------------------------------------------------------------------ #
    # Response / prompt helpers                                             #
    # ------------------------------------------------------------------ #

    def _render_prompt(self, header: str, docs: List[Dict], code: List[Dict]) -> str:
        sections = [header, "", "## Documentation"]
        if docs:
            for item in docs:
                sections.append(f"- **{item.get('title') or item.get('url')}**: {item.get('snippet', '')}")
        else:
            sections.append("- No documentation matches found.")

        sections.append("")
        sections.append("## Code examples")
        if code:
            for item in code:
                lang = item.get("language", "unknown")
                ctx = f" ({item.get('context', '')})" if item.get("context") else ""
                sections.append(f"- `{lang}`{ctx} from {item.get('url', '')}")
                sections.append(f"```{lang}\n{item.get('snippet', '')}\n```")
        else:
            sections.append("- No code examples found.")
        return "\n".join(sections)

    def _prompt_response(self, request_id: Any, text: str) -> Dict:
        return self._success_response(
            request_id,
            {
                "messages": [
                    {
                        "role": "user",
                        "content": {"type": "text", "text": text},
                    }
                ]
            },
        )

    def _crawler_status(self) -> Dict[str, bool]:
        return {
            "smart": SMART_CRAWLER_AVAILABLE,
            "selenium": SELENIUM_AVAILABLE,
            "ultrafast": ULTRAFAST_AVAILABLE,
        }

    # ------------------------------------------------------------------ #
    # JSON-RPC envelope helpers                                             #
    # ------------------------------------------------------------------ #

    def _coerce_int(self, value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = default
        return max(minimum, min(number, maximum))

    def _success_response(self, request_id: Any, result: Dict) -> Dict:
        response: Dict[str, Any] = {"jsonrpc": "2.0", "result": result}
        if request_id is not None:
            response["id"] = request_id
        return response

    def _error_response(self, request_id: Any, code: int, message: str) -> Dict:
        response: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "error": {"code": code, "message": message},
        }
        if request_id is not None:
            response["id"] = request_id
        return response


mcp_server = MCPServer()
