"""Configuration and constants for the MCP server."""

from __future__ import annotations

import os
from pathlib import Path


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "scrapee-mcp"
SERVER_VERSION = "3.0.0"

SCRAPE_REQUEST_TIMEOUT_SECONDS = int(os.getenv("SCRAPEE_SCRAPE_TIMEOUT_SECONDS", "8"))
SCRAPE_MAX_PAGES = int(os.getenv("SCRAPEE_SCRAPE_MAX_PAGES", "30"))
SCRAPE_MAX_DEPTH = int(os.getenv("SCRAPEE_SCRAPE_MAX_DEPTH", "2"))
SEARCH_DEFAULT_LIMIT = int(os.getenv("SCRAPEE_SEARCH_DEFAULT_LIMIT", "5"))

_DEFAULT_DB_PATH = (
    Path(os.getenv("SCRAPEE_MCP_DB_PATH", "")).expanduser()
    if os.getenv("SCRAPEE_MCP_DB_PATH")
    else Path(__file__).resolve().parent / "storage" / "data" / "mcp_docs.db"
)
DB_PATH = str(_DEFAULT_DB_PATH)

ALLOWED_DOMAINS = {
    domain.strip().lower()
    for domain in os.getenv("SCRAPEE_ALLOWED_DOMAINS", "").split(",")
    if domain.strip()
}

AUTO_INGEST_HINTS = {
    "python": "https://docs.python.org/3/",
    "react": "https://react.dev/reference/react",
    "next": "https://nextjs.org/docs",
    "fastapi": "https://fastapi.tiangolo.com/",
    "flask": "https://flask.palletsprojects.com/",
    "docker": "https://docs.docker.com/",
    "kubernetes": "https://kubernetes.io/docs/home/",
    "typescript": "https://www.typescriptlang.org/docs/",
    "javascript": "https://developer.mozilla.org/en-US/docs/Web/JavaScript",
}


class Config:
    def __init__(self):
        self.sqlite_path = os.getenv("SQLITE_DB_PATH", DB_PATH)
        self.allowed_domains = ALLOWED_DOMAINS
