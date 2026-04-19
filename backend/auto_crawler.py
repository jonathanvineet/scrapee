"""
Background Auto-Crawler — persistent knowledge graph builder.

Runs as a daemon thread inside the MCP server process.
Continuously discovers new documentation to index based on:
  - Recently queried topics that had thin results
  - Sitemaps from already-indexed domains
  - Periodic refresh of high-value doc sites

The crawler is careful to NOT overload servers:
  - Minimum 2s delay between requests
  - Maximum 50 new pages per crawl cycle
  - 30 minute sleep between full cycles
  - Respects per-domain crawl budgets
"""
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse


# Crawl settings
CRAWL_DELAY_SECONDS = 2.0         # between individual page fetches
CYCLE_SLEEP_MINUTES = 30          # between full crawl cycles
MAX_PAGES_PER_CYCLE = 50          # cap total new pages per run
MAX_PAGES_PER_DOMAIN = 10         # cap per domain per cycle
REFRESH_AFTER_DAYS = 3            # re-scrape pages older than this

# Seed documentation sites that always benefit from being up-to-date
EVERGREEN_SEEDS = [
    "https://docs.python.org/3/",
    "https://react.dev/learn",
    "https://fastapi.tiangolo.com/",
    "https://nextjs.org/docs",
    "https://docs.hedera.com",
    "https://redis.io/docs/",
    "https://docs.docker.com",
]


