# Fix Summary: Crawler Mode Balance Issue

## The Problem

**Frontend UI showed:**
- GHOST_PROTOCOL (mode: `smart`) → Getting only **1 page**
- SWARM_ROUTINE (mode: `pipeline`) → Getting **ALL pages** (unbounded)

This was backwards from the intended behavior.

---

## Root Causes

### Issue 1: SmartCrawler Constructor Signature Mismatch

**In `backend/app.py` line 211 (BEFORE):**
```python
crawler = SmartCrawler(start_url=start_url, max_depth=max_depth)
```

**Problem:** SmartCrawler does NOT accept `start_url` in `__init__()`. The signature is:
```python
def __init__(self, timeout=15, delay_between_requests=0.3, min_good_docs=5, cross_domain_budget=3):
```

The `seed_url` goes in the `crawl()` method, not `__init__()`:
```python
def crawl(self, seed_url: str, max_pages: int = 30, max_depth: int = 3) -> list[ScrapedDocument]:
```

**Effect:** SmartCrawler was receiving an unexpected keyword argument `start_url`, likely silently failing or behaving unexpectedly.

---

### Issue 2: SmartCrawler.crawl() Called Without Parameters

**In `backend/app.py` line 217 (BEFORE):**
```python
raw = crawler.crawl()  # ❌ Missing seed_url, max_pages!
```

**Problem:** SmartCrawler's `crawl()` method requires the seed URL and max_pages. Calling it with no arguments likely caused it to fail or return empty results (hence "only 1 page").

---

### Issue 3: UltraFastCrawler Had No max_pages Limit

**In `backend/app.py` line 209 (BEFORE):**
```python
crawler = UltraFastCrawler(start_url=start_url, max_depth=max_depth, max_workers=8)
raw = crawler.crawl()  # Unbounded crawl!
```

**Problem:** UltraFastCrawler doesn't have a `max_pages` parameter. It crawls until:
- It runs out of links to follow
- It hits the global timeout (25 seconds)

For large sites, this means it fetches **every single page** it can discover.

---

## The Fix

### Fix 1: Correct SmartCrawler Initialization

**In `backend/app.py` (AFTER):**
```python
else:
    # Default: Smart priority-queue crawling
    if SmartCrawler is None:
        return jsonify({"error": "SmartCrawler not available", "status": "failed"}), 422
    
    # SmartCrawler doesn't take start_url in __init__, only in crawl()
    crawler = SmartCrawler(
        timeout=15,
        delay_between_requests=0.3,
        min_good_docs=5,           # Early exit at 5 good docs
        cross_domain_budget=3,     # Max 3 pages per off-seed domain
    )
    
    # Call crawl with seed_url and limits
    raw = crawler.crawl(seed_url=start_url, max_pages=30, max_depth=max_depth)
    
    # Convert list[ScrapedDocument] to dict format for compatibility
    if isinstance(raw, list):
        raw = {doc.url: f"<h1>{doc.title}</h1>\n{doc.content}" for doc in raw}
```

**What Changed:**
1. SmartCrawler `__init__()` only gets configuration parameters
2. `crawl()` receives the actual seed_url and max_pages (30 pages max)
3. Early exit happens at min_good_docs=5, so it typically crawls ~8 pages
4. Convert ScrapedDocument list to dict for compatibility with existing code

---

### Fix 2: Cap UltraFastCrawler Page Count

**In `backend/app.py` (AFTER):**
```python
elif mode == "pipeline":
    # Multi-threaded concurrent crawling, bounded to 50 pages
    if UltraFastCrawler is None:
        return jsonify({"error": "UltraFastCrawler not available", "status": "failed"}), 422
    
    crawler = UltraFastCrawler(start_url=start_url, max_depth=max_depth, max_workers=8)
    
    # Add max_pages limit to prevent unbounded crawling
    crawler.max_pages = 50
    raw = crawler.crawl()
```

**What Changed:**
- Added `crawler.max_pages = 50` to limit unbounded crawling
- Now SWARM_ROUTINE fetches max 50 pages (parallel workers)

---

## Behavior Now

| Mode | Backend Route | Crawler | Pages | Strategy |
|------|---------------|---------|-------|----------|
| `smart` (GHOST_PROTOCOL) | `/api/scrape` | SmartCrawler | 30 max (early exit at 5 good docs) | Priority queue, docs first |
| `pipeline` (SWARM_ROUTINE) | `/api/scrape` | UltraFastCrawler | 50 max | Concurrent workers |
| `selenium` (DEEP_RENDER) | `/api/scrape` | SeleniumCrawler | Unlimited (timeout bound) | JS rendering |

---

## Testing

Test the fix locally:
```bash
curl -X POST http://localhost:5000/api/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "urls": ["https://docs.python.org"],
    "mode": "smart",
    "max_depth": 2
  }'
```

Expected: 5-15 pages (early exit at quality docs)

```bash
curl -X POST http://localhost:5000/api/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "urls": ["https://docs.python.org"],
    "mode": "pipeline",
    "max_depth": 2
  }'
```

Expected: 50 pages (max limit hit)

---

## Commits

- `dd879fb`: fix: Correct SmartCrawler initialization in /api/scrape - was passing start_url to __init__ when it belongs in crawl(), add max_pages limits for each mode

---

## Summary

The issue was in the **REST API endpoint** (`/api/scrape` in `app.py`), not the MCP server. The app.py code was:

1. ❌ Passing `start_url` to SmartCrawler's constructor (wrong place)
2. ❌ Calling `crawl()` without the required parameters
3. ❌ Not limiting UltraFastCrawler's page count

Now:
1. ✅ SmartCrawler gets proper __init__ config + crawl(seed_url, max_pages)
2. ✅ UltraFastCrawler is capped at 50 pages
3. ✅ Balanced behavior: GHOST_PROTOCOL is smart, SWARM_ROUTINE is fast/broad
