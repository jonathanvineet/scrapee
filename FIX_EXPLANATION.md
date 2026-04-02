# Fix Explanation: ContentFilter Receiving Raw HTML

## The Problem

After integrating ContentFilter into the scrape pipeline, ALL crawlers were returning only 1 page, regardless of the site. This was the opposite of the original problem (SWARM_ROUTINE returning 87 pages).

## Root Cause

**The pipeline and Selenium crawlers were returning raw HTML strings**, not structured data dictionaries.

When the crawlers returned data like:

```python
self.data[url] = "<html>...</html>"  # Just raw HTML!
```

The ContentFilter tried to access structured fields that didn't exist:

```python
paragraphs = raw.get("paragraphs") or []      # Returns []
headings = raw.get("headings") or []          # Returns []
links_count = int(raw.get("links_count") or 0)  # Returns 0
```

With **0 paragraphs, 0 headings, and 0 links**, the ContentFilter scoring algorithm heavily penalized pages:
- `n_para = max(len(paragraphs), 1)` = 1 (minimum)
- All paragraph-based bonuses were skipped
- The page scored very low (< MIN_QUALITY_SCORE of 30)
- Result: **Every page was rejected**

Only the SmartCrawler was working because it extracts structured fields (`paragraphs`, `headings`, `links_count`) before returning documents.

## The Solution

### 1. Updated Pipeline Crawler (UltraFastCrawler)

Changed from:
```python
self.data[url] = html  # Raw HTML string
```

To:
```python
# Extract structured data using BeautifulSoup
paragraphs = [p.get_text().strip() for p in soup.find_all("p") if len(p.get_text().strip()) > 20]
headings = [{"level": h.name, "text": h.get_text().strip()} 
            for h in soup.find_all(["h1", "h2", "h3", "h4"])]
links_count = len(soup.find_all("a", href=True))
code_blocks = [{"snippet": c.get_text().strip()[:500], "language": ""} 
               for c in soup.find_all(["code", "pre"])]

self.data[url] = {
    "url": url,
    "title": title,
    "content": html,
    "meta_description": meta_desc,
    "paragraphs": paragraphs,
    "headings": headings,
    "links_count": links_count,
    "code_blocks": code_blocks,
}
```

### 2. Updated Selenium Crawler (SeleniumCrawler)

Applied the same structural data extraction as the pipeline crawler.

### 3. Lowered Quality Threshold

Reduced `MIN_QUALITY_SCORE` from 30 to 20 to allow more valid pages to pass filtering while still rejecting nav/marketing pages.

## Result

Now all three crawlers:
- ✅ Extract actual content features (paragraphs, headings, links)
- ✅ Return structured data dictionaries compatible with ContentFilter
- ✅ Allow ContentFilter to properly score pages based on content quality
- ✅ Pass more legitimate content pages while still rejecting nav/marketing pages

## Testing

Test the fixed application with:

```bash
curl -X POST http://localhost:5000/api/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "urls": ["https://docs.python.org/3/library/asyncio.html"],
    "mode": "pipeline"
  }'
```

Expected: Should return multiple pages (not just 1) with proper quality scores.

## Git Commit

Commit: `9070954`
- Fixed: pipeline_crawler.py
- Fixed: selenium_crawler.py
- Updated: app.py (handle new dict format)
- Tuned: content_filter.py (MIN_QUALITY_SCORE = 20)