class AutoCrawler:
    """Background documentation crawler and knowledge graph builder.

    Lifecycle:
        crawler = AutoCrawler(store, scraper)
        crawler.start()   # spawns daemon thread, returns immediately
        crawler.stop()    # signals thread to exit cleanly
    """

    def __init__(self, store, scraper):
        self.store = store
        self.scraper = scraper

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Miss log: tracks queries that returned < 2 results
        # AutoCrawler will try to find docs for these
        self._query_misses: List[str] = []
        self._miss_lock = threading.Lock()

        # Per-domain page counts for this cycle
        self._domain_counts: Dict[str, int] = {}

        # Visited URLs this cycle (avoid re-scraping in same cycle)
        self._visited: Set[str] = set()

        print("[CRAWL] AutoCrawler initialised")

    # ──────────────────────────────────────────
    # Public control API
    # ──────────────────────────────────────────

    def start(self):
        """Start the background crawler daemon."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="AutoCrawler"
        )
        self._thread.start()
        print("[CRAWL] Background crawler started")

    def stop(self):
        """Signal the crawler to stop after the current operation."""
        self._stop_event.set()
        print("[CRAWL] Stop signal sent")

    def record_miss(self, query: str):
        """Call when a query returns empty results — crawler will try to fill the gap."""
        with self._miss_lock:
            if query not in self._query_misses:
                self._query_misses.append(query)

    # ──────────────────────────────────────────
    # Main loop
    # ──────────────────────────────────────────

    def _run_loop(self):
        """Daemon thread main loop."""
        # Initial delay so the server can fully start up first
        time.sleep(15)

        while not self._stop_event.is_set():
            try:
                self._run_cycle()
            except Exception as e:
                print(f"[CRAWL] Cycle error: {e}")

            # Sleep between cycles, but check stop every 30s
            sleep_end = time.monotonic() + CYCLE_SLEEP_MINUTES * 60
            while time.monotonic() < sleep_end and not self._stop_event.is_set():
                time.sleep(30)

    def _run_cycle(self):
        """Execute one full crawl cycle."""
        self._domain_counts = {}
        self._visited = set()
        pages_scraped = 0

        print(f"[CRAWL] Starting cycle at {datetime.utcnow().isoformat()}")

        # ── Phase 1: Answer pending query misses ──
        with self._miss_lock:
            misses = list(self._query_misses[:10])  # process up to 10 per cycle
            self._query_misses = self._query_misses[10:]

        for query in misses:
            if self._stop_event.is_set():
                break
            if pages_scraped >= MAX_PAGES_PER_CYCLE:
                break

            urls = self._sources_for_query(query)
            for url in urls:
                n = self._crawl_url(url, depth=1)
                pages_scraped += n
                if n > 0:
                    print(f"[CRAWL] Miss resolved: {query!r} via {url}")
                    break

        # ── Phase 2: Refresh stale docs ──
        stale = self._find_stale_docs(limit=20)
        for url in stale:
            if self._stop_event.is_set():
                break
            if pages_scraped >= MAX_PAGES_PER_CYCLE:
                break
            pages_scraped += self._crawl_url(url, depth=0)

        # ── Phase 3: Discover new pages via sitemaps ──
        indexed_domains = self._get_indexed_domains()
        for domain in indexed_domains[:5]:
            if self._stop_event.is_set():
                break
            if pages_scraped >= MAX_PAGES_PER_CYCLE:
                break
            sitemap_urls = self._discover_from_sitemap(domain)
            for url in sitemap_urls[:MAX_PAGES_PER_DOMAIN]:
                if pages_scraped >= MAX_PAGES_PER_CYCLE:
                    break
                pages_scraped += self._crawl_url(url, depth=0)

        # ── Phase 4: Evergreen seed refresh (if budget remains) ──
        if pages_scraped < MAX_PAGES_PER_CYCLE // 2:
            for seed in EVERGREEN_SEEDS:
                if self._stop_event.is_set():
                    break
                domain = urlparse(seed).netloc
                if not self._is_indexed(seed) or self._is_stale(seed):
                    pages_scraped += self._crawl_url(seed, depth=1)

        print(f"[CRAWL] Cycle complete: {pages_scraped} pages processed")

    # ──────────────────────────────────────────
    # Crawl helpers
    # ──────────────────────────────────────────

    def _crawl_url(self, url: str, depth: int = 0) -> int:
        """Scrape a single URL and store it. Returns 1 on success, 0 on skip/fail."""
        if url in self._visited:
            return 0

        domain = urlparse(url).netloc
        if self._domain_counts.get(domain, 0) >= MAX_PAGES_PER_DOMAIN:
            return 0

        self._visited.add(url)
        time.sleep(CRAWL_DELAY_SECONDS)

        try:
            result = self.scraper.scrape(url)
            if result.get("error"):
                return 0

            content = result.get("content", "")
            if not content or len(content) < 300:
                return 0

            self.store.save_doc(
                url,
                content,
                metadata={"title": result.get("title", ""), "domain": domain},
                code_blocks=result.get("code_blocks", []),
                topics=result.get("topics", []),
            )
            self._domain_counts[domain] = self._domain_counts.get(domain, 0) + 1
            print(f"[CRAWL] Indexed: {url}")
            return 1

        except Exception as e:
            print(f"[CRAWL] Failed {url}: {e}")
            return 0

    def _discover_from_sitemap(self, domain: str) -> List[str]:
        """Fetch sitemap.xml and return unvisited URLs from the same domain."""
        urls = []
        for sitemap_path in ["/sitemap.xml", "/sitemap_index.xml"]:
            sitemap_url = f"https://{domain}{sitemap_path}"
            try:
                import requests
                r = requests.get(sitemap_url, timeout=8,
                                 headers={"User-Agent": "Scrapee-MCP/1.0 (documentation indexer)"})
                if r.status_code == 200:
                    import re
                    found = re.findall(r"<loc>(https?://[^<]+)</loc>", r.text)
                    # Filter to same domain, not already in index
                    for u in found:
                        if domain in u and not self._is_indexed(u):
                            urls.append(u)
                    if urls:
                        break
            except Exception:
                continue
        return urls[:MAX_PAGES_PER_DOMAIN]

    # ──────────────────────────────────────────
    # Store helpers (thin wrappers)
    # ──────────────────────────────────────────

    def _find_stale_docs(self, limit: int = 20) -> List[str]:
        """Return URLs of documents not refreshed in the last N days."""
        try:
            cutoff = (datetime.utcnow() - timedelta(days=REFRESH_AFTER_DAYS)).isoformat()
            cursor = self.store.conn.cursor()
            rows = cursor.execute(
                "SELECT url FROM docs WHERE scraped_at < ? ORDER BY scraped_at ASC LIMIT ?",
                (cutoff, limit),
            ).fetchall()
            return [r[0] for r in rows]
        except Exception:
            return []

    def _get_indexed_domains(self) -> List[str]:
        """Return domains already in the index, ordered by doc count."""
        try:
            cursor = self.store.conn.cursor()
            rows = cursor.execute(
                "SELECT domain, COUNT(*) as n FROM docs WHERE domain IS NOT NULL "
                "GROUP BY domain ORDER BY n DESC LIMIT 20"
            ).fetchall()
            return [r[0] for r in rows if r[0]]
        except Exception:
            return []

    def _is_indexed(self, url: str) -> bool:
        try:
            cursor = self.store.conn.cursor()
            row = cursor.execute("SELECT 1 FROM docs WHERE url = ? LIMIT 1", (url,)).fetchone()
            return row is not None
        except Exception:
            return False

    def _is_stale(self, url: str) -> bool:
        try:
            cutoff = (datetime.utcnow() - timedelta(days=REFRESH_AFTER_DAYS)).isoformat()
            cursor = self.store.conn.cursor()
            row = cursor.execute(
                "SELECT 1 FROM docs WHERE url = ? AND scraped_at < ? LIMIT 1",
                (url, cutoff),
            ).fetchone()
            return row is not None
        except Exception:
            return False

    def _sources_for_query(self, query: str) -> List[str]:
        """Map a query to potential documentation URLs."""
        # Mirror the mcp.py keyword map to avoid a circular import
        keyword_map = {
            "react": "https://react.dev/learn",
            "nextjs": "https://nextjs.org/docs",
            "hedera": "https://docs.hedera.com",
            "python": "https://docs.python.org/3/",
            "fastapi": "https://fastapi.tiangolo.com/",
            "flask": "https://flask.palletsprojects.com/",
            "docker": "https://docs.docker.com",
            "redis": "https://redis.io/docs/",
            "typescript": "https://www.typescriptlang.org/docs/",
            "node": "https://nodejs.org/en/docs",
            "postgres": "https://www.postgresql.org/docs/",
            "mongodb": "https://www.mongodb.com/docs/",
            "rust": "https://doc.rust-lang.org",
            "django": "https://docs.djangoproject.com/",
            "vue": "https://vuejs.org/guide/",
        }
        q = query.lower()
        for keyword, url in keyword_map.items():
            if keyword in q:
                return [url]
        return []
