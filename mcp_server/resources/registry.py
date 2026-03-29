"""MCP resources listing and read handlers."""

from __future__ import annotations

import json
import logging
from typing import Dict, List

from mcp_server.logging_utils import setup_logging
from mcp_server.storage.sqlite_store import SQLiteStore

logger = setup_logging(__name__)


class ResourceRegistry:
    """Exposes documentation and code resources as MCP URIs."""

    def __init__(self, store: SQLiteStore):
        self.store = store

    def list_resources(self) -> List[Dict[str, object]]:
        """List all available resources (documents and code snippets)."""
        docs = self.store.list_docs(limit=100)
        resources: List[Dict[str, object]] = []

        # Add index resources
        resources.append({
            "uri": "docs://index",
            "name": "Indexed documentation catalog",
            "description": "Catalog of all indexed docs with source URLs and titles.",
            "mimeType": "application/json",
        })

        # Add document resources
        for doc in docs:
            resources.append({
                "uri": f"docs://{doc.get('id', '')}",
                "name": doc.get("title", "Document"),
                "description": f"Documentation from {doc.get('url', 'unknown')}",
                "mimeType": "text/plain",
            })

        return resources

    def read_resource(self, uri: str) -> Dict[str, object]:
        """Read a specific resource by URI."""
        if uri == "docs://index":
            payload = self.store.list_docs(limit=100)
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps(payload, ensure_ascii=False, indent=2),
                    }
                ]
            }

        if uri.startswith("docs://"):
            doc_id = uri.replace("docs://", "")
            document = self.store.get_doc_by_id(doc_id)
            if not document:
                logger.warning(f"Document not found: {uri}")
                raise KeyError(f"Unknown document resource: {uri}")
            
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "text/plain",
                        "text": document.get("content", ""),
                    }
                ]
            }

        logger.warning(f"Unknown resource URI: {uri}")
        raise KeyError(f"Unknown resource URI: {uri}")
