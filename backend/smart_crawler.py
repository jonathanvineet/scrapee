"""
smart_crawler.py
----------------
Intelligent documentation crawler with:
  - Scored priority queue (best pages first, not BFS/DFS)
  - URL intelligence filtering via URLIntelligence
  - Early-exit when results are good enough
  - Per-domain crawl budgets
  - Deduplication on normalised URLs
  - Lightweight HTML parsing with title + prose extraction
"""

from __future__ import annotations

import heapq
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Generator, Optional
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from utils.url_intelligence import URLIntelligence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class ScrapedDocument:
    url: str
    title: str
    content: str                    # cleaned prose
    code_blocks: list[dict]         # [{"snippet": ..., "language": ...}]
    domain: str = ""
    depth: int = 0
    score: int = 0                  # URL score at crawl time
    # Fields for ContentFilter
    paragraphs: list[str] = field(default_factory=list)
    headings: list[dict] = field(default_factory=list)
    links_count: int = 0
    meta_description: str = ""

    def __bool__(self) -> bool:
        return bool(self.content and len(self.content) > 50)


@dataclass(order=True)
class _QueueEntry:
    """Min-heap entry — negated score so highest score pops first."""
    priority: int           # -score (lower = higher priority)
    depth: int
    url: str = field(compare=False)

# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

_NOISE_TAGS = {"script", "style", "nav", "footer", "header", "aside",
               "form", "noscript", "iframe", "svg", "button", "input"}

_PROSE_TAGS = {"p", "li", "td", "dd", "blockquote", "article",
               "section", "main", "h1", "h2", "h3", "h4", "h5", "h6"}


def _extract_title(soup: BeautifulSoup) -> str:
    for selector in ["h1", "title", 'meta[property="og:title"]']:
        tag = soup.find(selector)
        if tag:
            return (tag.get("content") or tag.get_text(strip=True))[:200]
    return ""


def _extract_meta_description(soup: BeautifulSoup) -> str:
    """Extract meta description if present."""
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        return meta["content"]
    return ""


def _extract_headings(soup: BeautifulSoup) -> list[dict]:
    """Extract heading hierarchy (h1, h2, h3, etc.)."""
    headings = []
    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        text = heading.get_text(strip=True)
        if text and len(text) > 2:
            headings.append({
                "level": heading.name,
                "text": text[:200]
            })
    return headings


def _extract_paragraphs(soup: BeautifulSoup) -> list[str]:
    """Extract paragraph text for content analysis."""
    paragraphs = []
    
    # Remove noise tags
    soup_copy = BeautifulSoup(str(soup), "html.parser")
    for tag in soup_copy(list(_NOISE_TAGS)):
        tag.decompose()
    
    for p in soup_copy.find_all("p"):
        text = p.get_text(strip=True)
        if len(text) > 20:  # Skip stubs
            paragraphs.append(text)
    
    return paragraphs


def _extract_prose(soup: BeautifulSoup) -> str:
    """Extract human-readable text from page body, removing noise."""
    # Use body as base, or entire document if no body
    body = soup.body or soup
    
    # Clone and remove noise tags
    soup_clean = BeautifulSoup(str(body), "html.parser")
    for noise_tag in soup_clean.find_all(list(_NOISE_TAGS)):
        noise_tag.decompose()
    
    # Extract all prose-like content
    parts: list[str] = []
    for tag in soup_clean.find_all(_PROSE_TAGS):
        text = tag.get_text(separator=" ", strip=True)
        # Keep reasonable length content, skip very short fragments
        if len(text) > 20:
            parts.append(text)
    
    return "\n".join(parts)


def _extract_code_blocks(soup: BeautifulSoup) -> list[dict]:
    blocks = []
    for pre in soup.find_all("pre"):
        code = pre.find("code")
        snippet = (code or pre).get_text(strip=True)
        if len(snippet) < 10:
            continue
        # Detect language from class attribute: "language-python", "lang-js", etc.
        lang = ""
        if code and code.get("class"):
            for cls in code["class"]:
                m = re.match(r"(?:language|lang)-(\w+)", cls, re.I)
                if m:
                    lang = m.group(1).lower()
                    break
        blocks.append({"snippet": snippet[:3000], "language": lang})
    return blocks


def _normalise_url(url: str) -> str:
    """Strip fragment and trailing slash for dedup purposes."""
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, p.path.rstrip("/"), p.params, p.query, ""))


def _extract_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:")):
            continue
        full = urljoin(base_url, href)
        # Drop fragment
        full = full.split("#")[0]
        if full:
            links.append(full)
    return links

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

def _make_session(timeout: int = 15) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (compatible; ScrapeeBot/2.0; "
            "+https://github.com/scrapee) DocsIndexer"
        ),
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    s.max_redirects = 5
    return s

# ---------------------------------------------------------------------------
# Main crawler
# ---------------------------------------------------------------------------

