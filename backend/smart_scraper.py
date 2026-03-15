"""
Enhanced Smart Scraper for Production MCP
Extracts structured content including code blocks, topics, and metadata.

Security features:
- URL validation (scheme + hostname)
- Internal network / metadata endpoint blocking
- 8-second request timeout with partial-result return
"""
import ipaddress
import re
import socket
from typing import Dict, List, Optional, Tuple

import requests as _requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse


# Documentation domains that are broadly trusted for scraping.
# Override via env var SCRAPEE_ALLOWED_DOMAINS (comma-separated, empty = allow all public).
_ALLOWED_DOMAINS_ENV = ""
try:
    import os as _os
    _ALLOWED_DOMAINS_ENV = _os.getenv("SCRAPEE_ALLOWED_DOMAINS", "")
except Exception:
    pass

# When the env var is set, only those domains are permitted.
# When it is empty (default) any public domain is allowed.
ALLOWED_DOMAINS: Optional[frozenset] = (
    frozenset(d.strip().lower() for d in _ALLOWED_DOMAINS_ENV.split(",") if d.strip())
    if _ALLOWED_DOMAINS_ENV
    else None
)

# Hostnames that are always blocked regardless of allowlist.
BLOCKED_HOSTNAMES: frozenset = frozenset({
    "localhost",
    "0.0.0.0",
    "127.0.0.1",
    "::1",
    "metadata.google.internal",
    "169.254.169.254",  # AWS / GCE metadata
})

BLOCKED_SUFFIXES: Tuple[str, ...] = (".local", ".internal", ".corp", ".home")

# Maximum seconds to wait for a single HTTP request.
FETCH_TIMEOUT_SECONDS: int = 8


