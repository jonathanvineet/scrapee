from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import time
from urllib.parse import urlparse
from dotenv import load_dotenv

from mcp import (
    IMPORT_ERRORS,
    SCRAPE_TIMEOUT_SECONDS,
    SELENIUM_AVAILABLE,
    SMART_CRAWLER_AVAILABLE,
    ULTRAFAST_AVAILABLE,
    mcp_server,
)
from storage.sqlite_store import get_sqlite_store

load_dotenv()

app = Flask(__name__)

# ─── CORS ─────────────────────────────────────────────────────────────────────
# Development: allow all origins; Production: restrict to known frontends.
_flask_env = os.getenv("FLASK_ENV", "development")

if _flask_env == "development":
    _origins = "*"
else:
    _origins = [
        "http://localhost:3000",
        "http://localhost:8080",
        "https://scrapee-wine.vercel.app",
        "https://scrapee.vercel.app",
    ]
    _vercel_url = os.getenv("VERCEL_URL")
    _frontend_url = os.getenv("FRONTEND_URL")
    if _vercel_url:
        _origins.append(f"https://{_vercel_url}")
    if _frontend_url:
        _origins.append(_frontend_url)

CORS(
    app,
    resources={r"/api/*": {"origins": _origins}, r"/mcp*": {"origins": _origins}},
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    expose_headers=["Content-Type"],
    supports_credentials=True,
    max_age=3600,
)

# ─── Import error tracking ────────────────────────────────────────────────────
_import_errors = dict(IMPORT_ERRORS)


# ─── HTML parsing helper (used by /api/scrape) ────────────────────────────────
from urllib.parse import urljoin
from bs4 import BeautifulSoup


def parse_html(url: str, html: str, mode: str) -> dict:
    """Parse raw HTML into structured data with boilerplate filtering."""
    soup = BeautifulSoup(html, "html.parser")

    JUNK_KEYWORDS = [
        "sign in", "login", "log in", "logout", "sign out", "sign up", "register",
        "create account", "my account", "privacy policy", "terms of service",
        "terms of use", "contact us", "careers", "jobs", "about us", "newsletter",
        "subscribe", "cookie policy", "site map", "sitemap", "help center",
        "support", "faq", "copyright", "all rights reserved", "advertisement",
        "sponsor", "facebook", "twitter", "instagram", "linkedin", "youtube",
        "tiktok", "pinterest", "logo", "icon", "avatar",
    ]

    def is_junk(text: str) -> bool:
        if not text:
            return False
        low = text.lower().strip()
        return any(kw in low for kw in JUNK_KEYWORDS)

    links = []
    for tag in soup.find_all("a", href=True):
        href = urljoin(url, tag["href"])
        text = tag.get_text(strip=True)
        if is_junk(text) or is_junk(href):
            continue
        if href.startswith("http"):
            links.append({"url": href.rstrip("/"), "text": text or href})

    result = {
        "url": url,
        "title": soup.title.string.strip() if soup.title and soup.title.string else "",
        "links": links,
        "links_count": len(links),
    }

    if mode in ("fast", "smart", "pipeline"):
        meta_desc = ""
        meta = soup.find("meta", attrs={"name": "description"})
        if meta:
            meta_desc = meta.get("content", "")

        headings = []
        for tag in soup.find_all(["h1", "h2", "h3"]):
            text = tag.get_text(strip=True)
            if text and not is_junk(text) and len(text) > 2:
                headings.append({"level": tag.name, "text": text})

        paragraphs = []
        for p in soup.find_all("p"):
            text = p.get_text(strip=True)
            if len(text) > 45 and not is_junk(text):
                paragraphs.append(text)

        images = []
        for img in soup.find_all("img", src=True):
            src = urljoin(url, img["src"])
            alt = img.get("alt", "")
            if is_junk(alt) or is_junk(src):
                continue
            images.append({"src": src, "alt": alt})

        result["meta_description"] = meta_desc
        result["headings"] = headings[:30]
        result["paragraphs"] = paragraphs[:30]
        result["images"] = images[:30]

    return result


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/api/health", methods=["GET", "OPTIONS"])
def health():
    """Health check endpoint — returns diagnostic info per MCP spec §8."""
    if request.method == "OPTIONS":
        return "", 204

    store = get_sqlite_store()
    stats = store.get_stats()
    sqlite_ok = stats.get("sqlite_ok", False)

    return jsonify({
        "status": "ok" if sqlite_ok else "degraded",
        "storage": "sqlite",
        "doc_count": stats.get("total_docs", 0),
        "code_blocks": stats.get("total_code_blocks", 0),
        "crawlers": {
            "smart": SMART_CRAWLER_AVAILABLE,
            "selenium": SELENIUM_AVAILABLE,
            "ultrafast": ULTRAFAST_AVAILABLE,
        },
        "import_errors": list(_import_errors.keys()),
        "environment": {
            "sqlite_path": stats.get("db_path", ""),
        },
    }), 200 if sqlite_ok else 503


