"""Compatibility shim for MCP access via HTTP and stdio."""

from __future__ import annotations

from flask import Flask, jsonify, request
from flask_cors import CORS

from mcp_server.protocol import MCPProtocolServer


protocol_server = MCPProtocolServer()

app = Flask(__name__)
CORS(app)


@app.route("/api/mcp", methods=["POST"])
def mcp_endpoint():
    payload = request.get_json(silent=True)
    if payload is None:
        return (
            jsonify(
                {
                    "jsonrpc": "2.0",
                    "error": {"code": -32700, "message": "Parse error"},
                    "id": None,
                }
            ),
            400,
        )

    response = protocol_server.handle_envelope(payload)
    if response is None:
        return "", 204
    return jsonify(response)


@app.route("/api/health", methods=["GET"])
def health():
    stats = protocol_server.store.stats()
    return jsonify({"status": "ok", "storage": "sqlite", "stats": stats})


if __name__ == "__main__":
    from mcp_server.server import main

    raise SystemExit(main())
