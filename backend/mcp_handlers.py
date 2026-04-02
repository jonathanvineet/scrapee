"""
mcp_handlers.py
---------------
Drop-in MCP tool handlers that wire ContentFilter into the scrape pipeline.

What this fixes vs the old approach:
  - Raw links[], images[] arrays are NEVER stored or sent to the agent
  - Low-quality pages are rejected before touching the database
  - API responses are compact (title + url + snippet, not full content dumps)
  - Rejection stats are returned so you can tune thresholds
"""

from __future__ import annotations

import logging
import time
from typing import Callable

from backend.content_filter import ContentFilter

logger = logging.getLogger(__name__)

_filter = ContentFilter()   # stateless, safe to share


# ---------------------------------------------------------------------------
# scrape_url handler
# ---------------------------------------------------------------------------

def handle_scrape_url(
    arguments: dict,
    store,
    crawl_fn: Callable,     # crawl_fn(url, max_pages, max_depth) → list[dict]
) -> dict:
    """
    MCP handler for the scrape_url tool.

    Returns compact stats — never raw links/images/heading arrays.
    """
    url       = (arguments.get("url") or "").strip()
    max_depth = int(arguments.get("max_depth", 2))
    max_pages = int(arguments.get("max_pages", 20))
    mode      = arguments.get("mode", "smart")

    if not url:
        return {"error": "url is required"}

    t0 = time.time()

    # 1. Crawl
    try:
        raw_pages: list[dict] = crawl_fn(url, max_pages=max_pages, max_depth=max_depth)
    except Exception as exc:
        logger.error("Crawl failed: %s", exc)
        return {"error": str(exc), "scraped_count": 0}

    # 2. Filter (strips links/images, rejects nav/marketing pages)
    clean_docs = _filter.process_batch(raw_pages)

    # 3. Store
    indexed, failed = 0, []
    for doc in clean_docs:
        try:
            doc_id = store.save_doc(
                url=doc["url"],
                title=doc["title"],
                content=doc["content"],
                code_blocks=doc.get("code_blocks", []),
            )
            if doc_id:
                indexed += 1
            else:
                failed.append(doc["url"])
        except Exception as exc:
            logger.warning("Store error %s: %s", doc["url"], exc)
            failed.append(doc["url"])

    return {
        "scraped_count":  len(raw_pages),
        "passed_filter":  len(clean_docs),
        "rejected_count": len(raw_pages) - len(clean_docs),
        "indexed_count":  indexed,
        "failed_urls":    failed[:10],
        "duration_seconds": round(time.time() - t0, 2),
        # Compact samples: title + url + 350-char snippet ONLY
        "sample_docs": [_filter.make_sample(d) for d in clean_docs[:3]],
    }


# ---------------------------------------------------------------------------
# search_and_get handler
# ---------------------------------------------------------------------------

def handle_search_and_get(arguments: dict, store) -> dict:
    """
    MCP handler for search_and_get.

    Returns compact results the agent can use immediately.
    Full content is available via a separate get_doc(url) call if needed.
    """
    query = (arguments.get("query") or "").strip()
    limit = min(int(arguments.get("limit", 5)), 20)

    if not query:
        return {"error": "query is required", "results": []}

    raw = store.search_and_get(query, limit=limit)

    results = []
    for r in raw:
        content = r.get("content", "")
        snippet = (content[:400].rsplit(" ", 1)[0] + "…"
                   if len(content) > 400 else content)
        results.append({
            "title":           r.get("title", ""),
            "url":             r.get("url", ""),
            "snippet":         snippet,
            "domain":          r.get("domain", ""),
            "relevance_score": round(r.get("relevance_score", 0), 2),
        })

    return {"query": query, "result_count": len(results), "results": results}
