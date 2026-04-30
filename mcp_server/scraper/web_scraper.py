"""Reliable URL scraper with retries and structured extraction."""

from __future__ import annotations

import re
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from mcp_server.config import SCRAPE_REQUEST_TIMEOUT_SECONDS
from mcp_server.logging_utils import get_logger
from mcp_server.utils import chunk_text, document_uri_for_url, normalize_source_url, validate_public_url


logger = get_logger(__name__)


class WebScraper:
    """Crawls public documentation pages and extracts structured content."""
    def __init__(self, config=None, *, allowed_domains: Sequence[str] | None = None, timeout_seconds: int = SCRAPE_REQUEST_TIMEOUT_SECONDS):
        configured_domains = allowed_domains
        if config is not None and configured_domains is None:
            configured_domains = getattr(config, "allowed_domains", None)
        configured_timeout = timeout_seconds
        if config is not None:
            configured_timeout = int(getattr(config, "scrape_timeout_seconds", configured_timeout))

        self.allowed_domains = tuple(configured_domains or ())
        self.timeout_seconds = configured_timeout
        self.smart_available = True
        self.selenium_available = False
        self.ultrafast_available = False
        self.timeout_seconds = timeout_seconds
        self._session = self._build_session()

    def validate_url(self, url: str) -> tuple[bool, str]:
        normalized = normalize_source_url(url)
        if not normalized:
            return False, "Invalid URL format"
        return validate_public_url(normalized, self.allowed_domains)

    def _build_session(self) -> requests.Session:
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=0.6,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session = requests.Session()
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update(
            {
                "User-Agent": "scrapee-mcp/3.0 (+https://github.com/jonathanvineet/scrapee)",
                "Accept": "text/html,application/xhtml+xml",
            }
        )
        return session

    def fetch(self, url: str) -> Optional[str]:
        try:
            response = self._session.get(url, timeout=self.timeout_seconds)
            if response.status_code >= 400:
                logger.warning("Failed to fetch %s (status=%s)", url, response.status_code)
                return None
            return response.text
        except requests.RequestException as exc:
            logger.warning("Request failed for %s: %s", url, exc)
            return None

    def crawl(self, start_url: str, *, max_depth: int = 0, max_pages: int = 20) -> Dict[str, object]:
        normalized_start = normalize_source_url(start_url)
        is_valid, reason = validate_public_url(normalized_start, self.allowed_domains)
        if not is_valid:
            raise ValueError(f"Invalid URL: {reason}")

        base_host = urlparse(normalized_start).netloc.lower()
        queue: deque[Tuple[str, int]] = deque([(normalized_start, 0)])
        visited: set[str] = set()
        pages: List[Dict[str, object]] = []
        errors: List[Dict[str, str]] = []

        while queue and len(pages) < max_pages:
            url, depth = queue.popleft()
            if url in visited:
                continue
            visited.add(url)
            html = self.fetch(url)
            if not html:
                errors.append({"url": url, "reason": "fetch_failed"})
                continue

            parsed, links = self.parse_html(url, html)
            pages.append(parsed)

            if depth >= max_depth:
                continue
            for link in links:
                parsed_link = urlparse(link)
                if parsed_link.netloc.lower() != base_host:
                    continue
                if link not in visited:
                    queue.append((link, depth + 1))

        return {
            "start_url": normalized_start,
            "pages": pages,
            "visited_pages": len(visited),
            "errors": errors,
        }

    def parse_html(self, url: str, html: str) -> Tuple[Dict[str, object], List[str]]:
        soup = BeautifulSoup(html, "html.parser")
        for element in soup(["script", "style", "noscript", "iframe", "svg"]):
            element.decompose()

        title = self._extract_title(soup, url)
        content = self._extract_content(soup)
        code_blocks = self._extract_code_blocks(soup)
        chunks = chunk_text(content)
        links = self._extract_links(url, soup)

        return (
            {
                "uri": document_uri_for_url(url),
                "source_url": normalize_source_url(url),
                "title": title,
                "content": content,
                "chunks": chunks,
                "code_blocks": code_blocks,
                "metadata": {
                    "domain": urlparse(url).netloc.lower(),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "word_count": len(content.split()),
                    "chunk_count": len(chunks),
                    "code_block_count": len(code_blocks),
                },
            },
            links,
        )

    def _extract_title(self, soup: BeautifulSoup, url: str) -> str:
        if soup.title and soup.title.get_text(strip=True):
            return soup.title.get_text(strip=True)
        heading = soup.find(["h1", "h2"])
        if heading and heading.get_text(strip=True):
            return heading.get_text(strip=True)
        return url

    def _extract_content(self, soup: BeautifulSoup) -> str:
        """🔥 RULE 2: Universal extraction — NEVER FAIL."""
        # Remove garbage tags
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        
        # Primary extraction
        text = soup.get_text(" ", strip=True)
        
        content = text.lower() if text else ""
        print(f"[EXTRACT] Content length: {len(content)} chars")
        return content



    def _extract_links(self, source_url: str, soup: BeautifulSoup) -> List[str]:
        links: List[str] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "").strip()
            if not href:
                continue
            joined = normalize_source_url(urljoin(source_url, href))
            if not joined:
                continue
            is_valid, _ = validate_public_url(joined, self.allowed_domains)
            if not is_valid:
                continue
            if joined in seen:
                continue
            seen.add(joined)
            links.append(joined)
        return links

    def _extract_code_blocks(self, soup: BeautifulSoup) -> List[Dict[str, object]]:
        blocks: List[Dict[str, object]] = []
        seen: set[Tuple[str, str]] = set()
        candidates = soup.find_all(["pre", "code"])
        for index, element in enumerate(candidates):
            code = element.get_text("\n", strip=True)
            if len(code) < 20:
                continue
            language = self._detect_language(element, code)
            context = self._code_context(element)
            key = (code, language)
            if key in seen:
                continue
            seen.add(key)
            blocks.append(
                {
                    "language": language,
                    "snippet": code[:12000],
                    "context": context[:400],
                    "line_start": index + 1,
                }
            )
        return blocks

    def _detect_language(self, element: BeautifulSoup, code: str) -> str:
        classes = " ".join(element.get("class", []))
        classes = classes.lower()
        for prefix in ("language-", "lang-"):
            if prefix in classes:
                tail = classes.split(prefix, 1)[1]
                language = re.split(r"[^a-z0-9_-]", tail)[0]
                if language:
                    return language
        lower = code.lower()
        if "def " in lower and "import " in lower:
            return "python"
        if "const " in lower or "function " in lower:
            return "javascript"
        if "interface " in lower and ": " in lower:
            return "typescript"
        if "<?php" in lower:
            return "php"
        if "select " in lower and " from " in lower:
            return "sql"
        return "text"

    def _code_context(self, element: BeautifulSoup) -> str:
        heading = element.find_previous(["h1", "h2", "h3", "h4"])
        para = element.find_previous("p")
        parts = []
        if heading and heading.get_text(strip=True):
            parts.append(heading.get_text(strip=True))
        if para and para.get_text(strip=True):
            parts.append(para.get_text(strip=True))
        return " | ".join(parts)
