"""
Strict JSON-RPC 2.0 dispatcher for MCP protocol.
Validates envelope before routing to handlers.
"""

import json
import logging
from typing import Any, Optional

from mcp_server.logging_utils import setup_logging

logger = setup_logging(__name__)


class MCPProtocol:

    def __init__(self, tools, resources):
        self.tools = tools
        self.resources = resources

        self._methods = {
            "initialize":       self._handle_initialize,
            "tools/list":       self._handle_tools_list,
            "tools/call":       self._handle_tools_call,
            "resources/list":   self._handle_resources_list,
            "resources/read":   self._handle_resources_read,
            "prompts/list":     self._handle_prompts_list,
            "prompts/get":      self._handle_prompts_get,
            "ping":             self._handle_ping,
        }

    # ─── Dispatcher ───────────────────────────────────────────────────────────

    def dispatch(self, data: Any) -> Optional[dict]:
        """
        Validate JSON-RPC 2.0 envelope and route to handler.
        Returns None for notifications (no id field).
        """
        if not isinstance(data, dict):
            return self._error(None, -32700, "Parse error: expected JSON object")

        # Strict JSON-RPC 2.0 check
        if data.get("jsonrpc") != "2.0":
            return self._error(
                data.get("id"),
                -32600,
                "Invalid Request: 'jsonrpc' must be '2.0'"
            )

        method = data.get("method")
        if not method or not isinstance(method, str):
            return self._error(
                data.get("id"),
                -32600,
                "Invalid Request: 'method' must be a non-empty string"
            )

        req_id = data.get("id")          # None is valid for notifications
        params = data.get("params", {})
        if params is None:
            params = {}

        # Coerce string params safely (don't silently swallow errors)
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except json.JSONDecodeError:
                return self._error(req_id, -32602, f"Invalid params: could not parse string as JSON")

        handler = self._methods.get(method)
        if not handler:
            return self._error(req_id, -32601, f"Method not found: {method}")

        try:
            result = handler(params)
            # Notifications have no id and expect no response
            if req_id is None and method not in ("initialize", "tools/list"):
                return None
            return {"jsonrpc": "2.0", "id": req_id, "result": result}

        except MCPError as e:
            logger.warning(f"MCP error in {method}: {e.message}")
            return self._error(req_id, e.code, e.message)
        except Exception as e:
            logger.exception(f"Unhandled error in method {method}")
            return self._error(req_id, -32603, f"Internal error: {e}")

    # ─── Handlers ─────────────────────────────────────────────────────────────

    def _handle_initialize(self, params: dict) -> dict:
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools":     {"listChanged": False},
                "resources": {"listChanged": False, "subscribe": False},
                "prompts":   {"listChanged": False}
            },
            "serverInfo": {
                "name":    "scrapee",
                "version": "2.0.0"
            },
            # ✅ This is what makes the agent use tools without being asked
            "instructions": (
                "You have access to a live web scraping and documentation search server. "
                "ALWAYS use 'search_docs' or 'scrape_url' before answering any question "
                "about a library, API, framework, package, or when the user provides a URL. "
                "NEVER answer documentation or technical questions from training memory — "
                "always fetch live data first. "
                "After calling search_docs, read the returned resource_uris using "
                "resources/read to get the full document content before responding. "
                "If search_docs returns no results, call scrape_url to ingest fresh content, "
                "then search again."
            )
        }

    def _handle_tools_list(self, params: dict) -> dict:
        return {"tools": self.tools.list_tools()}

    def _handle_tools_call(self, params: dict) -> dict:
        name = params.get("name")
        if not name:
            raise MCPError(-32602, "Invalid params: 'name' is required for tools/call")

        args = params.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                raise MCPError(-32602, f"Invalid params: 'arguments' could not be parsed as JSON")

        return self.tools.call(name, args)

    def _handle_resources_list(self, params: dict) -> dict:
        return {"resources": self.resources.list_resources()}

    def _handle_resources_read(self, params: dict) -> dict:
        uri = params.get("uri")
        if not uri:
            raise MCPError(-32602, "Invalid params: 'uri' is required for resources/read")
        try:
            return self.resources.read_resource(uri)
        except KeyError as e:
            raise MCPError(-32602, f"Resource not found: {e}")


    def _handle_prompts_list(self, params: dict) -> dict:
        return {"prompts": []}

    def _handle_prompts_get(self, params: dict) -> dict:
        raise MCPError(-32601, "No prompts defined")

    def _handle_ping(self, params: dict) -> dict:
        return {}

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _error(self, req_id, code: int, message: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message}
        }


class MCPError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(message)
