from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import time
import requests
from urllib.parse import urlparse
from dotenv import load_dotenv

# Must be set before torch / sentence-transformers import (via mcp_engine).
# On macOS's Xcode-bundled Python, PyTorch ships its own libomp while
# numpy/scipy/sklearn load another — two OpenMP runtimes in one process, which
# segfaults (exit 139) and leaks semaphores. KMP_DUPLICATE_LIB_OK tolerates it;
# pinning every math lib to one thread avoids the worker-pool fork hazard.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("KMP_INIT_AT_FORK", "FALSE")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from mcp_engine import (
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

# ─── SCRAPE LOCK (Prevent duplicate concurrent scrapes) ──────────────────────
# Global set tracking queries currently being scraped, shared with the MCP
# engine's trigger_background_scrape.
# Prevents: User asks → scrape triggers → User asks again → DUPLICATE SCRAPE
from serverless_mcp_upgrade import SCRAPE_IN_PROGRESS

# ─── HTML parsing helper (used by /api/scrape) ────────────────────────────────
from urllib.parse import urljoin
from bs4 import BeautifulSoup

# Non-repo GitHub paths that should still be crawled as ordinary pages.
_GITHUB_NON_REPO = {
    "", "features", "pricing", "about", "topics", "collections", "trending",
    "marketplace", "sponsors", "settings", "notifications", "explore",
    "orgs", "users", "search", "login", "join", "new",
}


def _is_github_repo_url(url: str) -> bool:
    """True for a github.com/<owner>/<repo> page (repo root or subpage),
    excluding org pages, gists, raw files and non-repo sections."""
    try:
        p = urlparse(url)
        if p.netloc.lower() not in ("github.com", "www.github.com"):
            return False
        parts = [seg for seg in p.path.split("/") if seg]
        if len(parts) < 2:
            return False
        if parts[0].lower() in _GITHUB_NON_REPO:
            return False
        return True
    except Exception:
        return False


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

    from mcp_engine import SmartCrawler, SeleniumCrawler, UltraFastCrawler

    try:
        data = request.get_json()
        if not data or "urls" not in data:
            return jsonify({"error": "urls is required", "status": "failed"}), 400

        urls = data.get("urls", [])
        mode = (data.get("mode", "smart") or "smart").strip().lower()
        max_depth = int(data.get("max_depth", 2))
        # How many pages to pull from a single seed. SmartCrawler still applies
        # its own env-configurable ceiling on top of this.
        try:
            max_pages = max(1, min(int(data.get("max_pages", 40)), 250))
        except (TypeError, ValueError):
            max_pages = 40
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

                # ========== GITHUB REPO → dedicated understanding engine ==========
                # A bare repo landing page (github.com/owner/repo) has almost no
                # crawlable prose; route it through the repo engine, which reads
                # the file tree + key files and indexes a synthesized overview.
                if _is_github_repo_url(start_url) and getattr(mcp_server, "github_engine", None):
                    repo_res = mcp_server._tool_understand_repo({"repo_url": start_url})
                    if repo_res.get("status") == "success":
                        total_pages_scraped += 1
                        all_results.append({
                            "url": start_url,
                            "title": repo_res.get("repo", start_url),
                            "status": "indexed",
                            "kind": "github_repo",
                        })
                        continue
                    # Fall through to normal crawl on engine error (e.g. rate limit)
                    app.logger.warning(f"github engine fallback for {start_url}: {repo_res.get('error')}")

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
                    crawler.max_pages = max_pages
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
                        min_good_docs=max_pages,   # don't early-exit before max_pages
                        cross_domain_budget=3,
                    )
                    # SmartCrawler.crawl() returns list[ScrapedDocument] with ContentFilter fields
                    raw = crawler.crawl(seed_url=start_url, max_pages=max_pages, max_depth=max_depth)
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

                indexed_count = 0
                for parsed in raw_pages:
                    content = parsed.get("content", "") or ""
                    code_blocks = parsed.get("code_blocks") or []
                    page = {
                        "url": parsed.get("url", ""),
                        "title": parsed.get("title", ""),
                        "words": len(content.split()),
                        "code_blocks": len(code_blocks),
                        "excerpt": " ".join(content.split())[:240],
                    }
                    try:
                        saved = store.save_doc(
                            url=page["url"],
                            content=content,
                            metadata={"title": page["title"]},
                            code_blocks=code_blocks,
                        )
                    except Exception as store_err:
                        app.logger.warning(f"Failed to store {page['url']}: {store_err}")
                        saved = False
                    if saved:
                        indexed_count += 1
                    # save_doc skips thin pages and exact duplicates of a stored page.
                    page["status"] = "indexed" if saved else "skipped"
                    all_results.append(page)

                if indexed_count == 0:
                    all_results.append({
                        "url": start_url,
                        "error": f"Failed to index {len(raw_pages)} pages",
                        "status": "failed"
                    })

            except Exception as e:
                app.logger.error(f"Error crawling {start_url}: {e}")
                all_results.append({"url": start_url, "error": str(e), "status": "error"})

        # Cached get_context answers predate these pages.
        mcp_server.cache.clear()

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


