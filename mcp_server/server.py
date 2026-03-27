"""
MCP Server entry point.
Supports two transports controlled by MCP_TRANSPORT env var:
  - stdio  → for VS Code local dev (default)
  - http   → for Vercel production
"""

import sys
import os
import json
import logging

from mcp_server.protocol import MCPProtocol
from mcp_server.storage.sqlite_store import SQLiteStore
from mcp_server.tools.registry import ToolRegistry
from mcp_server.resources.registry import ResourceRegistry
from mcp_server.ingestion.service import IngestionService
from mcp_server.scraper.web_scraper import WebScraper
from mcp_server.config import Config
from mcp_server.logging_utils import setup_logging

logger = setup_logging(__name__)


def build_protocol() -> MCPProtocol:
    """Wire up all dependencies and return a ready protocol handler."""
    config = Config()
    store = SQLiteStore(config.sqlite_path)
    scraper = WebScraper(config)
    ingestion = IngestionService(store, scraper)
    tools = ToolRegistry(store, scraper, ingestion)
    resources = ResourceRegistry(store)
    return MCPProtocol(tools, resources)


# ─── STDIO transport (VS Code local dev) ──────────────────────────────────────

def run_stdio(protocol: MCPProtocol):
    """
    Standard MCP stdio loop.
    VS Code spawns this process and communicates via stdin/stdout.
    Each line is one JSON-RPC request; each response is one JSON line.
    """
    logger.info("MCP server started — stdio transport")
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            request = json.loads(raw_line)
        except json.JSONDecodeError as e:
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"}
            }
            _write_stdout(error_response)
            continue

        response = protocol.dispatch(request)
        if response is not None:  # None = notification, no response needed
            _write_stdout(response)


def _write_stdout(data: dict):
    sys.stdout.write(json.dumps(data) + "\n")
    sys.stdout.flush()


# ─── HTTP transport (Vercel production) ───────────────────────────────────────

def build_flask_app(protocol: MCPProtocol):
    """
    Returns a Flask app that handles MCP over HTTP.
    Used by Vercel via backend/api/mcp.py shim.
    """
    from flask import Flask, request as flask_request, jsonify

    app = Flask(__name__)

    @app.route("/mcp", methods=["GET", "POST"])
    def mcp_endpoint():
        if flask_request.method == "GET":
            return jsonify({
                "status": "ok",
                "transport": "http",
                "server": "scrapee-mcp",
                "version": "2.0.0"
            })

        try:
            data = flask_request.get_json(force=True, silent=True)
            if data is None:
                return jsonify({
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error: invalid JSON body"}
                }), 400

            response = protocol.dispatch(data)
            return jsonify(response)

        except Exception as e:
            logger.exception("Unhandled HTTP MCP error")
            return jsonify({
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32603, "message": f"Internal error: {e}"}
            }), 500

    @app.route("/api/health")
    def health():
        try:
            stats = protocol.tools.store.get_stats()
            storage = "sqlite"
        except Exception as e:
            stats = {}
            storage = f"error: {e}"

        return jsonify({
            "status": "ok",
            "transport": "http",
            "storage": storage,
            "stats": stats,
            "crawlers": protocol.tools.get_crawler_status()
        })

    return app


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    protocol = build_protocol()

    if transport == "stdio":
        run_stdio(protocol)
    elif transport == "http":
        app = build_flask_app(protocol)
        port = int(os.getenv("PORT", 8000))
        app.run(host="0.0.0.0", port=port)
    else:
        logger.error(f"Unknown MCP_TRANSPORT: {transport}. Use 'stdio' or 'http'.")
        sys.exit(1)


if __name__ == "__main__":
    main()
