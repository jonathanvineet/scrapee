"""MCP tools definitions and execution handlers."""

from __future__ import annotations

from typing import Dict, List

from mcp_server.config import SEARCH_DEFAULT_LIMIT
from mcp_server.ingestion import IngestionService
from mcp_server.storage import SQLiteStore
from mcp_server.utils import clamp_int, normalize_source_url


class ToolRegistry:
    """Defines and executes MCP tools with machine-friendly structured output."""

    def __init__(self, store: SQLiteStore, ingestion: IngestionService):
        self.store = store
        self.ingestion = ingestion
        self._handlers = {
            "search_docs": self._search_docs,
            "get_document": self._get_document,
            "scrape_url": self._scrape_url,
            "search_code": self._search_code,
        }

    def list_tools(self) -> List[Dict[str, object]]:
        return [
            {
                "name": "search_docs",
                "description": (
                    "Search indexed documentation and return matching document resource URIs. "
                    "If no matches are found, the server may auto-ingest relevant docs and retry."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Documentation search query."},
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 20,
                            "default": SEARCH_DEFAULT_LIMIT,
                            "description": "Maximum number of document matches.",
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "get_document",
                "description": (
                    "Resolve a document by resource URI (docs://...) or source URL, and return "
                    "metadata plus canonical document resource URI for resources/read."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "uri": {"type": "string", "description": "Document resource URI (docs://...)."},
                        "source_url": {"type": "string", "description": "Original HTTP(S) URL for the document."},
                    },
                    "anyOf": [{"required": ["uri"]}, {"required": ["source_url"]}],
                    "additionalProperties": False,
                },
            },
            {
                "name": "scrape_url",
                "description": (
                    "Scrape and ingest a URL into local storage, then return created document/code resource URIs."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "HTTP(S) URL to scrape and ingest."},
                        "max_depth": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 2,
                            "default": 0,
                            "description": "Internal-link crawl depth.",
                        },
                        "max_pages": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 30,
                            "default": 10,
                            "description": "Maximum pages to crawl.",
                        },
                    },
                    "required": ["url"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "search_code",
                "description": (
                    "Search indexed code snippets and return code:// resource URIs with linked docs:// URIs."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Code search query."},
                        "language": {"type": "string", "description": "Optional language filter (e.g. python)."},
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 20,
                            "default": SEARCH_DEFAULT_LIMIT,
                            "description": "Maximum number of snippet matches.",
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        ]

    def call(self, name: str, arguments: Dict[str, object]) -> Dict[str, object]:
        handler = self._handlers.get(name)
        if handler is None:
            raise ValueError(f"Unknown tool: {name}")
        return handler(arguments)

    def _search_docs(self, arguments: Dict[str, object]) -> Dict[str, object]:
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise ValueError("search_docs requires a non-empty 'query'.")
        limit = clamp_int(arguments.get("limit"), minimum=1, maximum=20, default=SEARCH_DEFAULT_LIMIT)
        results = self.store.search_documents(query, limit=limit)
        auto_ingested = False
        ingestion_result = None
        if not results:
            ingestion_result = self.ingestion.auto_ingest_for_query(query)
            if ingestion_result and ingestion_result.get("documents_ingested", 0) > 0:
                auto_ingested = True
                results = self.store.search_documents(query, limit=limit)

        payload = {
            "query": query,
            "total": len(results),
            "documents": [
                {
                    "uri": row["uri"],
                    "title": row.get("title") or row["source_url"],
                    "source_url": row["source_url"],
                    "snippet": row.get("snippet", ""),
                    "score": row.get("score", 0.0),
                }
                for row in results
            ],
            "resource_uris": [row["uri"] for row in results],
            "auto_ingested": auto_ingested,
            "ingestion": ingestion_result,
        }
        return payload

    def _get_document(self, arguments: Dict[str, object]) -> Dict[str, object]:
        uri = str(arguments.get("uri", "")).strip()
        source_url = normalize_source_url(str(arguments.get("source_url", "")).strip())
        document = None
        if uri:
            document = self.store.get_document_by_uri(uri)
        elif source_url:
            document = self.store.get_document_by_source_url(source_url)
            if not document:
                self.ingestion.ingest_url(source_url, max_depth=0, max_pages=5)
                document = self.store.get_document_by_source_url(source_url)
        else:
            raise ValueError("get_document requires 'uri' or 'source_url'.")

        if not document:
            raise ValueError("Document was not found.")

        payload = {
            "document": {
                "uri": document["uri"],
                "source_url": document["source_url"],
                "title": document.get("title", ""),
                "content_length": len(document.get("content", "")),
                "scraped_at": document.get("scraped_at", ""),
                "updated_at": document.get("updated_at", ""),
            },
            "resource_uri": document["uri"],
            "code_resource_uris": [snippet["uri"] for snippet in document.get("code_snippets", [])],
        }
        return payload

    def _scrape_url(self, arguments: Dict[str, object]) -> Dict[str, object]:
        raw_url = str(arguments.get("url", "")).strip()
        if not raw_url:
            raise ValueError("scrape_url requires non-empty 'url'.")
        max_depth = clamp_int(arguments.get("max_depth"), minimum=0, maximum=2, default=0)
        max_pages = clamp_int(arguments.get("max_pages"), minimum=1, maximum=30, default=10)
        ingestion = self.ingestion.ingest_url(raw_url, max_depth=max_depth, max_pages=max_pages)
        return {
            "start_url": ingestion["start_url"],
            "documents_ingested": ingestion["documents_ingested"],
            "document_resource_uris": ingestion["document_resource_uris"],
            "code_resource_uris": ingestion["code_resource_uris"],
            "errors": ingestion["errors"],
        }

    def _search_code(self, arguments: Dict[str, object]) -> Dict[str, object]:
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise ValueError("search_code requires a non-empty 'query'.")
        language = str(arguments.get("language", "")).strip().lower() or None
        limit = clamp_int(arguments.get("limit"), minimum=1, maximum=20, default=SEARCH_DEFAULT_LIMIT)
        rows = self.store.search_code(query, limit=limit, language=language)

        return {
            "query": query,
            "language": language,
            "total": len(rows),
            "matches": [
                {
                    "uri": row["uri"],
                    "document_uri": row["document_uri"],
                    "source_url": row["source_url"],
                    "title": row.get("title", ""),
                    "language": row.get("language", "text"),
                    "snippet": row.get("snippet", ""),
                    "context": row.get("context", ""),
                    "score": row.get("score", 0.0),
                }
                for row in rows
            ],
            "resource_uris": [row["uri"] for row in rows],
            "document_resource_uris": sorted({row["document_uri"] for row in rows}),
        }