@app.route("/api/mcp/feedback", methods=["POST", "OPTIONS"])
def mcp_feedback():
    """Accept implicit feedback from the frontend about which sources helped.

    Body: { "query": "...", "sources": ["https://..."], "success": true }
    """
    if request.method == "OPTIONS":
        return "", 204

    try:
        data = request.get_json() or {}
        sources = data.get("sources", []) or []
        success = bool(data.get("success", True))
        query = data.get("query", "") or ""

        store = get_sqlite_store()
        # Non-blocking: record feedback and return
        try:
            store.record_source_feedback(query, sources, success)
        except Exception as e:
            app.logger.warning(f"Feedback recording failed: {e}")

        return jsonify({"status": "ok"}), 200
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


# ─── INDEX MANAGEMENT (web UI + CLI) ─────────────────────────────────────────
@app.route("/api/sources", methods=["GET", "OPTIONS"])
def list_sources():
    """Every indexed domain with its page and code-block counts."""
    if request.method == "OPTIONS":
        return "", 204
    store = get_sqlite_store()
    stats = store.get_stats()
    return jsonify({
        "sources": store.list_sources(),
        "total_docs": stats.get("total_docs", 0),
        "total_code_blocks": stats.get("total_code_blocks", 0),
    }), 200


@app.route("/api/sources/<path:domain>", methods=["GET", "DELETE", "OPTIONS"])
def source_detail(domain):
    """GET the pages indexed for a domain; DELETE removes them all."""
    if request.method == "OPTIONS":
        return "", 204
    store = get_sqlite_store()
    if request.method == "DELETE":
        removed = store.delete_domain_documents(domain)
        mcp_server.cache.clear()
        return jsonify({"status": "ok", "domain": domain, "removed": removed}), 200
    return jsonify({"domain": domain, "docs": store.list_source_docs(domain)}), 200


@app.route("/api/context", methods=["POST", "OPTIONS"])
def context():
    """Run get_context exactly as an MCP client would, for previewing answers.

    Body: { "query": "..." }
    """
    if request.method == "OPTIONS":
        return "", 204
    data = request.get_json(silent=True) or {}
    query = str(data.get("query", "")).strip()
    if not query:
        return jsonify({"status": "error", "error": "query is required"}), 400
    return jsonify(mcp_server._tool_get_context({"query": query})), 200


@app.route("/api/reset", methods=["POST", "OPTIONS"])
def reset_index():
    """Empty the whole index. Body must be { "confirm": true }."""
    if request.method == "OPTIONS":
        return "", 204
    data = request.get_json(silent=True) or {}
    if data.get("confirm") is not True:
        return jsonify({"status": "error", "error": 'send {"confirm": true} to empty the index'}), 400
    removed = get_sqlite_store().delete_all_documents()
    mcp_server.cache.clear()
    return jsonify({"status": "ok", "removed": removed}), 200


