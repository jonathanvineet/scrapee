"""Error models used by MCP protocol handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class MCPException(Exception):
    """Structured internal exception mapped to JSON-RPC errors."""

    code: int
    message: str
    data: Optional[Dict[str, Any]] = None

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message
