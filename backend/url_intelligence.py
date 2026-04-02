"""
url_intelligence.py
-------------------
Universal URL scoring and filtering.

Works on ANY website using purely structural signals:
  - Path segment semantics  (login, signup → always noise, docs → always good)
  - File extension rejection (images, archives, fonts)
  - URL shape heuristics     (depth, query params, patterns)
  - Domain-relative scoring  (same domain as seed = bonus)

Zero hardcoded domain lists. Extend via `URLIntelligence(extra_blocklist=[...])`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse, urlunparse

# ---------------------------------------------------------------------------
# Universal blocked path SEGMENTS
# These apply to ANY website. A path segment is one slash-delimited part.
# e.g.  /en/docs/login  →  segments = ["en", "docs", "login"]  → blocked (login)
# ---------------------------------------------------------------------------

BLOCKED_SEGMENTS: frozenset[str] = frozenset({
    # ── Auth / account ────────────────────────────────────────────────
    "login", "logout", "signin", "signout", "signup", "register",
    "join", "auth", "oauth", "sso", "saml", "callback",
    "reset-password", "forgot-password", "change-password",
    "verify", "verify-email", "confirm-email",
    "two-factor", "2fa", "mfa", "totp",
    "session", "sessions", "tokens",
    # ── Commercial / marketing ────────────────────────────────────────
    "pricing", "plans", "plan", "billing", "invoice", "invoices",
    "checkout", "cart", "payment", "payments", "subscribe",
    "subscription", "upgrade", "downgrade", "enterprise",
    "contact", "contact-us", "sales", "demo", "request-demo",
    "quote", "get-quote", "free-trial", "start-trial",
    "careers", "jobs", "job", "hiring", "work-with-us",
    "about", "about-us", "team", "our-team", "company",
    "press", "media", "newsroom", "investors", "ir",
    "partners", "partner", "affiliates", "affiliate",
    "advertise", "advertising", "ads", "sponsor", "sponsors",
    "newsletter", "mailing-list", "email-list",
    "events", "event", "webinar", "webinars", "conference",
    "podcast", "podcasts", "videos", "video",
    "shop", "store", "merchandise", "swag",
    "donate", "donation", "donations",
    # ── Legal / policy ────────────────────────────────────────────────
    "terms", "tos", "terms-of-service", "terms-and-conditions",
    "privacy", "privacy-policy", "cookie-policy", "cookie-preferences",
    "gdpr", "ccpa", "legal", "licenses", "copyright",
    "dmca", "takedown", "report-abuse",
    "security",          # /security landing pages (not /security/advisories content)
    "vulnerability", "responsible-disclosure",
    # ── Navigation / discovery ────────────────────────────────────────
    "search", "find", "explore", "browse",
    "trending", "popular", "featured", "recommended",
    "sitemap", "site-map",
    "404", "500", "error", "not-found",
    "offline", "maintenance", "status",
    # ── CMS / infra noise ─────────────────────────────────────────────
    "wp-admin", "wp-login", "wp-json", "wp-content",
    "admin", "administrator", "dashboard", "panel", "backend",
    "cdn-cgi", "healthcheck", "health", "ping", "robots.txt",
    "feed", "rss", "atom", "rss.xml", "atom.xml",
    # ── Social / community (profile/follow pages, not content) ───────
    "followers", "following", "friends", "connections",
    "likes", "reactions", "shares", "reposts",
    "notifications", "inbox", "messages",
    "settings", "preferences", "profile", "account",
    "edit-profile", "edit", "new",
})

# ---------------------------------------------------------------------------
# Blocked file extensions  (skip before any HTTP request)
# ---------------------------------------------------------------------------

BLOCKED_EXTENSIONS: frozenset[str] = frozenset({
    # Images
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".avif",
    ".bmp", ".tiff", ".tif",
    # Media
    ".mp4", ".mp3", ".avi", ".mov", ".mkv", ".webm",
    ".wav", ".ogg", ".flac", ".aac",
    # Archives / binaries
    ".zip", ".tar", ".gz", ".tgz", ".bz2", ".7z", ".rar",
    ".exe", ".dmg", ".pkg", ".deb", ".rpm", ".apk",
    # Fonts
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    # Documents (not HTML — handled separately by scrapers that want PDFs)
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    # Code assets (not prose)
    ".css", ".map", ".min.js",
})

# ---------------------------------------------------------------------------
# Blocked URL PATH PATTERNS  (regex, applied to full path)
# These catch structural patterns no single-segment check can catch.
# ---------------------------------------------------------------------------

BLOCKED_PATH_PATTERNS: list[re.Pattern] = [
    # Pagination: ?page=N, /page/2, /p/3, /2/, /3/ at end of path
    re.compile(r"[?&]page=\d+", re.I),
    re.compile(r"/page/\d+(/|$)", re.I),
    re.compile(r"/p/\d+(/|$)", re.I),
    re.compile(r"/\d+(/|$)"),           # bare number path segments (often IDs)
    # Old versioned docs: /v1.2.3/, /1.0/, /0.9.x/
    re.compile(r"/v?\d+\.\d+[\.\d]*x?(/|$)", re.I),
    # Download / raw file endpoints
    re.compile(r"/(download|raw|export|print)(/|$|\?)", re.I),
    # User-generated spam paths
    re.compile(r"/(tag|tags|category|categories|label|labels)/", re.I),
    re.compile(r"/(author|user|users|u|profile)/[^/]+(/|$)", re.I),
    # Date-based archives (blog indexes, not articles)
    re.compile(r"/\d{4}/\d{2}(/\d{2})?(/|$)"),
    # Tracking / UTM junk
    re.compile(r"[?&](utm_|ref=|source=|medium=|campaign=)", re.I),
    # Fragment-only
    re.compile(r"^#"),
]

# ---------------------------------------------------------------------------
# High-value path KEYWORDS  (appear anywhere in the path)
# ---------------------------------------------------------------------------

HIGH_VALUE_KEYWORDS: list[tuple[str, int]] = [
    # Core documentation
    (r"\b(docs?|documentation|manual|handbook|playbook)\b", 25),
    (r"\b(api|reference|spec|specification)\b", 22),
    (r"\b(guide|guides|tutorial|tutorials|walkthrough)\b", 20),
    (r"\b(wiki|knowledge.?base|kb)\b", 20),
    (r"\b(getting.?started|quickstart|quick.?start|onboarding)\b", 18),
    (r"\b(introduction|intro|overview|concepts?|architecture)\b", 15),
    (r"\b(example|examples|sample|samples|demo|cookbook|recipes?)\b", 14),
    (r"\b(howto|how.?to|faq|troubleshoot|debug|diagnose)\b", 12),
    (r"\b(readme|changelog|migration|release.?notes?|upgrading)\b", 12),
    (r"\b(install|installation|setup|configuration|config)\b", 10),
    # Blog / articles (actual content, not index)
    (r"\b(blog|articles?|posts?|learn)\b", 8),
]

LOW_VALUE_KEYWORDS: list[tuple[str, int]] = [
    (r"\b(archive|archives)\b", -8),
    (r"\b(test|tests|spec|specs|fixture|fixtures)\b", -10),
    (r"\.(png|jpg|jpeg|gif|svg|css|js|woff|ttf)$", -50),
]


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class URLIntelligence:
    """
    Universal URL scorer — works on any website.

    Parameters
    ----------
    seed_url        : str   - The crawl's starting URL (used for same-domain bonus)
    extra_blocklist : list  - Additional path segments to block (site-specific)
    min_score       : int   - Score threshold; URLs below this are treated as blocked
    stay_on_domain  : bool  - Penalise cross-domain URLs heavily (default True)
    """

    def __init__(
        self,
        seed_url: str,
        extra_blocklist: Optional[list[str]] = None,
        min_score: int = 25,
        stay_on_domain: bool = True,
    ) -> None:
        parsed = urlparse(seed_url)
        self.seed_host: str = parsed.netloc.lower().lstrip("www.")
        self.seed_path_prefix: str = parsed.path.rstrip("/")
        self.min_score = min_score
        self.stay_on_domain = stay_on_domain

        # Merge extra blocklist
        self._blocklist = BLOCKED_SEGMENTS
        if extra_blocklist:
            self._blocklist = BLOCKED_SEGMENTS | frozenset(
                s.lower().strip("/") for s in extra_blocklist
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_allowed(self, url: str) -> bool:
        """
        Fast gate — returns False if the URL should never be fetched.
        Called on every discovered link; must be cheap.
        """
        if not url:
            return False

        # Must be HTTP(S)
        if not url.startswith(("http://", "https://")):
            return False

        try:
            parsed = urlparse(url)
        except Exception:
            return False

        path = parsed.path.lower()

        # 1. Extension check
        for ext in BLOCKED_EXTENSIONS:
            if path.endswith(ext):
                return False

        # 2. Path-pattern check
        full = path + ("?" + parsed.query if parsed.query else "")
        for pat in BLOCKED_PATH_PATTERNS:
            if pat.search(full):
                return False

        # 3. Segment check  — split path into parts, reject if any is blocked
        segments = {s for s in path.split("/") if s}
        if segments & self._blocklist:
            return False

        return True

    def score(self, url: str) -> int:
        """
        Score 0–100. Higher = more likely to contain useful content.
        Returns 0 for URLs that fail is_allowed().
        """
        if not self.is_allowed(url):
            return 0

        try:
            parsed = urlparse(url)
        except Exception:
            return 0

        host = parsed.netloc.lower().lstrip("www.")
        path = parsed.path.lower()
        score = 50  # baseline

        # ── Same-domain signal ────────────────────────────────────────
        if self.seed_host and (self.seed_host in host or host in self.seed_host):
            score += 15
        elif self.stay_on_domain:
            score -= 25  # cross-domain is deprioritised, not blocked

        # ── Sub-path bonus: URL starts with the seed path ─────────────
        if self.seed_path_prefix and path.startswith(self.seed_path_prefix):
            score += 10

        # ── High-value keyword bonuses ────────────────────────────────
        for pattern, delta in HIGH_VALUE_KEYWORDS:
            if re.search(pattern, path, re.I):
                score += delta
                break  # only the best match

        # ── Low-value keyword penalties ───────────────────────────────
        for pattern, delta in LOW_VALUE_KEYWORDS:
            if re.search(pattern, path, re.I):
                score += delta  # already negative
                break

        # ── Path depth: shallower = more likely to be a hub/landing ──
        depth = len([s for s in path.split("/") if s])
        if depth == 0:
            score += 5   # root
        elif depth <= 2:
            score += 8   # /docs, /docs/api
        elif depth <= 4:
            score += 3   # /docs/reference/types
        elif depth >= 7:
            score -= 8   # very deep = probably generated/archive

        # ── Query string penalty ─────────────────────────────────────
        if parsed.query:
            score -= 5

        return max(0, min(100, score))

    def filter_and_rank(self, urls: list[str]) -> list[str]:
        """Return only allowed URLs, sorted best-first."""
        scored = []
        for u in urls:
            s = self.score(u)
            if s >= self.min_score:
                scored.append((s, u))
        scored.sort(reverse=True)
        return [u for _, u in scored]

    def is_worth_crawling(self, url: str) -> bool:
        return self.score(url) >= self.min_score

    def explain(self, url: str) -> dict:
        """Debug helper — returns score breakdown."""
        allowed = self.is_allowed(url)
        s = self.score(url) if allowed else 0
        label = (
            "excellent" if s >= 80 else
            "good"      if s >= 60 else
            "ok"        if s >= 40 else
            "low"       if s >= 25 else
            "skip"
        )
        return {"url": url, "allowed": allowed, "score": s, "label": label}
