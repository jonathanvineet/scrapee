#!/usr/bin/env python3
"""
Stdio transport for the Scrapee MCP server.

Speaks newline-delimited JSON-RPC 2.0 over stdin/stdout so any MCP client
(Claude Desktop, VS Code, Cursor, ...) can spawn Scrapee as a local server:

    python3 backend/mcp_stdio.py

The heavy lifting (initialize, tools/list, tools/call, resources/*, prompts/*)
is delegated to the existing engine singleton `mcp_engine.mcp_server`.

IMPORTANT: stdout carries ONLY protocol messages. The engine prints banners at
import time, and background threads (the auto-crawler) print at arbitrary times,
so we grab the real stdout up front and then point `sys.stdout` at stderr for
the rest of the process. Only `_write()` ever touches the protocol channel.
"""
import json
import sys

# Capture the true protocol channel before anything can write to it, then send
# every other stdout write (this module, the engine, background threads) to
# stderr so it can never corrupt the JSON-RPC stream.
_PROTOCOL_OUT = sys.stdout
sys.stdout = sys.stderr

from mcp_engine import mcp_server  # noqa: E402 - must follow the stdout swap


def _write(obj: dict) -> None:
    """Emit a single JSON-RPC message as one line on the protocol channel."""
    _PROTOCOL_OUT.write(json.dumps(obj) + "\n")
    _PROTOCOL_OUT.flush()


def _error(msg_id, code: int, message: str) -> None:
    _write({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}})


def main() -> int:
    print("[mcp_stdio] Scrapee MCP server ready on stdio", file=sys.stderr)
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except (ValueError, TypeError) as exc:
            _error(None, -32700, f"Parse error: {exc}")
            continue

        try:
            response = mcp_server.handle_request(msg)
        except Exception as exc:  # noqa: BLE001 - the loop must outlive any handler error
            msg_id = msg.get("id") if isinstance(msg, dict) else None
            _error(msg_id, -32603, f"Internal error: {exc}")
            continue

        # Notifications (no "id") and other no-reply cases return None.
        if response is not None:
            _write(response)

    print("[mcp_stdio] stdin closed, shutting down", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        pass
