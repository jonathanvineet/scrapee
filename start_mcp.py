#!/usr/bin/env python3
"""Launch the production MCP server over STDIO."""

from mcp_server.server import main


if __name__ == "__main__":
    raise SystemExit(main())