# ─── SERVERLESS MCP: BACKGROUND SCRAPE ENDPOINT (NON-BLOCKING) ───────────────
@app.route("/api/internal/background_scrape", methods=["POST"])
def background_scrape():
    """
    VERCEL-OPTIMIZED: Process ONE URL per invocation, chain remaining.
    
    CRITICAL: This endpoint is ISOLATED:
    - Only calls _tool_scrape_url (NO MCP logic)
    - Never calls _tool_answer or search (prevents loops)
    - Clears SCRAPE_IN_PROGRESS lock when done
    
    Called via fire-and-forget HTTP POST from MCP tools.
    
    PATTERN:
    1. Process ONLY first URL in this invocation
    2. If more URLs remain → POST next invocation immediately
    3. Each invocation runs independently (Vercel-safe)
    4. Total time: ~2-3s per URL (well under 10s limit)
    
    PRODUCTION FEATURES:
    - One URL per invocation (Vercel safety)
    - Recursive chaining (auto-triggers next batch)
    - Hard 8-second timeout guard
    - Clears scrape lock (prevents duplicates)
    """
    data = request.json or {}
    query = data.get("query", "").strip()
    urls = data.get("urls", [])
    remaining = data.get("remaining", [])
    
    # Combine URLs + remaining
    all_urls = (urls or []) + (remaining or [])
    
    if not query or not all_urls:
        return jsonify({"status": "skipped", "reason": "missing query or urls"}), 200
    
    # SINGLE URL PROCESSING (one per invocation)
    url_to_process = all_urls[0]
    remaining_urls = all_urls[1:]
    
    start_time = time.time()
    max_duration = 8  # Hard timeout
    
    try:
        print(f"[Background] Processing URL 1/{len(all_urls)}: {url_to_process}")
        
        # ─ ISOLATED: ONLY scrape, NO MCP logic ─
        try:
            result = mcp_server._tool_scrape_url({
                "url": url_to_process,
                "mode": "smart",
                "max_depth": 1  # Shallow crawl
            })
            
            # Record success in domain learner (minimal, no MCP calls)
            if hasattr(mcp_server, 'domain_learner') and not result.get("error"):
                mcp_server.domain_learner.record_success(query, url_to_process)
                print(f"[Background] ✅ Scraped: {url_to_process}")
            else:
                print(f"[Background] ⚠️  Scrape returned error: {url_to_process}")
                
        except Exception as e:
            print(f"[Background] ❌ Failed to scrape {url_to_process}: {e}")
        
        # ─ CHAIN: Trigger next URL (if exists) ─
        if remaining_urls:
            elapsed = time.time() - start_time
            if elapsed < max_duration - 1:  # Leave 1s buffer
                try:
                    base_url = os.getenv("BASE_URL")
                    next_payload = {
                        "query": query,
                        "urls": remaining_urls
                    }
                    
                    # Fire-and-forget with minimal timeout
                    requests.post(
                        f"{base_url}/api/internal/background_scrape",
                        json=next_payload,
                        timeout=0.001  # Ultra-minimal (don't wait)
                    )
                    print(f"[Background] 🔗 Chained next batch ({len(remaining_urls)} URLs remaining)")
                except Exception as e:
                    print(f"[Background] ⚠️  Failed to chain next URLs: {e}")
                    # Clear lock on chain failure so retry can happen
                    SCRAPE_IN_PROGRESS.discard(query)
        else:
            # All URLs processed - mark COMPLETED and clear lock
            try:
                mcp_server.store.upsert_scrape_job(query, "completed")
                print(f"[Background] ✅ Job COMPLETED: {query}")
            except Exception as e:
                print(f"[Background] ⚠️  Failed to mark job COMPLETED: {e}")
            
            # IMPORTANT: Clear lock so future queries can scrape again
            SCRAPE_IN_PROGRESS.discard(query)
        
        return jsonify({
            "status": "done",
            "query": query,
            "url_processed": url_to_process,
            "remaining_count": len(remaining_urls),
            "elapsed_ms": int((time.time() - start_time) * 1000)
        }), 200
        
    except Exception as e:
        print(f"[Background] ❌ Error in background_scrape: {e}")
        try:
            mcp_server.store.upsert_scrape_job(query, "failed")
        except:
            pass
        return jsonify({"status": "error", "error": str(e)}), 500


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
    # The auto-reloader forks the process while torch/SBERT worker pools are
    # live, which leaks semaphores and crashes the child (exit 245). Keep debug
    # error pages but disable the reloader unless explicitly asked for.
    use_reloader = os.getenv("FLASK_USE_RELOADER", "False") == "True"
    app.run(debug=debug, host="0.0.0.0", port=port, use_reloader=use_reloader)
