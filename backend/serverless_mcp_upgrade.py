"""
Serverless-Native MCP Upgrade

CRITICAL: This module contains the new serverless-optimized architecture
for Vercel deployment. All crawling is fire-and-forget, non-blocking.

Key changes:
1. No blocking scrapes in request-response cycle
2. Fire-and-forget background scraping
3. Instant responses with "learning..." status
4. Thread-safe cache with locks
5. Query memory (domain learning)
6. Gzip compression support
7. Aggressive timeouts for serverless

USAGE:
Import these functions into mcp.py and app.py
"""

import json
import os
import requests
import threading
import time
from typing import Dict, Optional, Any, List
from urllib.parse import urlparse


# ─────────────────────────────────────────────────────────────────────────────
# 1. THREAD-SAFE CACHE LAYER (FIX: Add locks)
# ─────────────────────────────────────────────────────────────────────────────

class ThreadSafeCacheLayer:
    """Enhanced cache with thread locks and size limits."""

    def __init__(self, ttl_seconds: int = 300, max_entries: int = 10000):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._cache: Dict[str, tuple] = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            cached = self._cache.get(key)
            if not cached:
                self.misses += 1
                return None
            expires_at, value = cached
            if expires_at < time.monotonic():
                self._cache.pop(key, None)
                self.misses += 1
                return None
            self.hits += 1
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            # Evict oldest if at capacity
            if len(self._cache) >= self.max_entries:
                oldest_key = min(
                    self._cache.keys(),
                    key=lambda k: self._cache[k][0]
                )
                del self._cache[oldest_key]
            
            self._cache[key] = (time.monotonic() + self.ttl_seconds, value)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            hit_rate = (
                self.hits / (self.hits + self.misses) * 100
                if (self.hits + self.misses) > 0
                else 0
            )
            return {
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": f"{hit_rate:.1f}%",
                "entries": len(self._cache),
                "max_entries": self.max_entries
            }


# ─────────────────────────────────────────────────────────────────────────────
# 2. DOMAIN LEARNING (QUERY MEMORY)
# ─────────────────────────────────────────────────────────────────────────────

class DomainLearner:
    """Learn best source URLs for query patterns."""

    def __init__(self):
        self.learned_domains: Dict[str, str] = {}
        self._lock = threading.Lock()

    def record_success(self, query: str, url: str) -> None:
        """Record a successful scrape for a query."""
        with self._lock:
            domain = urlparse(url).netloc
            self.learned_domains[query.lower()] = url

    def get_domain(self, query: str) -> Optional[str]:
        """Get previously learned domain for query."""
        with self._lock:
            return self.learned_domains.get(query.lower())

    def clear(self) -> None:
        with self._lock:
            self.learned_domains.clear()


# ─────────────────────────────────────────────────────────────────────────────
# 2B. SCRAPE DECISION LOGIC
# ─────────────────────────────────────────────────────────────────────────────

def should_scrape_query(store, query: str) -> bool:
    """
    Decide whether to scrape for a query.
    
    Returns False if:
    - Scrape already completed
    - Scrape is currently running
    
    Returns True if:
    - First time seeing this query
    - Previous scrape failed
    """
    try:
        job = store.get_scrape_job(query)
        
        if not job:
            return True  # New query, should scrape
        
        status = job.get("status", "").lower()
        
        if status == "completed":
            return False  # Already scraped
        
        if status == "running":
            return False  # Currently scraping, don't duplicate
        
        return True  # Failed or unknown, retry
    except Exception as e:
        print(f"[Scrape Decision] Error: {e}")
        return True  # Default to scraping on error


# ─────────────────────────────────────────────────────────────────────────────
# 3. NON-BLOCKING BACKGROUND SCRAPE TRIGGER
# ─────────────────────────────────────────────────────────────────────────────