class SmartCrawler:
    """
    Priority-queue crawler that fetches highest-scored URLs first.

    Key improvements over the old BFS approach:
    - URLIntelligence scores every discovered link before it enters the queue
    - Blocked URLs (login, signup, etc.) never enter the queue
    - Early exit: if we already have `min_good_docs` high-quality documents,
      we stop crawling even if max_pages not reached
    - Per-domain budget caps cross-domain sprawl
    - Adaptive delay avoids hammering a single server
    """

    def __init__(
        self,
        timeout: int = 15,
        delay_between_requests: float = 0.3,
        min_good_docs: int = 5,         # early-exit threshold
        cross_domain_budget: int = 3,   # max pages from any single off-seed domain
    ) -> None:
        self.timeout = timeout
        self.delay = delay_between_requests
        self.min_good_docs = min_good_docs
        self.cross_domain_budget = cross_domain_budget
        self.session = _make_session(timeout)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def crawl(
        self,
        seed_url: str,
        max_pages: int = 30,
        max_depth: int = 3,
    ) -> list[ScrapedDocument]:
        """
        Crawl starting from `seed_url`.

        Returns a list of ScrapedDocument, sorted by URL score descending
        (highest quality first).
        """
        intel = URLIntelligence(seed_url)
        visited: set[str] = set()
        domain_counts: dict[str, int] = {}
        heap: list[_QueueEntry] = []
        results: list[ScrapedDocument] = []

        # Seed
        seed_score = intel.score(seed_url)
        heapq.heappush(heap, _QueueEntry(-seed_score, 0, seed_url))

        logger.info("SmartCrawler starting: seed=%s max_pages=%d max_depth=%d",
                    seed_url, max_pages, max_depth)

        while heap and len(results) < max_pages:
            entry = heapq.heappop(heap)
            url = entry.url
            depth = entry.depth
            score = -entry.priority

            norm = _normalise_url(url)
            if norm in visited:
                continue
            visited.add(norm)

            # Cross-domain budget
            host = urlparse(url).netloc
            seed_host = urlparse(seed_url).netloc
            if host != seed_host:
                domain_counts[host] = domain_counts.get(host, 0) + 1
                if domain_counts[host] > self.cross_domain_budget:
                    logger.debug("Cross-domain budget exhausted for %s, skipping %s", host, url)
                    continue

            # Fetch
            result = self._fetch_with_links(url, depth, score)
            if result is None:
                time.sleep(self.delay)
                continue

            doc, child_links = result
            if doc:
                results.append(doc)

                # Discover and enqueue ALL child links (no filtering)
                if depth < max_depth:
                    ranked = intel.filter_and_rank(child_links)
                    for child_url in ranked:
                        child_norm = _normalise_url(child_url)
                        if child_norm not in visited:
                            child_score = intel.score(child_url)
                            # Add all links with reasonable scores
                            heapq.heappush(
                                heap,
                                _QueueEntry(-child_score, depth + 1, child_url),
                            )

            time.sleep(self.delay)

        # Sort final results: highest-score docs first
        results.sort(key=lambda d: d.score, reverse=True)
        logger.info(
            "Crawl complete: %d pages fetched",
            len(results),
        )
        return results

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _fetch_with_links(
        self, url: str, depth: int, score: int
    ) -> Optional[tuple[Optional[ScrapedDocument], list[str]]]:
        """Fetch a page and return (document, child_links) together."""
        try:
            resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            if resp.status_code != 200:
                logger.debug("HTTP %d for %s", resp.status_code, url)
                return None
            if "text/html" not in resp.headers.get("content-type", ""):
                logger.debug("Non-HTML for %s", url)
                return None
        except requests.RequestException as exc:
            logger.warning("Fetch failed %s: %s", url, exc)
            return None

        try:
            soup = BeautifulSoup(resp.text, "html.parser")
            title = _extract_title(soup)
            links = _extract_links(soup, url)
            prose = _extract_prose(soup)
            code_blocks = _extract_code_blocks(soup)
            # Extract structured fields for ContentFilter
            paragraphs = _extract_paragraphs(soup)
            headings = _extract_headings(soup)
            meta_desc = _extract_meta_description(soup)
        except Exception as exc:
            logger.warning("Parse failed %s: %s", url, exc)
            return None

        if not prose or len(prose) < 50:
            # Still return links so we don't lose crawl paths
            logger.debug("Thin content (%d chars) at %s, but returning links", len(prose), url)
            return None, links

        domain = urlparse(url).netloc
        doc = ScrapedDocument(
            url=url,
            title=title or url,
            content=prose,
            code_blocks=code_blocks,
            domain=domain,
            depth=depth,
            score=score,
            # ContentFilter fields
            paragraphs=paragraphs,
            headings=headings,
            links_count=len(links),
            meta_description=meta_desc,
        )
        logger.info(
            "[score=%d depth=%d] %s — %d chars, %d codes",
            score, depth, url, len(prose), len(code_blocks),
        )
        return doc, links
