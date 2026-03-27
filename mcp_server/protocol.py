"""JSON-RPC 2.0 + MCP lifecycle dispatcher."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict

from mcp_server.config import ALLOWED_DOMAINS, DB_PATH, PROTOCOL_VERSION, SERVER_NAME, SERVER_VERSION
from mcp_server.ingestion import IngestionService
from mcp_server.logging_utils import get_logger
from mcp_server.resources import ResourceRegistry
from mcp_server.scraper import WebScraper
from mcp_server.storage import SQLiteStore
from mcp_server.tools import ToolRegistry


logger = get_logger(__name__)


@dataclass
class _MethodContext:
    request_id: Any
    params: Dict[str, Any]


class MCPProtocolServer:
    """Production MCP server implementing core lifecycle methods."""

    def __init__(self, db_path: str = DB_PATH):
        self.store = SQLiteStore(db_path=db_path)
        self.scraper = WebScraper(allowed_domains=ALLOWED_DOMAINS or ())
        self.ingestion = IngestionService(self.store, self.scraper)
        self.tools = ToolRegistry(self.store, self.ingestion)
        self.resources = ResourceRegistry(self.store)

    # ------------------------------------------------------------------ #
    # Public dispatch API
    # ------------------------------------------------------------------ #

    def handle_envelope(self, payload: Any) -> Optional[Dict[str, Any] | list]:
        if isinstance(payload, list):
            responses = []
            for item in payload:
                response = self._handle_single(item)
                if response is not None:
                    responses.append(response)
            return responses or None
        return self._handle_single(payload)

    def _handle_single(self, payload: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return self._error_response(None, -32600, "Invalid Request")

        if payload.get("jsonrpc") != "2.0":
            return self._error_response(payload.get("id"), -32600, "Invalid Request: jsonrpc must be '2.0'")

        method = payload.get("method")
        request_id = payload.get("id")
        params = payload.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return self._error_response(request_id, -32602, "Invalid params: object expected")
        if not isinstance(method, str) or not method:
            return self._error_response(request_id, -32600, "Invalid Request: method is required")

        if request_id is None and method.startswith("notifications/"):
            return None

        context = _MethodContext(request_id=request_id, params=params)
        try:
            if method == "initialize":
                return self._success_response(request_id, self._initialize(context))
            if method == "tools/list":
                return self._success_response(request_id, {"tools": self.tools.list_tools()})
            if method == "tools/call":
                return self._success_response(request_id, self._tools_call(context))
            if method == "resources/list":
                return self._success_response(request_id, {"resources": self.resources.list_resources()})
            if method == "resources/read":
                return self._success_response(request_id, self._resources_read(context))
            if method == "ping":
                return self._success_response(request_id, {"ok": True})
            if request_id is None:
                return None
            return self._error_response(request_id, -32601, f"Method not found: {method}")
        except ValueError as exc:
            return self._error_response(request_id, -32602, str(exc))
        except KeyError as exc:
            return self._error_response(request_id, -32602, str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unhandled error while processing %s", method)
            return self._error_response(request_id, -32603, f"Internal error: {exc}")

    # ------------------------------------------------------------------ #
    # MCP method handlers
    # ------------------------------------------------------------------ #

    def _initialize(self, context: _MethodContext) -> Dict[str, Any]:
        client_version = str(context.params.get("protocolVersion", "")).strip()
        if client_version and client_version != PROTOCOL_VERSION:
            logger.info("Client protocol %s requested; serving %s", client_version, PROTOCOL_VERSION)
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"listChanged": False, "subscribe": False},
            },
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": (
                "Use tools for actions (search/scrape/lookup), then read resource URIs via resources/read "
                "for complete document or code content."
            ),
        }

    def _tools_call(self, context: _MethodContext) -> Dict[str, Any]:
        name = str(context.params.get("name", "")).strip()
        if not name:
            raise ValueError("tools/call requires 'name'.")
        arguments = context.params.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise ValueError("tools/call arguments string must contain valid JSON") from exc
        if not isinstance(arguments, dict):
            raise ValueError("tools/call arguments must be an object.")
        try:
            result = self.tools.call(name, arguments)
        except ValueError as exc:
            return {
                "content": [{"type": "text", "text": str(exc)}],
                "isError": True,
            }
        summary = self._tool_summary(name, result)
        return {
            "content": [{"type": "text", "text": summary}],
            "structuredContent": result,
        }

    def _resources_read(self, context: _MethodContext) -> Dict[str, Any]:
        uri = str(context.params.get("uri", "")).strip()
        if not uri:
            raise ValueError("resources/read requires 'uri'.")
        return self.resources.read_resource(uri)

    def _tool_summary(self, name: str, result: Dict[str, Any]) -> str:
        if name == "search_docs":
            return f"Found {result.get('total', 0)} document matches."
        if name == "search_code":
            return f"Found {result.get('total', 0)} code matches."
        if name == "scrape_url":
            return f"Ingested {result.get('documents_ingested', 0)} documents."
        if name == "get_document":
            doc = result.get("document", {})
            return f"Resolved document {doc.get('uri', '')}."
        return "Tool executed."

    # ------------------------------------------------------------------ #
    # JSON-RPC helpers
    # ------------------------------------------------------------------ #

    def _success_response(self, request_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
        response: Dict[str, Any] = {"jsonrpc": "2.0", "result": result}
        if request_id is not None:
            response["id"] = request_id
        return response

    def _error_response(self, request_id: Any, code: int, message: str, data: Dict[str, Any] | None = None) -> Dict[str, Any]:
        response: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "error": {"code": code, "message": message},
        }
        if data is not None:
            response["error"]["data"] = data
        if request_id is not None:
            response["id"] = request_id
        return response
