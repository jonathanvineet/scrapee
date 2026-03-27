"""MCP resources listing and read handlers."""

from __future__ import annotations

import json
from typing import Dict, List

from mcp_server.storage import SQLiteStore


class ResourceRegistry:
    """Exposes documentation and code resources as MCP URIs."""

    def __init__(self, store: SQLiteStore):
        self.store = store

    def list_resources(self) -> List[Dict[str, object]]:
        documents = self.store.list_documents()
        code = self.store.list_code_resources()
        resources: List[Dict[str, object]] = [
            {
                "uri": "docs://index",
                "name": "Indexed documentation catalog",
                "description": "Catalog of all indexed docs with source URLs and titles.",
                "mimeType": "application/json",
            },
            {
                "uri": "code://index",
                "name": "Indexed code catalog",
                "description": "Catalog of all indexed code snippets and owning documents.",
                "mimeType": "application/json",
            },
        ]

        for doc in documents:
            resources.append(
                {
                    "uri": doc["uri"],
                    "name": doc.get("title") or doc["source_url"],
                    "description": f"Documentation page from {doc['source_url']}",
                    "mimeType": "text/plain",
                }
            )

        for snippet in code:
            resources.append(
                {
                    "uri": snippet["uri"],
                    "name": f"{snippet['language']} snippet from {snippet['source_url']}",
                    "description": f"Code example associated with {snippet['document_uri']}",
                    "mimeType": "text/plain",
                }
            )
        return resources

    def read_resource(self, uri: str) -> Dict[str, object]:
        if uri == "docs://index":
            payload = self.store.list_documents()
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps(payload, ensure_ascii=False, indent=2),
                    }
                ]
            }
        if uri == "code://index":
            payload = self.store.list_code_resources()
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
            document = self.store.get_document_by_uri(uri)
            if not document:
                raise KeyError(f"Unknown document resource: {uri}")
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "text/plain",
                        "text": document["content"],
                    }
                ]
            }

        if uri.startswith("code://"):
            snippet = self.store.get_code_by_uri(uri)
            if not snippet:
                raise KeyError(f"Unknown code resource: {uri}")
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "text/plain",
                        "text": snippet["snippet"],
                    }
                ]
            }

        raise KeyError(f"Unknown resource URI: {uri}")
