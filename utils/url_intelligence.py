"""
url_intelligence.py
-------------------
Domain-aware URL scoring and filtering.

Two responsibilities:
  1. BLOCK  – Hard-reject URLs that are navigation/auth/marketing noise
              (e.g. /login, /signup, /pricing on ANY host; GitHub-specific
              paths like /stargazers, /watchers, etc.)
  2. SCORE  – Rank remaining URLs 0–100 so the crawler always processes
              high-value doc pages before low-value ones.

Usage
-----
    from utils.url_intelligence import URLIntelligence

    ui = URLIntelligence(seed_url="https://github.com/user/repo")
    ui.is_allowed("https://github.com/user/repo/blob/main/README.md")  # True
    ui.is_allowed("https://github.com/login")                          # False
    ui.score("https://github.com/user/repo/wiki/Home")                 # ~90
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Universal blocked path segments (apply to every domain)
# ---------------------------------------------------------------------------

UNIVERSAL_BLOCKED_SEGMENTS: set[str] = {
    # Auth / account management
    "login", "logout", "signin", "signout", "signup", "register",
    "auth", "oauth", "sso", "callback", "reset-password", "forgot-password",
    "verify-email", "two-factor", "mfa",
    # Marketing / acquisition
    "pricing", "plans", "billing", "subscribe", "subscription",
    "upgrade", "enterprise", "contact", "about", "careers", "jobs",
    "team", "company", "press", "blog", "newsletter", "events",
    "webinar", "podcast", "ebook", "download-pdf",
    # Legal
    "terms", "tos", "privacy", "cookie-policy", "legal", "dmca",
    "security", "vulnerability",
    # Misc noise
    "404", "500", "error", "maintenance", "offline",
    "cdn-cgi", "wp-admin", "wp-login", "wp-json",
    "feed", "rss", "sitemap", "robots.txt",
    "search",           # search UIs are not content
    "explore",
    "trending",
}

# ---------------------------------------------------------------------------
# Domain-specific blocked segment patterns (regex applied to full path)
# ---------------------------------------------------------------------------

DOMAIN_BLOCKED_PATTERNS: dict[str, list[str]] = {
    "github.com": [
        r"^/([^/]+/[^/]+)?/(stargazers|watchers|network|forks|followers|following)$",
        r"^/([^/]+/[^/]+)?/pulse(/.*)?$",
        r"^/([^/]+/[^/]+)?/graphs(/.*)?$",
        r"^/([^/]+/[^/]+)?/archive/",
        r"^/([^/]+/[^/]+)?/releases/download/",
        r"^/([^/]+/[^/]+)?/zipball/",
        r"^/([^/]+/[^/]+)?/tarball/",
        r"^/([^/]+/[^/]+)?/compare(/.*)?$",
        r"^/([^/]+/[^/]+)?/actions$",
        r"^/([^/]+/[^/]+)?/projects$",
        r"^/([^/]+/[^/]+)?/packages$",
        r"^/([^/]+/[^/]+)?/security(/.*)?$",
        r"^/([^/]+/[^/]+)?/insights(/.*)?$",
        r"^/([^/]+/[^/]+)?/settings(/.*)?$",
        r"^/([^/]+/[^/]+)?/deployments(/.*)?$",
        r"^/([^/]+/[^/]+)?/labels(/.*)?$",
        r"^/([^/]+/[^/]+)?/milestones(/.*)?$",
        r"^/([^/]+/[^/]+)?/sponsors(/.*)?$",
        r"^/marketplace(/.*)?$",
        r"^/explore(/.*)?$",
        r"^/topics(/.*)?$",
        r"^/trending(/.*)?$",
        r"^/notifications(/.*)?$",
        r"^/issues$",           # global issues feed, not repo issues
    ],
    "gitlab.com": [
        r"/-/profile(/.*)?$",
        r"/-/user_settings(/.*)?$",
        r"/-/admin(/.*)?$",
        r"/activity$",
        r"/pipelines(/.*)?$",
        r"/jobs(/.*)?$",
        r"/environments(/.*)?$",
    ],
    "docs.google.com": [
        r"/d/e/",               # published export links
    ],
    "npmjs.com": [
        r"^/login$",
        r"^/signup$",
        r"^/~",                 # user profiles
        r"^/org/",              # org pages
    ],
    "pypi.org": [
        r"^/account/",
        r"^/manage/",
    ],
}

# ---------------------------------------------------------------------------
# High-value path patterns → boost score
# ---------------------------------------------------------------------------

HIGH_VALUE_PATTERNS: list[tuple[str, int]] = [
    # Most valuable
    (r"/(readme|getting.?started|quickstart|introduction|overview|tutorial)(\.|$|/)", 30),
    (r"/(docs?|documentation|guide|manual|reference|api)(/|$)", 25),
    (r"/(wiki|handbook|playbook)(/|$)", 22),
    (r"/blob/(main|master)/.*(readme|changelog|contributing)", 20),
    # GitHub-specific valuable paths
    (r"/blob/(main|master)/docs?/", 20),
    (r"/blob/(main|master)/src/", 10),
    (r"/tree/(main|master)/docs?", 18),
    # Code examples
    (r"/(example|sample|demo|tutorial|cookbook)s?(/|$)", 15),
    # Changelog / migration
    (r"/(changelog|migration|release.?notes|upgrading|breaking.?changes)", 10),
    # Config / setup
    (r"/(installation|install|setup|configuration|config)(/|$|\?)", 10),
    # Concepts
    (r"/(concept|architecture|design|internals|how.?it.?works)(/|$)", 8),
    # FAQ
    (r"/(faq|troubleshoot|debug|issues|known.?issues)(/|$)", 5),
]

LOW_VALUE_PATTERNS: list[tuple[str, int]] = [
    (r"\?.*page=\d+", -10),         # paginated results
    (r"/v\d+\.\d+\.\d+/",  -5),     # old version docs
    (r"/(test|spec|fixture)s?/", -15),
    (r"\.(png|jpg|jpeg|gif|svg|ico|pdf|zip|tar|gz|woff|ttf|eot)$", -50),
    (r"^#", -100),                  # fragment-only
]

# ---------------------------------------------------------------------------
# File extension quick-rejects
# ---------------------------------------------------------------------------

BLOCKED_EXTENSIONS: set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".pdf", ".zip", ".tar", ".gz", ".tgz", ".bz2", ".7z",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".mp4", ".mp3", ".avi", ".mov", ".wav",
    ".css",                         # stylesheets (no content)
    ".js", ".ts",                   # raw JS/TS source (not prose)
    ".map",                         # source maps
}

# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

class URLIntelligence:
    """
    Determines whether a URL should be crawled and ranks it by likely
    content value.

    Parameters
    ----------
    seed_url : str
        The root URL the crawl started from. Used to compute same-domain
        checks and apply domain-specific rules.
    stay_on_domain : bool
        If True (default), URLs on a different domain are scored very low
        and flagged non-doclike. They will not be blocked, so the caller
        can still decide, but they won't be prioritised.
    """

    def __init__(self, seed_url: str, stay_on_domain: bool = True) -> None:
        parsed = urlparse(seed_url)
        self.seed_host: str = parsed.netloc.lower().lstrip("www.")
        self.stay_on_domain = stay_on_domain

        # Compile domain-specific blocked patterns once
        self._domain_patterns: list[re.Pattern] = []
        for domain, patterns in DOMAIN_BLOCKED_PATTERNS.items():
            if domain in self.seed_host or self.seed_host in domain:
                for pat in patterns:
                    self._domain_patterns.append(re.compile(pat, re.IGNORECASE))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_allowed(self, url: str) -> bool:
        """
        Returns False if the URL should be completely skipped.
        Fast path — called on every discovered link.
        """
        if not url or not url.startswith(("http://", "https://")):
            return False

        try:
            parsed = urlparse(url)
        except Exception:
            return False

        path = parsed.path.lower()

        # 1. Extension blocklist
        for ext in BLOCKED_EXTENSIONS:
            if path.endswith(ext):
                return False

        # 2. Universal blocked path segments
        segments = {s for s in path.split("/") if s}
        if segments & UNIVERSAL_BLOCKED_SEGMENTS:
            return False

        # 3. Domain-specific patterns
        for pat in self._domain_patterns:
            if pat.search(parsed.path):
                return False

        # 4. Fragment-only or empty
        if not path or path == "/":
            return True  # root is fine

        return True

    def score(self, url: str) -> int:
        """
        Score a URL from 0–100.
        Higher = crawl sooner.
        Returns 0 for non-allowed URLs (caller should check is_allowed first).
        """
        if not self.is_allowed(url):
            return 0

        try:
            parsed = urlparse(url)
        except Exception:
            return 0

        host = parsed.netloc.lower().lstrip("www.")
        path = (parsed.path + "?" + parsed.query if parsed.query else parsed.path).lower()

        score = 50  # base

        # Same-domain bonus
        if self.seed_host in host or host in self.seed_host:
            score += 20
        elif self.stay_on_domain:
            score -= 30  # penalise cross-domain strongly

        # High-value path bonuses
        for pattern, delta in HIGH_VALUE_PATTERNS:
            if re.search(pattern, path, re.IGNORECASE):
                score += delta
                break  # only first match

        # Low-value path penalties
        for pattern, delta in LOW_VALUE_PATTERNS:
            if re.search(pattern, path, re.IGNORECASE):
                score += delta  # delta is already negative

        # Shorter paths tend to be higher-level (more valuable as entry points)
        depth = path.count("/")
        if depth <= 2:
            score += 5
        elif depth >= 6:
            score -= 5

        return max(0, min(100, score))

    def is_doc_like(self, url: str) -> bool:
        """True if the URL looks like it leads to documentation content."""
        return self.score(url) >= 45

    def filter_and_rank(self, urls: list[str]) -> list[str]:
        """
        Given a list of URLs, return only allowed ones, sorted best-first.
        """
        allowed = [u for u in urls if self.is_allowed(u)]
        return sorted(allowed, key=self.score, reverse=True)

    def categorise(self, url: str) -> str:
        """
        Returns a human-readable category string for logging / debugging.
        """
        s = self.score(url)
        if s >= 80:
            return "excellent"
        if s >= 60:
            return "good"
        if s >= 45:
            return "ok"
        if s >= 20:
            return "low"
        return "skip"
