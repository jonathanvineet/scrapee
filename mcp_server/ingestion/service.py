"""Ingestion orchestration for scraping, persistence, and auto-seeding."""

from __future__ import annotations

from typing import Dict, Optional

from mcp_server.config import AUTO_INGEST_HINTS, SCRAPE_MAX_DEPTH, SCRAPE_MAX_PAGES
from mcp_server.logging_utils import get_logger
from mcp_server.storage import SQLiteStore
from mcp_server.scraper import WebScraper
from mcp_server.utils import clamp_int, first_url_in_text, normalize_source_url


logger = get_logger(__name__)


class IngestionService:
    """Coordinates scraper output with persistent storage."""

    def __init__(self, store: SQLiteStore, scraper: WebScraper):
        self.store = store
        self.scraper = scraper

    def ingest_url(self, url: str, *, max_depth: int = 0, max_pages: int = SCRAPE_MAX_PAGES) -> Dict[str, object]:
        normalized = normalize_source_url(url)
        crawl_result = self.scraper.crawl(
            normalized,
            max_depth=clamp_int(max_depth, minimum=0, maximum=SCRAPE_MAX_DEPTH, default=0),
            max_pages=clamp_int(max_pages, minimum=1, maximum=SCRAPE_MAX_PAGES, default=20),
        )

        persisted_docs = []
        code_resources = []
        for page in crawl_result["pages"]:
            saved = self.store.upsert_document(
                uri=str(page["uri"]),
                source_url=str(page["source_url"]),
                title=str(page["title"]),
                content=str(page["content"]),
                metadata=dict(page["metadata"]),
                chunks=list(page["chunks"]),
                code_blocks=list(page["code_blocks"]),
            )
            persisted_docs.append(
                {
                    "uri": saved["uri"],
                    "source_url": saved["source_url"],
                    "title": saved["title"],
                    "chunk_count": saved["chunk_count"],
                    "code_resource_count": len(saved["code_uris"]),
                }
            )
            code_resources.extend(saved["code_uris"])

        summary = {
            "start_url": crawl_result["start_url"],
            "documents_ingested": len(persisted_docs),
            "documents": persisted_docs,
            "document_resource_uris": [doc["uri"] for doc in persisted_docs],
            "code_resource_uris": code_resources,
            "errors": crawl_result["errors"],
        }
        logger.info(
            "Ingested %s documents from %s",
            summary["documents_ingested"],
            summary["start_url"],
        )
        return summary

    def auto_ingest_for_query(self, query: str) -> Optional[Dict[str, object]]:
        explicit_url = first_url_in_text(query)
        if explicit_url:
            return self.ingest_url(explicit_url, max_depth=0, max_pages=5)

        lowered = query.lower()
        for keyword, url in AUTO_INGEST_HINTS.items():
            if keyword in lowered:
                try:
                    return self.ingest_url(url, max_depth=1, max_pages=12)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Auto-ingest failed for keyword %s: %s", keyword, exc)
                    return None
        return None
