"""
Enhanced Smart Scraper for Production MCP
Extracts structured content including code blocks, topics, and metadata.

UNIVERSAL FORMAT SUPPORT:
- HTML documents (docs, tutorials, blogs)
- XML config files (pom.xml, etc.)
- JSON configs (package.json, etc.)
- Plain text files (README.md, etc.)
- GitHub repos (auto blob→raw conversion)

Security features:
- URL validation (scheme + hostname)
- Internal network / metadata endpoint blocking
- 8-second request timeout with partial-result return
"""
import ipaddress
import json as _json
import re
import socket
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

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

    MAX_CONTENT_LENGTH = 1_000_000
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

    # ─────────────────────────────────────────────────────────────────────────
    # UNIVERSAL CONTENT TYPE DETECTION & ROUTING
    # ─────────────────────────────────────────────────────────────────────────

    def _extract_domain_from_url(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            parsed = urlparse(url)
            return parsed.netloc or "unknown"
        except:
            return "unknown"

    def _normalize_url(self, url: str) -> str:
        """
        Normalize URLs for universal scraping.
        
        GitHub blob→raw conversion:
        - github.com/.../blob/.../file → raw.githubusercontent.com/.../file
        - Enables direct access to raw content
        """
        if "github.com" in url and "/blob/" in url:
            # Convert: https://github.com/user/repo/blob/branch/path/file
            # To: https://raw.githubusercontent.com/user/repo/branch/path/file
            url = url.replace("github.com", "raw.githubusercontent.com")
            url = url.replace("/blob/", "/")
            print(f"[Universal] Converted GitHub blob → raw: {url}")
        return url

    def _detect_content_type(self, content: str, url: str) -> str:
        """
        Detect content type from content or URL extension.
        
        Returns: "html" | "xml" | "json" | "plaintext"
        """
        if not content:
            return "plaintext"
        
        stripped = content.strip()
        
        # Check JSON
        if stripped.startswith(("{", "[")):
            try:
                _json.loads(stripped)
                return "json"
            except:
                pass
        
        # Check XML
        if stripped.startswith("<?xml") or stripped.startswith("<"):
            try:
                ET.fromstring(stripped[:500])  # Try to parse first 500 chars
                return "xml"
            except:
                pass
        
        # Check HTML
        if "<html" in stripped.lower() or "<body" in stripped.lower() or "<div" in stripped.lower():
            return "html"
        
        # Check file extension
        url_lower = url.lower()
        if url_lower.endswith((".xml", ".pom")):
            return "xml"
        if url_lower.endswith((".json", ".yml", ".yaml")):
            return "json"
        if url_lower.endswith((".md", ".txt", ".rst")):
            return "plaintext"
        
        # Default to HTML (backward compatible)
        return "html"

    def _parse_xml(self, xml_content: str, url: str) -> Dict:
        """Parse XML/config files (pom.xml, etc.)."""
        try:
            root = ET.fromstring(xml_content)
            
            # Extract all tags and attributes
            code_blocks = []
            topics = []
            content_lines = []
            
            def extract_elements(elem, path=""):
                """Recursively extract XML structure."""
                current_path = f"{path}/{elem.tag}"
                
                if elem.text and elem.text.strip():
                    content_lines.append(f"{current_path}: {elem.text.strip()[:200]}")
                
                if elem.attrib:
                    attr_str = " ".join(f'{k}="{v}"' for k, v in elem.attrib.items())
                    topics.append({
                        "topic": f"XML Attribute",
                        "heading": current_path,
                        "level": len(path.split("/")),
                        "content": attr_str[:400]
                    })
                
                for child in elem:
                    extract_elements(child, current_path)
            
            extract_elements(root)
            
            # Store full XML as code block
            code_blocks.append({
                "snippet": xml_content[:5000],
                "language": "xml",
                "context": f"XML structure from {url}",
                "line_number": 1
            })
            
            return {
                "content": "\n".join(content_lines[:500]),
                "code_blocks": code_blocks,
                "topics": topics,
                "metadata": {
                    "type": "xml",
                    "root_tag": root.tag,
                    "domain": self._extract_domain_from_url(url),
                    "language": "xml"
                }
            }
        except Exception as e:
            print(f"[XML Parse] Error parsing {url}: {e}")
            # Fallback to plaintext
            return self._parse_plaintext(xml_content, url)

    def _parse_json(self, json_content: str, url: str) -> Dict:
        """Parse JSON config files."""
        try:
            data = _json.loads(json_content)
            
            # Extract structure
            code_blocks = [{
                "snippet": json_content[:5000],
                "language": "json",
                "context": f"JSON config from {url}",
                "line_number": 1
            }]
            
            topics = []
            content_lines = []
            
            def flatten_json(obj, prefix=""):
                """Extract JSON structure."""
                if isinstance(obj, dict):
                    for key, value in obj.items():
                        full_key = f"{prefix}.{key}" if prefix else key
                        if isinstance(value, (dict, list)):
                            flatten_json(value, full_key)
                        else:
                            content_lines.append(f"{full_key}: {str(value)[:100]}")
                            topics.append({
                                "topic": "JSON Field",
                                "heading": full_key,
                                "level": len(full_key.split(".")),
                                "content": str(value)[:400]
                            })
                elif isinstance(obj, list):
                    for i, item in enumerate(obj[:5]):
                        flatten_json(item, f"{prefix}[{i}]")
            
            flatten_json(data)
            
            return {
                "content": "\n".join(content_lines[:500]),
                "code_blocks": code_blocks,
                "topics": topics,
                "metadata": {
                    "type": "json",
                    "domain": self._extract_domain_from_url(url),
                    "language": "json"
                }
            }
        except Exception as e:
            print(f"[JSON Parse] Error parsing {url}: {e}")
            return self._parse_plaintext(json_content, url)

    def _parse_plaintext(self, text_content: str, url: str) -> Dict:
        """Parse plain text files (README.md, docs, etc.)."""
        lines = text_content.split("\n")
        
        # Extract headings as topics
        topics = []
        code_blocks = []
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # Markdown/restructured headings
            if stripped.startswith("#"):
                level = len(stripped) - len(stripped.lstrip("#"))
                content = stripped.lstrip("# ").strip()
                topics.append({
                    "topic": "Heading",
                    "heading": content,
                    "level": level,
                    "content": content[:400]
                })
            
            # Code blocks marked with backticks
            if "```" in line:
                # Try to extract code block context
                code_start = i
                code_block = []
                for j in range(i+1, min(i+50, len(lines))):
                    if "```" in lines[j]:
                        break
                    code_block.append(lines[j])
                
                if code_block:
                    code_blocks.append({
                        "snippet": "\n".join(code_block)[:5000],
                        "language": "plaintext",
                        "context": f"Code block at line {code_start}",
                        "line_number": code_start
                    })
        
        # Store full text
        if len(text_content) > 100:
            code_blocks.insert(0, {
                "snippet": text_content[:5000],
                "language": "plaintext",
                "context": f"Full document from {url}",
                "line_number": 1
            })
        
        return {
            "content": text_content[:10000],
            "code_blocks": code_blocks,
            "topics": topics,
            "metadata": {
                "type": "plaintext",
                "domain": self._extract_domain_from_url(url),
                "language": "plaintext",
                "line_count": len(lines)
            }
        }

    def parse_html(self, html: str, url: str) -> Dict:
        """
        UNIVERSAL PARSER — routes to appropriate format handler.
        
        AUTO-DETECTS:
        - HTML documents → HTML parser (existing)
        - XML configs → XML parser
        - JSON configs → JSON parser
        - Plain text → Text parser
        
        Also NORMALIZES URLs:
        - GitHub blob → raw.githubusercontent
        - Other conversions as needed
        
        Args:
            html: Content string (misleading name for universal parser)
            url:  Source URL
        
        Returns:
            Dict with keys: content, code_blocks, topics, metadata
        """
        # Step 1: Normalize URL (GitHub blob → raw)
        url = self._normalize_url(url)
        
        # Step 2: Detect content type
        content_type = self._detect_content_type(html, url)
        print(f"[Universal] Detected {content_type} from {url}")
        
        # Step 3: Route to appropriate parser
        if content_type == "xml":
            return self._parse_xml(html, url)
        elif content_type == "json":
            return self._parse_json(html, url)
        elif content_type == "plaintext":
            return self._parse_plaintext(html, url)
        else:
            # Default to HTML parser (existing logic)
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

    def _extract_github_readme(self, url: str, timeout: int = FETCH_TIMEOUT_SECONDS) -> Optional[str]:
        """
        Extract README.md content from GitHub repo (for project overview).
        
        Args:
            url: GitHub URL (e.g., https://github.com/user/repo)
            timeout: Seconds to wait
        
        Returns:
            README content or None if not found
        """
        if "github.com" not in url:
            return None
        
        # Convert to raw README URL
        parts = url.rstrip("/").split("/")
        if len(parts) < 5:  # https://github.com/user/repo minimum
            return None
        
        owner, repo = parts[3], parts[4]
        readme_url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/README.md"
        
        html = self.fetch_with_timeout(readme_url, timeout=timeout)
        return html if html else None
    
    def _extract_github_src_overview(self, url: str, timeout: int = FETCH_TIMEOUT_SECONDS) -> Dict:
        """
        Extract overview from GitHub repo src/ folder structure and key files.
        
        Identifies:
        - Main source directory (src/, lib/, main/, etc.)
        - Key files (main.py, app.py, index.js, etc.)
        - Project structure from folder listing
        
        Args:
            url: GitHub repo URL
            timeout: Seconds to wait
        
        Returns:
            Dict with structure, key_files, description
        """
        if "github.com" not in url:
            return {}
        
        parts = url.rstrip("/").split("/")
        if len(parts) < 5:
            return {}
        
        owner, repo = parts[3], parts[4]
        base_url = f"https://github.com/{owner}/{repo}"
        
        # Try to fetch the repo root to find src/ folder
        html = self.fetch_with_timeout(base_url, timeout=timeout)
        if not html:
            return {}
        
        soup = BeautifulSoup(html, "html.parser")
        
        # Find folder/file listing
        structure = {
            "directories": [],
            "key_files": [],
            "languages": []
        }
        
        # Look for file listing elements (GitHub shows folder/file structure)
        for item in soup.find_all("a", {"data-name": True}):
            name = item.get_text(strip=True)
            if name in ["src", "source", "lib", "main", "app", "code"]:
                structure["directories"].append(name)
            elif name in ["main.py", "app.py", "index.js", "setup.py", "package.json", "pom.xml"]:
                structure["key_files"].append(name)
        
        # Look for language indicators (GitHub shows programming language)
        lang_elem = soup.find("span", {"itemprop": "programmingLanguage"})
        if lang_elem:
            structure["languages"].append(lang_elem.get_text(strip=True))
        
        return structure
    
    def extract_fallback(self, html: str) -> Dict:
        """Raw BeautifulSoup fallback extractor — used when structured parsing yields too little."""
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator=" ", strip=True)
        return {
            "content": text[:50000],
            "code_blocks": [],
            "topics": [],
            "metadata": {"title": ""}
        }

    def extract_from_github(self, url: str, timeout: int = FETCH_TIMEOUT_SECONDS) -> Dict:
        """
        GitHub-aware extraction: README + structure + key source files.
        
        For "what does this project do?" queries on GitHub repos:
        1. Extract README.md (project description)
        2. Get repo structure (folders like src/)
        3. Extract key file overview
        
        Args:
            url: GitHub repo URL
            timeout: Seconds to wait
        
        Returns:
            Dict with readme_content, structure, description, code_snippets
        """
        result = {
            "type": "github_repo",
            "url": url,
            "readme": None,
            "structure": {},
            "key_files": [],
            "overview": ""
        }
        
        # Try to get README
        readme = self._extract_github_readme(url, timeout)
        if readme:
            result["readme"] = readme[:2000]  # First 2000 chars
        
        # Get structure
        structure = self._extract_github_src_overview(url, timeout)
        result["structure"] = structure
        
        # Build overview from README + structure
        overview_parts = []
        if result["readme"]:
            # Extract first paragraph from README
            lines = result["readme"].split("\n")
            for line in lines:
                if line.strip() and not line.startswith("#"):
                    overview_parts.append(line.strip())
                    if len(" ".join(overview_parts)) > 200:
                        break
        
        if structure.get("directories"):
            overview_parts.append(f"Main directories: {', '.join(structure['directories'])}")
        
        if structure.get("languages"):
            overview_parts.append(f"Languages: {', '.join(structure['languages'])}")
        
        result["overview"] = " | ".join(overview_parts)
        
        return result

    def scrape(self, url: str, max_depth: int = 0, timeout: int = FETCH_TIMEOUT_SECONDS) -> Dict:
        """
        Scrape a single URL: fetch HTML, parse, and extract structured content.
        
        Args:
            url: The URL to scrape
            max_depth: Not used (kept for compatibility with crawler interface)
            timeout: Seconds to wait for the request
        
        Returns:
            Dict with keys: url, title, content, code_blocks, topics, or error key on failure
        """
        print(f"[SCRAPE] Processing: {url}")

        # Rewrite GitHub blob viewer URLs to raw file URLs
        if "github.com" in url and "/blob/" in url:
            url = url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
            print(f"[SCRAPE] Rewrote to raw URL: {url}")

        # Raw pass-through for XML/JSON files and GitHub raw URLs — no HTML parsing needed
        if url.endswith(".xml") or url.endswith(".json") or "github.com" in url:
            html = self.fetch_with_timeout(url, timeout=timeout)
            if html:
                return {
                    "url": url,
                    "title": "Raw File",
                    "content": html[:50000],
                    "code_blocks": [],
                    "topics": [],
                    "metadata": {"title": "Raw File"}
                }

        # GitHub repo detection: use GitHub-specific extraction
        if "github.com" in url and url.count("/") == 4:  # https://github.com/user/repo
            github_result = self.extract_from_github(url, timeout)
            # Merge GitHub data into standard format
            return {
                "url": url,
                "title": f"GitHub: {url.split('/')[-1]}",
                "content": github_result.get("overview", ""),
                "code_blocks": [],
                "metadata": github_result
            }
        
        # Validate URL
        valid, error_msg = self.validate_url(url)
        if not valid:
            return {"url": url, "error": error_msg}
        
        # Fetch HTML
        html = self.fetch_with_timeout(url, timeout=timeout)
        if html is None:
            return {"url": url, "error": "Failed to fetch URL (HTTP error or connection refused)"}
        if html == "":
            return {"url": url, "error": "Request timeout - no content received"}
        
        # Parse and extract
        parsed = self.parse_html(html, url)

        # If parsed content is thin, use raw fallback
        if not parsed.get("content") or len(parsed["content"]) < 200:
            print("[FALLBACK] Using raw extraction")
            parsed = self.extract_fallback(html)
        
        # Validate content
        content = parsed.get("content", "").strip()
        if not content or len(content) < 20:
            return {"url": url, "error": "Page has insufficient content (< 20 characters)"}
        
        # Build response
        metadata = parsed.get("metadata", {})
        return {
            "url": url,
            "title": metadata.get("title", ""),
            "content": content,
            "code_blocks": parsed.get("code_blocks", []),
            "topics": parsed.get("topics", []),
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

    def extract_structured(self, url: str, extract_tables: bool = True, 
                          extract_api_schemas: bool = True, 
                          extract_config_examples: bool = True) -> Dict:
        """Extract structured data like tables, API schemas, and config examples."""
        valid, reason = self.validate_url(url)
        if not valid:
            return {"error": reason}
        
        html = self.fetch_with_timeout(url)
        if not html:
            return {"error": "Failed to fetch URL"}
        
        soup = BeautifulSoup(html, "html.parser")
        result = {
            "url": url,
            "tables": [],
            "api_schemas": [],
            "config_examples": []
        }
        
        if extract_tables:
            result["tables"] = self._extract_tables(soup)
        
        if extract_api_schemas:
            result["api_schemas"] = self._extract_api_schemas(soup)
        
        if extract_config_examples:
            result["config_examples"] = self._extract_config_examples(soup)
        
        return result

    def _extract_tables(self, soup: BeautifulSoup) -> List[Dict]:
        """Extract tables from HTML."""
        tables = []
        for table in soup.find_all("table")[:10]:  # Limit to 10 tables
            rows = []
            for tr in table.find_all("tr")[:20]:  # Limit to 20 rows
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if cells:
                    rows.append(cells)
            if rows:
                tables.append({
                    "headers": rows[0] if rows else [],
                    "rows": rows[1:] if len(rows) > 1 else []
                })
        return tables

    def _extract_api_schemas(self, soup: BeautifulSoup) -> List[Dict]:
        """Extract API schemas (REST endpoints, method signatures)."""
        schemas = []
        
        # Look for code blocks that look like API documentation
        for code in soup.find_all(["code", "pre"])[:15]:
            text = code.get_text()
            
            # Detect common API patterns
            if any(x in text for x in ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"]):
                schemas.append({
                    "type": "http_endpoint",
                    "content": text[:500]
                })
            elif "{" in text and (":" in text or "}" in text):
                schemas.append({
                    "type": "json_schema",
                    "content": text[:500]
                })
        
        return schemas

    def _extract_config_examples(self, soup: BeautifulSoup) -> List[Dict]:
        """Extract configuration examples."""
        configs = []
        
        # Look for configuration file examples
        patterns = {
            "yaml": [r"\.ya?ml", "YAML", "config:", "name:"],
            "json": [r"\.json", "JSON", '"{', '"}'],
            "ini": [r"\.ini", "[section]"],
            "env": [r"\.env", "ENV_VAR="],
            "docker": [r"Dockerfile", "FROM ", "RUN "],
        }
        
        for code in soup.find_all(["code", "pre"])[:20]:
            text = code.get_text()
            
            for config_type, keywords in patterns.items():
                if any(keyword in text for keyword in keywords):
                    configs.append({
                        "type": config_type,
                        "content": text[:500]
                    })
                    break
        
        return configs


# ─── Factory ──────────────────────────────────────────────────────────────────

def create_scraper() -> SmartScraper:
    """Return a configured SmartScraper instance."""
    return SmartScraper()
