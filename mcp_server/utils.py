"""Utility helpers for URL normalization, validation, and text processing."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from typing import List, Sequence, Tuple
from urllib.parse import urldefrag, urlparse


BLOCKED_HOSTNAMES = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "169.254.169.254"}
BLOCKED_SUFFIXES = (".local", ".internal", ".corp", ".home")


def json_dumps(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def normalize_source_url(url: str) -> str:
    if not isinstance(url, str):
        return ""
    raw = url.strip()
    if not raw:
        return ""
    normalized, _ = urldefrag(raw)
    parsed = urlparse(normalized)
    if not parsed.scheme or not parsed.netloc:
        return ""
    scheme = parsed.scheme.lower()
    host = parsed.netloc.lower()
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{scheme}://{host}{path}{query}"


def validate_public_url(url: str, allowed_domains: Sequence[str] | None = None) -> Tuple[bool, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False, "Only http and https URLs are allowed."

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return False, "URL must include a hostname."
    if hostname in BLOCKED_HOSTNAMES or hostname.endswith(BLOCKED_SUFFIXES):
        return False, "Internal/blocked hostnames are not allowed."

    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False, "Internal/private IP addresses are not allowed."
    except ValueError:
        pass

    if allowed_domains:
        allowed = {d.lower() for d in allowed_domains}
        if hostname not in allowed and not any(hostname.endswith(f".{domain}") for domain in allowed):
            return False, "Domain is not in the configured allowlist."

    return True, ""


def document_uri_for_url(url: str) -> str:
    normalized = normalize_source_url(url)
    parsed = urlparse(normalized)
    stem = parsed.path.strip("/") or "index"
    safe_stem = re.sub(r"[^a-zA-Z0-9/_-]+", "-", stem)[:120].strip("-") or "index"
    query_hash = ""
    if parsed.query:
        digest = hashlib.sha1(parsed.query.encode("utf-8")).hexdigest()[:12]
        query_hash = f"-q{digest}"
    return f"docs://{parsed.netloc.lower()}/{safe_stem}{query_hash}"


def code_uri_for_snippet(document_uri: str, position: int) -> str:
    digest = hashlib.sha1(f"{document_uri}:{position}".encode("utf-8")).hexdigest()[:12]
    return f"code://snippet/{digest}"


def chunk_text(text: str, size: int = 1400, overlap: int = 200) -> List[str]:
    cleaned = re.sub(r"\n{3,}", "\n\n", text.strip())
    if not cleaned:
        return []
    if len(cleaned) <= size:
        return [cleaned]

    chunks: List[str] = []
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + size)
        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(cleaned):
            break
        start = max(start + size - overlap, end)
    return chunks


def fts_query_from_text(query: str) -> str:
    tokens = [token for token in re.findall(r"[A-Za-z0-9_./:-]+", query) if token]
    if not tokens:
        return "\"\""
    return " AND ".join(f"\"{token}\"*" for token in tokens)


def first_url_in_text(text: str) -> str | None:
    if not text:
        return None
    match = re.search(r"https?://[^\s]+", text)
    if not match:
        return None
    return normalize_source_url(match.group(0))


def clamp_int(value: object, *, minimum: int, maximum: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))
