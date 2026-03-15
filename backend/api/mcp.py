"""Compatibility shim for deployments that still point at backend/api/mcp.py."""
import os
import sys

from flask import Flask, jsonify, request
from flask_cors import CORS


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CURRENT_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from mcp import mcp_server


app = Flask(__name__)
CORS(app)


@app.route("/api/mcp", methods=["POST"])
def mcp_endpoint():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify(
            {
                "jsonrpc": "2.0",
                "error": {"code": -32700, "message": "Parse error"},
            }
        ), 400

    response = mcp_server.handle_request(data)
    if response is None:
        return "", 204
    return jsonify(response)


@app.route("/api/health", methods=["GET"])
def health_check():
    stats = mcp_server.store.get_stats()
    return jsonify(
        {
            "status": "ok" if stats.get("sqlite_ok") else "degraded",
            "storage": "sqlite",
            "docs": stats.get("total_docs", 0),
            "code_blocks": stats.get("total_code_blocks", 0),
        }
    )
