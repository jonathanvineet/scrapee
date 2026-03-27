"""STDIO entrypoint for the production MCP server."""

from __future__ import annotations

import json
import sys
from typing import Any

from mcp_server.logging_utils import configure_logging, get_logger
from mcp_server.protocol import MCPProtocolServer


configure_logging(level="INFO")
logger = get_logger(__name__)


def _emit(payload: Any) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    server = MCPProtocolServer()
    logger.info("MCP server started (stdio transport)")

    while True:
        line = sys.stdin.readline()
        if line == "":
            logger.info("STDIN closed, shutting down MCP server")
            return 0

        message = line.strip()
        if not message:
            continue

        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            _emit(
                {
                    "jsonrpc": "2.0",
                    "error": {"code": -32700, "message": "Parse error"},
                    "id": None,
                }
            )
            continue

        response = server.handle_envelope(payload)
        if response is not None:
            _emit(response)


if __name__ == "__main__":
    raise SystemExit(main())