@app.route("/api/scrape", methods=["POST", "OPTIONS"])
def scrape():
    """
    POST /api/scrape
    {
        "urls": ["https://example.com"],
        "mode": "smart" | "pipeline" | "selenium",
        "max_depth": 1,
        "output_format": "json"
    }
    Modes:
      smart    → SmartCrawler (intelligent priority queue, early exit at 5 good docs, max 30 pages)
      pipeline → UltraFastCrawler (threaded concurrent crawling, max 50 pages)
      selenium → SeleniumCrawler (full JS rendering)
    
    All raw pages are FILTERED through ContentFilter before storage:
      - Rejects nav/index pages (8+ links per paragraph)
      - Rejects marketing pages (50%+ CTAs)
      - Strips boilerplate and low-quality sections
      - Never stores raw links/images, only prose content
    """
    if request.method == "OPTIONS":
        return "", 204

    from mcp import SmartCrawler, SeleniumCrawler, UltraFastCrawler

    try:
        data = request.get_json()
        if not data or "urls" not in data:
            return jsonify({"error": "urls is required", "status": "failed"}), 400

        urls = data.get("urls", [])
        mode = (data.get("mode", "smart") or "smart").strip().lower()
        max_depth = int(data.get("max_depth", 1))
        output_format = data.get("output_format", "json")

        if not isinstance(urls, list) or len(urls) == 0:
            return jsonify({"error": "urls must be a non-empty list", "status": "failed"}), 400

        store = get_sqlite_store()
        all_results = []
        total_pages_scraped = 0

        for start_url in urls:
            try:
                if not start_url.startswith(("http://", "https://")):
                    all_results.append({
                        "url": start_url,
                        "error": "Invalid URL format - must start with http:// or https://",
                        "status": "failed",
                    })
                    continue

                # ========== CRAWL BASED ON MODE ==========
                raw_pages = []
                
                if mode == "selenium":
                    # Full JS rendering via Selenium
                    if SeleniumCrawler is None:
                        return jsonify({"error": "SeleniumCrawler not available", "status": "failed"}), 422
                    crawler = SeleniumCrawler(start_url=start_url, max_depth=max_depth)
                    raw = crawler.crawl()
                    # Now returns dicts with structured data {url, title, content, paragraphs, headings, etc}
                    if isinstance(raw, dict):
                        raw_pages = [v if isinstance(v, dict) else {"url": k, "content": v} for k, v in raw.items()]
                    
                elif mode == "pipeline":
                    # Multi-threaded concurrent crawling, bounded to 50 pages
                    if UltraFastCrawler is None:
                        return jsonify({"error": "UltraFastCrawler not available", "status": "failed"}), 422
                    crawler = UltraFastCrawler(start_url=start_url, max_depth=max_depth, max_workers=8)
                    # Add max_pages limit to prevent unbounded crawling
                    crawler.max_pages = 50
                    raw = crawler.crawl()
                    # Now returns dicts with structured data {url, title, content, paragraphs, headings, etc}
                    if isinstance(raw, dict):
                        raw_pages = [v if isinstance(v, dict) else {"url": k, "content": v} for k, v in raw.items()]
                    
                else:
                    # Default: Smart priority-queue crawling (GHOST_PROTOCOL)
                    if SmartCrawler is None:
                        return jsonify({"error": "SmartCrawler not available", "status": "failed"}), 422
                    crawler = SmartCrawler(
                        timeout=15,
                        delay_between_requests=0.3,
                        min_good_docs=5,
                        cross_domain_budget=3,
                    )
                    # SmartCrawler.crawl() returns list[ScrapedDocument] with ContentFilter fields
                    raw = crawler.crawl(seed_url=start_url, max_pages=30, max_depth=max_depth)
                    # Convert ScrapedDocument objects to dicts
                    if isinstance(raw, list):
                        raw_pages = [
                            {
                                "url": doc.url,
                                "title": doc.title,
                                "content": doc.content,
                                "meta_description": doc.meta_description,
                                "paragraphs": doc.paragraphs,
                                "headings": doc.headings,
                                "code_blocks": doc.code_blocks,
                                "links_count": doc.links_count,
                            }
                            for doc in raw
                        ]
                
                total_pages_scraped += len(raw_pages)
                
                if not raw_pages:
                    all_results.append({
                        "url": start_url,
                        "error": "No content scraped",
                        "status": "failed"
                    })
                    continue

                # Store ALL pages without filtering
                indexed_count = 0
                for parsed in raw_pages:
                    try:
                        doc_id = store.save_doc(
                            url=parsed.get("url", ""),
                            content=parsed.get("content", ""),
                            metadata={"title": parsed.get("title", "")},
                        )
                        if doc_id:
                            indexed_count += 1
                            all_results.append({
                                "url": parsed.get("url", ""),
                                "title": parsed.get("title", ""),
                                "status": "indexed",
                            })
                    except Exception as store_err:
                        app.logger.warning(f"Failed to store {parsed.get('url')}: {store_err}")

                if indexed_count == 0:
                    all_results.append({
                        "url": start_url,
                        "error": f"Failed to index {len(raw_pages)} pages",
                        "status": "failed"
                    })

            except Exception as e:
                app.logger.error(f"Error crawling {start_url}: {e}")
                all_results.append({"url": start_url, "error": str(e), "status": "error"})

        return jsonify({
            "status": "success",
            "mode": mode,
            "urls_processed": len(urls),
            "pages_scraped": total_pages_scraped,
            "pages_indexed": len([r for r in all_results if r.get("status") == "indexed"]),
            "output_format": output_format,
            "data": all_results,
        }), 200

    except Exception as e:
        import traceback
        app.logger.error(f"Fatal scrape error: {e}\n{traceback.format_exc()}")
        return jsonify({
            "error": str(e),
            "status": "failed",
            "trace": traceback.format_exc() if os.getenv("FLASK_ENV") != "production" else None,
        }), 500


