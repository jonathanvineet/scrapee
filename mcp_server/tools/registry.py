"""
Tool definitions and handlers.
Descriptions are directive (tell the model WHEN to call)
not descriptive (tell the model WHAT the tool does).
"""

import json
import logging
from mcp_server.logging_utils import setup_logging

logger = setup_logging(__name__)


class ToolRegistry:

    def __init__(self, store, scraper, ingestion):
        self.store = store
        self.scraper = scraper
        self.ingestion = ingestion

        self._handlers = {
            "search_docs":    self._handle_search_docs,
            "scrape_url":     self._handle_scrape_url,
            "search_code":    self._handle_search_code,
            "get_document":   self._handle_get_document,
            "list_docs":      self._handle_list_docs,
        }

    # ─── Tool definitions ─────────────────────────────────────────────────────

    def list_tools(self) -> list:
        return [
            {
                "name": "search_docs",
                # ✅ Directive: tells model WHEN not WHAT
                "description": (
                    "ALWAYS call this first before answering any question about a library, "
                    "API, framework, package, or 'how do I...' question. "
                    "Never answer technical questions from training memory when this tool "
                    "is available. Returns resource_uris — follow up with resources/read "
                    "on each URI to get the full content before responding to the user."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max results to return",
                            "default": 5
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "scrape_url",
                "description": (
                    "Call this whenever the user provides a URL or asks about content "
                    "from a specific page or website. Always use this instead of recalling "
                    "web content from memory. After scraping, call search_docs to find "
                    "relevant content from the freshly ingested page."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL to scrape and index"
                        },
                        "max_depth": {
                            "type": "integer",
                            "description": "How many link levels deep to crawl",
                            "default": 1
                        },
                        "max_pages": {
                            "type": "integer",
                            "description": "Max pages to crawl in one run",
                            "default": 5
                        }
                    },
                    "required": ["url"]
                }
            },
            {
                "name": "search_code",
                "description": (
                    "Call this when the user asks for code examples, implementation "
                    "samples, or 'show me how to...' questions. Searches indexed code "
                    "snippets extracted from scraped documentation. Returns resource_uris "
                    "— follow up with resources/read to get the full snippet."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "What to search for in code"
                        },
                        "language": {
                            "type": "string",
                            "description": "Filter by programming language (optional)"
                        },
                        "limit": {
                            "type": "integer",
                            "default": 5
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "get_document",
                "description": (
                    "Retrieve full content of a specific document by its URI or URL. "
                    "Use this when you have a resource URI from search_docs results "
                    "and need the complete document text."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "identifier": {
                            "type": "string",
                            "description": "docs:// URI or source URL of the document"
                        }
                    },
                    "required": ["identifier"]
                }
            },
            {
                "name": "list_docs",
                "description": (
                    "List all documents that have been scraped and stored. "
                    "Use this when the user asks what documentation is available "
                    "or wants to browse indexed content."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 20}
                    }
                }
            }
        ]

    # ─── Handlers ─────────────────────────────────────────────────────────────

    def call(self, name: str, args: dict) -> dict:
        handler = self._handlers.get(name)
        if not handler:
            return self._error(f"Unknown tool: {name}")
        try:
            return handler(args)
        except Exception as e:
            logger.exception(f"Tool error in {name}")
            return self._error(str(e))

    def _handle_search_docs(self, args: dict) -> dict:
        query = args.get("query", "").strip()
        limit = int(args.get("limit", 5))

        if not query:
            return self._error("'query' is required")

        results = self.store.search_with_snippets(query, limit)

        # Auto-ingest fallback — try to find and scrape something relevant
        auto_ingested = False
        if not results:
            logger.info(f"No results for '{query}', attempting auto-ingest")
            try:
                self.ingestion.ingest_query(query)
                results = self.store.search_with_snippets(query, limit)
                auto_ingested = bool(results)
            except Exception as e:
                logger.warning(f"Auto-ingest failed: {e}")

        resource_uris = [f"docs://{r['id']}" for r in results]

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({
                        "results": results,
                        "resource_uris": resource_uris,
                        # ✅ Agent knows what happened — prevents redundant calls
                        "_meta": {
                            "total": len(results),
                            "query": query,
                            "auto_ingested": auto_ingested,
                            "hint": (
                                "Call resources/read with each URI in resource_uris "
                                "to get full document content."
                            ) if results else (
                                "No results found. Try scrape_url with a relevant "
                                "documentation URL to ingest content first."
                            )
                        }
                    }, indent=2)
                }
            ]
        }

    def _handle_scrape_url(self, args: dict) -> dict:
        url = args.get("url", "").strip()
        if not url:
            return self._error("'url' is required")

        max_depth = int(args.get("max_depth", 1))
        max_pages = int(args.get("max_pages", 5))

        # Validate URL before scraping
        valid, reason = self.scraper.validate_url(url)
        if not valid:
            return self._error(f"Invalid URL: {reason}")

        try:
            result = self.ingestion.ingest_url(url, max_depth=max_depth, max_pages=max_pages)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({
                            "success": True,
                            "url": url,
                            "pages_ingested": result.get("pages_ingested", 0),
                            "doc_ids": result.get("doc_ids", []),
                            "_meta": {
                                "hint": (
                                    "Content has been indexed. "
                                    "Now call search_docs to find relevant information."
                                )
                            }
                        }, indent=2)
                    }
                ]
            }
        except Exception as e:
            return self._error(f"Scrape failed: {e}")

    def _handle_search_code(self, args: dict) -> dict:
        query = args.get("query", "").strip()
        language = args.get("language")
        limit = int(args.get("limit", 5))

        if not query:
            return self._error("'query' is required")

        results = self.store.search_code_with_context(query, language, limit)
        resource_uris = [f"code://{r['id']}" for r in results]

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({
                        "results": results,
                        "resource_uris": resource_uris,
                        "_meta": {
                            "total": len(results),
                            "query": query,
                            "language_filter": language
                        }
                    }, indent=2)
                }
            ]
        }

    def _handle_get_document(self, args: dict) -> dict:
        identifier = args.get("identifier", "").strip()
        if not identifier:
            return self._error("'identifier' is required")

        # Support both docs:// URI and raw URL
        if identifier.startswith("docs://"):
            doc_id = identifier.replace("docs://", "")
            doc = self.store.get_doc_by_id(doc_id)
        else:
            doc = self.store.get_doc_by_url(identifier)

        if not doc:
            return self._error(f"Document not found: {identifier}")

        return {
            "content": [
                {"type": "text", "text": json.dumps(doc, indent=2)}
            ]
        }

    def _handle_list_docs(self, args: dict) -> dict:
        limit = int(args.get("limit", 20))
        docs = self.store.list_docs(limit=limit)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({
                        "docs": docs,
                        "total": len(docs),
                        "_meta": {
                            "hint": "Use get_document with a URI or search_docs to find specific content."
                        }
                    }, indent=2)
                }
            ]
        }

    def get_crawler_status(self) -> dict:
        """Used by health endpoint."""
        return {
            "smart":     getattr(self.scraper, "smart_available", False),
            "selenium":  getattr(self.scraper, "selenium_available", False),
            "ultrafast": getattr(self.scraper, "ultrafast_available", False),
        }

    def _error(self, message: str) -> dict:
        return {
            "content": [
                {"type": "text", "text": json.dumps({"error": message})}
            ],
            "isError": True
        }