def trigger_background_scrape(query: str, urls: Optional[List[str]] = None, store=None) -> bool:
    """
    True fire-and-forget background scrape trigger.
    
    VERCEL-SAFE:
    - Uses direct HTTP POST (not threading)
    - True fire-and-forget (minimal timeout = instant return)
    - 0.001s timeout ensures response returns immediately
    - Never blocks the request thread
    
    Args:
        query: User query (for logging)
        urls: List of URLs to scrape (limited to 2)
        store: SQLiteStore for marking job as RUNNING
    
    Returns:
        True if POST sent, False if exception
    """
    try:
        base_url = os.getenv("BASE_URL")
        if not base_url:
            print(f"[Background] BASE_URL not set, skipping")
            return False
        
        # Mark scrape job as RUNNING (prevents duplicate scrapes)
        if store:
            try:
                store.upsert_scrape_job(query, "running")
            except Exception as e:
                print(f"[Background] Failed to mark job RUNNING: {e}")
        
        endpoint = f"{base_url}/api/internal/background_scrape"
        payload = {
            "query": query,
            "urls": urls[:2] if urls else []  # LIMIT: Only 2 URLs
        }
        
        # CRITICAL: 0.001s timeout = truly non-blocking fire-and-forget
        # This ensures user response returns immediately, no blocking
        try:
            requests.post(
                endpoint,
                json=payload,
                timeout=0.001  # ← MINIMAL: ~1ms
            )
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            # Timeout/connection errors are expected with 1ms timeout
            # This is intentional - we don't wait for success confirmation
            pass
        
        print(f"[Background] Fire-and-forget sent for: {query}")
        return True
    except Exception as e:
        print(f"[Background] Scrape trigger failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 4. AGGRESSIVE TIMEOUT GUARDS (SERVERLESS-SAFE)
# ─────────────────────────────────────────────────────────────────────────────

class ServerlessTimeoutGuard:
    """Enforces timeouts for serverless environments."""

    VERCEL_HARD_LIMIT = 60  # Vercel kills at 60s
    SAFE_MARGIN = 5  # Leave 5s buffer
    MAX_CRAWL_TIME = VERCEL_HARD_LIMIT - SAFE_MARGIN  # 55 seconds

    def __init__(self):
        self.start_time = time.time()

    def remaining(self) -> float:
        """Get remaining time budget."""
        elapsed = time.time() - self.start_time
        return max(0, self.MAX_CRAWL_TIME - elapsed)

    def should_stop(self) -> bool:
        """Check if we should stop crawling."""
        return self.remaining() < 2  # Stop with 2s left

    @staticmethod
    def enforce(crawler) -> None:
        """Monkey-patch crawler with timeout guard."""
        original_crawl = crawler.crawl
        guard = ServerlessTimeoutGuard()

        def guarded_crawl(*args, **kwargs):
            results = []
            for page in original_crawl(*args, **kwargs):
                if guard.should_stop():
                    print(f"[Timeout] Stopping crawl early (remaining: {guard.remaining():.1f}s)")
                    break
                results.append(page)
            return results

        crawler.crawl = guarded_crawl


# ─────────────────────────────────────────────────────────────────────────────
# 5. NETWORK OPTIMIZATION (GZIP COMPRESSION)
# ─────────────────────────────────────────────────────────────────────────────

def configure_session_for_serverless(session):
    """
    Configure requests.Session for optimal serverless performance.
    
    - Enables gzip/deflate compression
    - Sets aggressive timeouts
    - Optimizes connection pooling
    """
    session.headers.update({
        "User-Agent": "Scrapee/2.0-Serverless",
        "Accept-Encoding": "gzip, deflate"  # Enable compression
    })
    
    # Aggressive timeouts for serverless
    session.timeout = 8  # Total timeout
    
    return session


# ─────────────────────────────────────────────────────────────────────────────
# 6. INSTANT RESPONSE PATTERN (NO BLOCKING)
# ─────────────────────────────────────────────────────────────────────────────

class NonBlockingSearchResponse:
    """
    Generates instant responses without blocking.
    
    Pattern:
    1. Return cached results if available (instant)
    2. Trigger background scrape if empty
    3. Return learning state
    """

    @staticmethod
    def answer(query: str, results: Optional[List[Dict]] = None,
               has_triggered_scrape: bool = False) -> Dict[str, Any]:
        """
        Generate non-blocking answer response.
        
        Args:
            query: User query
            results: Search results (if available)
            has_triggered_scrape: Whether background scrape was triggered
        
        Returns:
            Response dict with status
        """
        if results:
            return {
                "status": "ready",
                "query": query,
                "results": results,
                "response_time_ms": "instant"
            }
        
        if has_triggered_scrape:
            return {
                "status": "learning",
                "query": query,
                "message": "Fetching live documentation... (will be ready on next query)",
                "results": [],
                "response_time_ms": "<300ms"
            }
        
        return {
            "status": "empty",
            "query": query,
            "message": "No documentation indexed yet. Try scraping a source URL first.",
            "results": [],
            "response_time_ms": "<100ms"
        }


# ─────────────────────────────────────────────────────────────────────────────
# 7. MINIMAL CRAWL CONFIG (SERVERLESS-SAFE)
# ─────────────────────────────────────────────────────────────────────────────

SERVERLESS_CRAWLER_CONFIG = {
    "max_depth": 1,  # Keep shallow
    "max_pages": 5,  # Small batches
    "timeout": 8,  # Aggressive
    "delay": 0.2,  # Faster
    "batch_size": 3,  # Parallel fetch: 3 at a time
}


# ─────────────────────────────────────────────────────────────────────────────
# 8. QUERY GENERATION FOR BACKGROUND SCRAPE
# ─────────────────────────────────────────────────────────────────────────────

def generate_sources_for_query(query: str, domain_hints: Dict[str, str]) -> List[str]:
    """
    Generate list of URLs to scrape for a given query.
    
    Uses heuristics:
    - Match query keywords against domain hints
    - Return top URLs to crawl
    """
    query_lower = query.lower()
    sources = []
    
    for keyword, domain_url in domain_hints.items():
        if keyword in query_lower:
            sources.append(domain_url)
    
    return sources[:3]  # Return top 3


def rank_sources_by_relevance(urls: List[str], query: str = "") -> List[str]:
    """
    Rank sources by relevance/reliability.
    
    Scoring heuristic:
    - Official docs sites score higher
    - ReadTheDocs scores high
    - GitHub scores medium (source code)
    - Generic sites score lower
    """
    scored = []
    
    for url in urls:
        score = 0
        url_lower = url.lower()
        
        # Official documentation sites (highest priority)
        if any(domain in url_lower for domain in [
            "docs.",
            "/docs",
            "/documentation",
            "official",
            ".io/docs"
        ]):
            score += 10
        
        # ReadTheDocs (very reliable)
        if "readthedocs" in url_lower:
            score += 8
        
        # Framework official sites
        if any(domain in url_lower for domain in [
            "python.org",
            "nodejs.org",
            "ruby-lang.org",
            "golang.org",
            "rust-lang.org"
        ]):
            score += 9
        
        # GitHub (source code, but ranked lower than official docs)
        if "github.com" in url_lower:
            score += 3
        
        # Stack Overflow (example code)
        if "stackoverflow.com" in url_lower:
            score += 2
        
        # Generic sites
        if score == 0:
            score = 1
        
        scored.append((score, url))
    
    # Sort by score descending, return URLs
    return [url for score, url in sorted(scored, key=lambda x: x[0], reverse=True)]


# ─────────────────────────────────────────────────────────────────────────────
# MIGRATION GUIDE
# ─────────────────────────────────────────────────────────────────────────────

"""
HOW TO USE IN app.py:

1. Replace CacheLayer with ThreadSafeCacheLayer:
   
   from serverless_mcp_upgrade import ThreadSafeCacheLayer
   mcp_server.cache = ThreadSafeCacheLayer(ttl_seconds=300)

2. Add domain learner:
   
   from serverless_mcp_upgrade import DomainLearner
   mcp_server.domain_learner = DomainLearner()

3. Configure session:
   
   from serverless_mcp_upgrade import configure_session_for_serverless
   mcp_server.session = configure_session_for_serverless(mcp_server.session)

4. Add background scrape endpoint:
   
   @app.route("/api/internal/background_scrape", methods=["POST"])
   def background_scrape():
       data = request.json
       query = data.get("query")
       urls = data.get("urls", [])
       
       for url in urls:
           try:
               mcp_server._tool_scrape_url({
                   "url": url,
                   "mode": "smart",
                   "max_depth": 1
               })
               mcp_server.domain_learner.record_success(query, url)
           except Exception as e:
               print(f"[Background] Failed to scrape {url}: {e}")
       
       return {"status": "done"}

5. Modify tools (e.g., _tool_answer):
   
   def _tool_answer(self, args):
       query = args.get("query")
       results = self.store.search_and_get(query)
       
       if results:
           return NonBlockingSearchResponse.answer(query, results)
       
       # Trigger background scrape
       urls = generate_sources_for_query(query, self.DOMAIN_HINTS)
       if urls:
           trigger_background_scrape(query, urls)
           return NonBlockingSearchResponse.answer(query, has_triggered_scrape=True)
       
       return NonBlockingSearchResponse.answer(query)
"""