@app.route("/api/scrape/validate-urls", methods=["POST"])
def validate_urls():
    try:
        data = request.get_json()
        urls = data.get("urls", [])
        results = [{"url": u, "valid": u.startswith(("http://", "https://"))} for u in urls]
        return jsonify({"results": results}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/debug-scrape", methods=["POST"])
def debug_scrape():
    """Debug endpoint to trace a crawl step by step."""
    import traceback as tb
    import requests as req

    data = request.get_json()
    url = data.get("url", "https://example.com")
    trace = []

    try:
        r = req.get(url, timeout=8, verify=False, headers={"User-Agent": "Mozilla/5.0 (compatible; Scrapee/1.0)"})
        trace.append({"step": "fetch", "status_code": r.status_code, "html_length": len(r.text)})
        soup = BeautifulSoup(r.text, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        links = [tag["href"] for tag in soup.find_all("a", href=True)]
        trace.append({"step": "parse", "title": title, "links_count": len(links), "sample_links": links[:5]})
    except Exception as e:
        trace.append({"step": "error", "error": str(e), "traceback": tb.format_exc()})

    return jsonify({"trace": trace}), 200


@app.route("/mcp", methods=["GET", "POST"])
def mcp():
    """Delegate all MCP JSON-RPC requests to the shared MCPServer instance."""
    if request.method != "POST":
        return jsonify({"error": "MCP endpoint expects POST JSON-RPC requests"}), 405

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}), 400

    response = mcp_server.handle_request(data)
    if response is None:
        response = {"jsonrpc": "2.0", "result": None}
    return jsonify(response), 200


# ─── SERVERLESS MCP: BACKGROUND SCRAPE ENDPOINT (NON-BLOCKING) ───────────────
@app.route("/api/internal/background_scrape", methods=["POST"])
def background_scrape():
    """
    Internal endpoint for non-blocking background scraping.
    
    Called via fire-and-forget HTTP POST from MCP tools.
    Completes within 8 seconds (Vercel-safe with buffer).
    
    VERCEL-SAFE:
    - Limits to 2 URLs (prevents long execution)
    - Hard 8-second timeout guard
    - Doesn't block user-facing requests
    - Uses direct HTTP (not threading)
    """
    data = request.json or {}
    query = data.get("query", "").strip()
    urls = data.get("urls", [])
    
    if not urls:
        return jsonify({"status": "skipped", "reason": "no urls"}), 200
    
    # HARD LIMIT: 8-second timeout guard
    start_time = time.time()
    max_duration = 8  # Vercel safety margin
    
    # Process URLs (top 2 ONLY, not 5)
    scraped_count = 0
    for url in urls[:2]:  # CRITICAL: Limited to 2 URLs
        # Check timeout before each URL
        elapsed = time.time() - start_time
        if elapsed > max_duration:
            print(f"[Background] Timeout: stopping after {elapsed:.1f}s")
            break
        
        try:
            # Quick scrape: shallow depth, small batch
            result = mcp_server._tool_scrape_url({
                "url": url,
                "mode": "smart",
                "max_depth": 1
            })
            
            # Record success in domain learner
            if hasattr(mcp_server, 'domain_learner') and not result.get("error"):
                mcp_server.domain_learner.record_success(query, url)
                scraped_count += 1
        except Exception as e:
            print(f"[Background] Failed to scrape {url}: {e}")
            continue
    
    return jsonify({
        "status": "done",
        "query": query,
        "urls_processed": len(urls),
        "scraped_count": scraped_count
    }), 200


# ─── CACHE STATS ENDPOINT (DEBUGGING) ──────────────────────────────────────
@app.route("/api/stats", methods=["GET"])
def stats():
    """Get system statistics for debugging."""
    cache_stats = (
        mcp_server.cache.stats()
        if hasattr(mcp_server.cache, 'stats')
        else {"error": "cache stats not available"}
    )
    
    db_stats = mcp_server.store.get_stats()
    
    domain_learner_stats = (
        {"learned_domains": len(mcp_server.domain_learner.learned_domains)}
        if hasattr(mcp_server, 'domain_learner')
        else {}
    )
    
    return jsonify({
        "cache": cache_stats,
        "database": db_stats,
        "domain_learning": domain_learner_stats,
        "timestamp": time.time()
    }), 200


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "False") == "True"
    port = int(os.getenv("FLASK_PORT", 8080))
    app.run(debug=debug, host="0.0.0.0", port=port)