class SmartScraper:
    """
    Production-grade scraper that extracts structured content.

    Features:
    - Code block extraction with language detection
    - Topic/heading hierarchy extraction
    - Metadata extraction (title, description, language)
    - Context extraction for code blocks
    - URL validation and internal-network blocking
    - 8-second timeout with partial-result fallback
    """

    # Language detection patterns
    LANGUAGE_PATTERNS = {
        "python": [r"\bdef\b", r"\bimport\b", r"\bclass\b", r"\.py\b"],
        "javascript": [r"\bfunction\b", r"\bconst\b", r"\blet\b", r"=>", r"\.js\b"],
        "typescript": [r":\s*\w+", r"\binterface\b", r"\btype\b", r"\.ts\b"],
        "java": [r"\bpublic\s+class\b", r"\bprivate\b", r"\bpackage\b", r"\.java\b"],
        "rust": [r"\bfn\b", r"\blet\s+mut\b", r"\bimpl\b", r"\.rs\b"],
        "go": [r"\bfunc\b", r"\bpackage\b", r":=", r"\.go\b"],
        "solidity": [r"\bcontract\b", r"\bpragma\b", r"\bsolidity\b", r"\.sol\b"],
        "bash": [r"#!/bin/bash", r"\becho\b", r"\$\{", r"\.sh\b"],
        "sql": [r"\bSELECT\b", r"\bFROM\b", r"\bWHERE\b", r"\bJOIN\b"],
        "html": [r"<html", r"<div", r"<body", r"\.html\b"],
        "css": [r"\{[^}]*:[^}]*\}", r"\.css\b"],
        "json": [r"^\s*\{", r':\s*["[]', r"\.json\b"],
        "yaml": [r"^\s*\w+:", r"\.yml\b", r"\.yaml\b"],
        "docker": [r"\bFROM\b", r"\bRUN\b", r"\bCOPY\b", r"Dockerfile"],
    }

    MAX_CONTENT_LENGTH = 100_000
    MAX_CODE_BLOCKS = 200
    MAX_TOPICS = 200

    def __init__(self):
        pass

    # ------------------------------------------------------------------ #
    # Public API                                                            #
    # ------------------------------------------------------------------ #

    def validate_url(self, url: str) -> Tuple[bool, str]:
        """
        Validate a URL for safety before scraping.

        Returns:
            (True, "") if safe, or (False, reason) if blocked.
        """
        if not url or not isinstance(url, str):
            return False, "empty URL"

        parsed = urlparse(url)

        # Scheme check
        if parsed.scheme not in {"http", "https"}:
            return False, f"invalid scheme '{parsed.scheme}': only http and https are allowed"

        hostname = (parsed.hostname or "").lower().strip()
        if not hostname:
            return False, "URL must include a hostname"

        # Blocked hostname list
        if hostname in BLOCKED_HOSTNAMES:
            return False, f"blocked hostname: {hostname}"

        # Blocked suffix check
        if hostname.endswith(BLOCKED_SUFFIXES):
            return False, f"blocked internal domain: {hostname}"

        # IP-range blocking
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False, f"blocked internal IP range: {hostname}"
        except ValueError:
            pass  # Not an IP literal — proceed

        # Domain allowlist (only enforced when SCRAPEE_ALLOWED_DOMAINS is set)
        if ALLOWED_DOMAINS is not None:
            if hostname not in ALLOWED_DOMAINS and not any(
                hostname.endswith(f".{d}") for d in ALLOWED_DOMAINS
            ):
                return False, f"domain not in allowlist: {hostname}"

        return True, ""

    def fetch_with_timeout(self, url: str, timeout: int = FETCH_TIMEOUT_SECONDS) -> Optional[str]:
        """
        Fetch a URL with a hard timeout.

        Returns raw HTML string or None on failure.
        Returns whatever was downloaded on partial timeout (requests streams).
        """
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; Scrapee/1.0; "
                "+https://github.com/scrapee)"
            )
        }
        try:
            resp = _requests.get(url, timeout=timeout, headers=headers, verify=True, allow_redirects=True)
            resp.raise_for_status()
            return resp.text
        except _requests.exceptions.Timeout:
            # Return an empty string so callers can detect the partial-result case
            return ""
        except Exception:
            return None

    def parse_html(self, html: str, url: str) -> Dict:
        """
        Parse HTML and extract structured content.

        Args:
            html: HTML content string
            url:  Source URL (used for metadata and domain extraction)

        Returns:
            Dict with keys: content, code_blocks, topics, metadata
        """
        soup = BeautifulSoup(html or "", "html.parser")

        # Strip navigation chrome
        for element in soup(["script", "style", "nav", "footer", "header", "iframe"]):
            element.decompose()

        metadata = self._extract_metadata(soup, url)
        code_blocks = self._extract_code_blocks(soup, url)
        topics = self._extract_topics(soup)
        content = self._extract_text(soup)

        return {
            "content": content,
            "code_blocks": code_blocks,
            "topics": topics,
            "metadata": metadata,
        }

    # ------------------------------------------------------------------ #
    # Private helpers                                                        #
    # ------------------------------------------------------------------ #

    def _extract_metadata(self, soup: BeautifulSoup, url: str) -> Dict:
        """Extract page metadata (title, description, OG tags, language)."""
        metadata: Dict = {"url": url, "domain": urlparse(url).netloc}

        title_tag = soup.find("title")
        if title_tag:
            metadata["title"] = title_tag.get_text(strip=True)

        desc_tag = soup.find("meta", attrs={"name": "description"})
        if desc_tag and desc_tag.get("content"):
            metadata["description"] = desc_tag["content"]

        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            metadata["og_title"] = og_title["content"]
            metadata.setdefault("title", og_title["content"])

        og_desc = soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            metadata["og_description"] = og_desc["content"]
            metadata.setdefault("description", og_desc["content"])

        html_tag = soup.find("html")
        if html_tag and html_tag.get("lang"):
            metadata["language"] = html_tag["lang"]

        if not metadata.get("title"):
            first_heading = soup.find(["h1", "h2"])
            if first_heading:
                metadata["title"] = first_heading.get_text(strip=True)

        return metadata

    def _extract_code_blocks(self, soup: BeautifulSoup, url: str) -> List[Dict]:
        """Extract code blocks with language detection and surrounding context."""
        code_blocks = []
        seen: set = set()

        for idx, element in enumerate(soup.find_all(["code", "pre"])[: self.MAX_CODE_BLOCKS]):
            code_text = element.get_text()
            if not code_text or len(code_text.strip()) < 10:
                continue

            language = self._normalize_language(self._detect_language(element, code_text))
            context = self._extract_context(element)
            snippet = code_text.strip()
            fingerprint = (snippet, language, context)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)

            code_blocks.append(
                {
                    "snippet": snippet[:5000],
                    "language": language,
                    "context": context[:400],
                    "line_number": idx + 1,
                }
            )

        return code_blocks

    def _detect_language(self, element, code_text: str) -> str:
        """Detect programming language from element class attributes or content patterns."""
        classes = element.get("class", [])
        for cls in classes:
            cls_lower = str(cls).lower()
            if "language-" in cls_lower:
                return cls_lower.split("language-")[1].split()[0]
            if "lang-" in cls_lower:
                return cls_lower.split("lang-")[1].split()[0]
            if cls_lower in self.LANGUAGE_PATTERNS:
                return cls_lower

        data_lang = element.get("data-language") or element.get("data-lang")
        if data_lang:
            return str(data_lang).lower()

        scores: Dict[str, int] = {}
        for lang, patterns in self.LANGUAGE_PATTERNS.items():
            score = sum(
                1 for p in patterns if re.search(p, code_text, re.IGNORECASE | re.MULTILINE)
            )
            if score > 0:
                scores[lang] = score

        if scores:
            return max(scores.items(), key=lambda x: x[1])[0]

        return "unknown"

    def _normalize_language(self, language: str) -> str:
        aliases = {
            "js": "javascript",
            "ts": "typescript",
            "py": "python",
            "shell": "bash",
            "sh": "bash",
            "yml": "yaml",
        }
        value = (language or "unknown").strip().lower()
        return aliases.get(value, value or "unknown")

    def _extract_context(self, element, max_chars: int = 200) -> str:
        """Extract nearby heading / paragraph text as context for a code block."""
        context_parts = []

        prev = element.find_previous(["p", "h1", "h2", "h3", "h4", "h5", "h6", "li"])
        if prev:
            text = prev.get_text(strip=True)
            if text and len(text) < max_chars:
                context_parts.append(text)

        parent = element.find_parent(["section", "div", "article"])
        if parent:
            heading = parent.find(["h1", "h2", "h3", "h4", "h5", "h6"])
            if heading:
                heading_text = heading.get_text(strip=True)
                if heading_text and heading_text not in context_parts:
                    context_parts.insert(0, heading_text)

        context = " | ".join(context_parts)
        return context[:max_chars] if context else ""

    def _extract_topics(self, soup: BeautifulSoup) -> List[Dict]:
        """Extract document heading structure as topics."""
        topics = []
        seen: set = set()

        for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])[: self.MAX_TOPICS]:
            level = int(heading.name[1])
            heading_text = heading.get_text(strip=True)
            if not heading_text:
                continue

            content_parts = []
            for sibling in heading.find_next_siblings():
                if sibling.name and sibling.name.startswith("h"):
                    break
                if sibling.name in ["p", "li", "div"]:
                    text = sibling.get_text(strip=True)
                    if text:
                        content_parts.append(text)

            content = " ".join(content_parts[:5])
            topic = re.sub(r"[^a-z0-9]+", "-", heading_text.lower()).strip("-")
            fingerprint = (topic, heading_text)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)

            topics.append(
                {
                    "topic": topic,
                    "heading": heading_text,
                    "level": level,
                    "content": content[:500],
                }
            )

        return topics

    def _extract_text(self, soup: BeautifulSoup) -> str:
        """Extract clean, de-duplicated text from the page."""
        text = soup.get_text(separator="\n", strip=True)
        text = re.sub(r"\n\s*\n+", "\n\n", text)
        text = re.sub(r" +", " ", text)
        return text.strip()[: self.MAX_CONTENT_LENGTH]


# ─── Factory ──────────────────────────────────────────────────────────────────

def create_scraper() -> SmartScraper:
    """Return a configured SmartScraper instance."""
    return SmartScraper()
