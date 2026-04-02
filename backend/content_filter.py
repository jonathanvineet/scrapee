"""
content_filter.py
-----------------
Universal content quality filter for scraped web pages.

Works on ANY website using structural and statistical signals only.
No domain-specific rules. No hardcoded site names.

Core idea
---------
Every webpage falls into one of three structural types:

  TYPE A — Real content pages (articles, docs, READMEs, blog posts)
      • Few links relative to prose length
      • Long paragraphs (avg > 40 words)
      • Headings that read like article sections
      • High text density

  TYPE B — Navigation / index pages (sitemaps, tag pages, category pages,
           profile pages, directory listings)
      • Many links, short paragraphs or none
      • Headings like "Navigation Menu", "Skip to content"
      • Low text density

  TYPE C — Marketing / conversion pages (pricing, landing, about)
      • Medium links, medium prose
      • Very short paragraphs (CTAs, bullets)
      • Keywords like "Get started", "Sign up free", "Join millions"

We score all three dimensions and reject B & C.

Input format
------------
The filter works on dicts that look like the raw output from your pipeline
crawler (the format in your payload JSON):

    {
        "url":              str,
        "title":            str,
        "meta_description": str,
        "paragraphs":       [str, ...],
        "headings":         [{"level": "h2", "text": "..."}, ...],
        "links":            [{"text": "...", "url": "..."}, ...],
        "links_count":      int,
        "images":           [...],
        "code_blocks":      [{"snippet": "...", "language": "..."}, ...],
    }

It also works on the simpler dict from SmartCrawler (no links/headings keys).
"""

from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Tuneable thresholds
# ---------------------------------------------------------------------------

# A page is rejected if its quality score is below this
MIN_QUALITY_SCORE: int = 20

# A page is rejected if its cleaned prose is shorter than this (characters)
MIN_PROSE_CHARS: int = 120

# Stored content is capped at this many characters (prevents huge pages)
MAX_CONTENT_CHARS: int = 50_000

# In API responses, sample_docs snippets are trimmed to this
SNIPPET_CHARS: int = 350

# If links_count / paragraph_count exceeds this, the page is nav-heavy
LINK_TO_PARA_RATIO_LIMIT: float = 8.0

# If average paragraph word count is below this, the page is likely marketing
MIN_AVG_PARA_WORDS: float = 12.0

# ---------------------------------------------------------------------------
# Universal boilerplate heading patterns
# Applies to ALL websites — these headings are never real content.
# ---------------------------------------------------------------------------

_BOILERPLATE_HEADING_RE = re.compile(
    r"""
    ^ (
        navigation(\s+menu)?        |
        main\s+navigation           |
        skip\s+(to\s+)?(content|main) |
        table\s+of\s+contents?      |
        breadcrumb(s)?              |
        site\s+(map|menu|nav(igation)?) |
        (top|primary|secondary|global|main|mobile)\s+(menu|nav(igation)?) |
        menu                        |
        search(\s+results?)?        |
        (back\s+to\s+)?top          |
        in\s+this\s+(page|article|section|document) |
        on\s+this\s+page            |
        page\s+contents?            |
        related\s+(articles?|posts?|links?|content) |
        you\s+might\s+also\s+like   |
        see\s+also                  |
        further\s+reading           |
        external\s+links?           |
        footnotes?                  |
        references?                 |
        (social\s+)?(share|sharing) |
        provide\s+feedback          |
        leave\s+a\s+(comment|reply) |
        comments?\s*(section)?      |
        tags?                       |
        categories                  |
        filed\s+under               |
        topics?                     |
        footer                      |
        header                      |
        sidebar                     |
        advertisement               |
        sponsored(\s+content)?      |
        cookie(\s+(notice|banner|consent))? |
        privacy\s+(notice|banner)   |
        uh\s+oh[!.]?                |    # GitHub-style empty state
        (block\s+or\s+report\s+)    |
        achievements?               |
        highlights?                 |
        saved\s+searches            |
        use\s+saved\s+searches
    ) $
    """,
    re.VERBOSE | re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Universal boilerplate paragraph patterns
# Short snippets that appear on almost every site and carry zero information.
# ---------------------------------------------------------------------------

_BOILERPLATE_PARA_RE = re.compile(
    r"""
    (
        we\s+use\s+cookies?                     |
        (accept|decline)\s+(all\s+)?cookies?    |
        cookie\s+(policy|settings?|preferences) |
        by\s+(using|continuing|browsing)\s+(to\s+use\s+)?this\s+site |
        your\s+privacy\s+(choices?|settings?)   |
        subscribe\s+to\s+(our\s+)?(newsletter|mailing) |
        sign\s+up\s+(for\s+)?(\w+\s+)?updates  |
        get\s+(our\s+)?(latest\s+)?(news|updates|tips)\s+(in\s+your\s+)?inbox |
        (all\s+)?rights?\s+reserved             |
        copyright\s*©?\s*\d{4}                  |
        ©\s*\d{4}                               |
        terms\s+(of\s+)?(service|use)           |
        privacy\s+policy                        |
        made\s+with\s+❤                         |
        powered\s+by\s+\w+                      |
        (click|tap)\s+here\s+to                 |
        (read|learn)\s+more\s*\.?$              |
        ^(yes|no)[,.]?\s*i\s+(agree|accept|understand) |
        we\s+read\s+every\s+piece\s+of\s+feedback |
        to\s+see\s+all\s+available\s+qualifiers |
        join\s+(millions?|thousands?)\s+of      |
        start\s+(your\s+)?(free\s+)?(trial|journey|today) |
        get\s+started\s+(for\s+free\s*)?today   |
        no\s+credit\s+card\s+required           |
        cancel\s+any\s+time                     |
        \d+[\-–]\s*minute\s+read
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Marketing / conversion page detection
# If a page's paragraphs heavily match these, it's a CTA/landing page.
# ---------------------------------------------------------------------------

_MARKETING_CTA_RE = re.compile(
    r"""
    \b (
        sign\s+up(\s+free)?         |
        get\s+started               |
        try\s+for\s+free            |
        free\s+trial                |
        request\s+a?\s+demo         |
        contact\s+(sales|us)        |
        talk\s+to\s+(sales|an?\s+expert) |
        schedule\s+a\s+(call|demo)  |
        learn\s+more                |
        see\s+(pricing|plans)       |
        join\s+(now|today|free)     |
        get\s+access                |
        start\s+building            |
        book\s+a\s+demo
    ) \b
    """,
    re.VERBOSE | re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Content-positive patterns (presence boosts quality score)
# ---------------------------------------------------------------------------

_CODE_FENCE_RE = re.compile(r"```|~~~|\$\s+\w|>>>\s+\w", re.M)
_TECHNICAL_TERM_RE = re.compile(
    r"\b(function|class|import|require|const|let|var|def|return|async|await|"
    r"interface|struct|module|package|namespace|=>|->|:=|stdout|stderr)\b"
)
_STRUCTURED_LIST_RE = re.compile(r"^\s*[-*•]\s+\w", re.M)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ContentFilter:
    """
    Scores and cleans scraped pages for any website.

    Usage
    -----
        cf = ContentFilter()
        doc = cf.process(raw_page_dict)
        if doc:                          # None = rejected
            store.save_doc(**doc)
    """

    def __init__(
        self,
        min_quality: int = MIN_QUALITY_SCORE,
        min_chars: int = MIN_PROSE_CHARS,
    ) -> None:
        self.min_quality = min_quality
        self.min_chars = min_chars

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def process(self, raw: dict) -> Optional[dict]:
        """
        Clean and quality-check a raw scraped page.

        Returns a clean dict with keys: url, title, content, code_blocks, quality_score
        Returns None if the page should be discarded.
        """
        url   = (raw.get("url") or "").strip()
        title = (raw.get("title") or "").strip()

        if not url:
            return None

        # ── Extract and clean each field ──────────────────────────────
        paragraphs  = self._clean_paragraphs(raw.get("paragraphs") or [])
        headings    = self._clean_headings(raw.get("headings") or [])
        code_blocks = self._clean_code_blocks(raw.get("code_blocks") or [])
        meta        = (raw.get("meta_description") or "").strip()

        # Raw link/image arrays are intentionally DISCARDED here —
        # they are navigation infrastructure, not content.
        links_count = int(raw.get("links_count") or len(raw.get("links") or []))

        # ── Content quality gate ──────────────────────────────────────
        score = self._quality_score(
            url         = url,
            title       = title,
            paragraphs  = paragraphs,
            headings    = headings,
            code_blocks = code_blocks,
            links_count = links_count,
            meta        = meta,
        )

        if score < self.min_quality:
            return None

        # ── Build clean prose content ─────────────────────────────────
        content = self._build_content(meta, headings, paragraphs, code_blocks)

        if len(content) < self.min_chars:
            return None

        return {
            "url":           url,
            "title":         title or url,
            "content":       content[:MAX_CONTENT_CHARS],
            "code_blocks":   code_blocks,
            "quality_score": score,
        }

    def process_batch(self, pages: list[dict]) -> list[dict]:
        """Filter and clean a batch. Returns only passing docs, best-first."""
        results = []
        rejected = 0
        for page in pages:
            doc = self.process(page)
            if doc:
                results.append(doc)
            else:
                rejected += 1

        # Sort best-quality docs first (for sample_docs ordering)
        results.sort(key=lambda d: d["quality_score"], reverse=True)

        if rejected:
            import logging
            logging.getLogger(__name__).info(
                "ContentFilter: %d/%d pages passed (rejected %d low-quality)",
                len(results), len(pages), rejected,
            )
        return results

    def make_sample(self, doc: dict) -> dict:
        """Compact representation for API responses — no full content."""
        content = doc.get("content", "")
        if len(content) > SNIPPET_CHARS:
            snippet = content[:SNIPPET_CHARS].rsplit(" ", 1)[0] + "…"
        else:
            snippet = content
        return {
            "title":         doc.get("title", ""),
            "url":           doc.get("url", ""),
            "snippet":       snippet,
            "quality_score": doc.get("quality_score", 0),
        }

    # ------------------------------------------------------------------
    # Private — cleaning
    # ------------------------------------------------------------------

    def _clean_paragraphs(self, raw: list) -> list[str]:
        """Remove boilerplate and trivially short paragraphs."""
        result = []
        for item in raw:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
            else:
                text = str(item)
            text = text.strip()
            if len(text) < 15:
                continue
            if _BOILERPLATE_PARA_RE.search(text):
                continue
            result.append(text)
        return result

    def _clean_headings(self, raw: list) -> list[str]:
        """Extract heading text, strip navigation boilerplate."""
        result = []
        for item in raw:
            text = (item.get("text") if isinstance(item, dict) else str(item)).strip()
            if not text or len(text) < 2:
                continue
            if _BOILERPLATE_HEADING_RE.match(text):
                continue
            # Reject suspiciously long headings — they're usually nav items run together
            if len(text) > 120:
                continue
            # Reject headings that are just a URL
            if text.startswith(("http://", "https://", "www.")):
                continue
            result.append(text)
        return result

    def _clean_code_blocks(self, raw: list) -> list[dict]:
        """Keep only non-trivial code blocks."""
        result = []
        for block in raw:
            if not isinstance(block, dict):
                continue
            snippet = (block.get("snippet") or "").strip()
            if len(snippet) < 10:
                continue
            result.append({
                "snippet":  snippet[:5_000],
                "language": (block.get("language") or "").lower(),
                "context":  (block.get("context") or "")[:300],
            })
        return result

    # ------------------------------------------------------------------
    # Private — quality scoring
    # ------------------------------------------------------------------

    def _quality_score(
        self,
        url: str,
        title: str,
        paragraphs: list[str],
        headings: list[str],
        code_blocks: list[dict],
        links_count: int,
        meta: str,
    ) -> int:
        """
        Score 0–100 using purely structural / statistical signals.
        No domain knowledge required.
        """
        score = 0
        url_lower   = url.lower()
        title_lower = title.lower()

        # ────────────────────────────────────────────────────────────────
        # 1. LINK DENSITY  (the most reliable nav-page detector)
        #
        #    A page with 135 links and 11 paragraphs is a nav page.
        #    A page with 8 links and 20 paragraphs is content.
        # ────────────────────────────────────────────────────────────────
        n_para = max(len(paragraphs), 1)
        ratio  = links_count / n_para

        if ratio > LINK_TO_PARA_RATIO_LIMIT:
            # Hard cap: very nav-heavy pages can't score above 20
            return min(20, score)

        if ratio < 1.0:
            score += 15    # very content-dense
        elif ratio < 3.0:
            score += 10
        elif ratio < 6.0:
            score += 4
        # ratio >= 6 → no bonus, approaching the cap above

        # ────────────────────────────────────────────────────────────────
        # 2. PARAGRAPH DEPTH & QUALITY
        # ────────────────────────────────────────────────────────────────
        if n_para >= 20:
            score += 25
        elif n_para >= 10:
            score += 18
        elif n_para >= 5:
            score += 10
        elif n_para >= 2:
            score += 5

        # Average paragraph word count
        if paragraphs:
            avg_words = sum(len(p.split()) for p in paragraphs) / len(paragraphs)
            if avg_words >= 40:
                score += 15   # long paragraphs = real article
            elif avg_words >= 20:
                score += 8
            elif avg_words < MIN_AVG_PARA_WORDS:
                score -= 10   # very short = bullets / CTAs

        # Total prose volume
        total_chars = sum(len(p) for p in paragraphs)
        if total_chars >= 3000:
            score += 15
        elif total_chars >= 1000:
            score += 8
        elif total_chars >= 300:
            score += 3

        # ────────────────────────────────────────────────────────────────
        # 3. HEADING QUALITY
        #    After boilerplate removal, are there real section headings?
        # ────────────────────────────────────────────────────────────────
        if len(headings) >= 3:
            score += 10
        elif len(headings) >= 1:
            score += 4

        # ────────────────────────────────────────────────────────────────
        # 4. CODE BLOCKS  (strong signal for developer documentation)
        # ────────────────────────────────────────────────────────────────
        if code_blocks:
            score += min(len(code_blocks) * 6, 20)

        # Inline code fences in paragraph text
        all_para_text = " ".join(paragraphs)
        if _CODE_FENCE_RE.search(all_para_text):
            score += 8
        if _TECHNICAL_TERM_RE.search(all_para_text):
            score += 5

        # ────────────────────────────────────────────────────────────────
        # 5. MARKETING CTA DENSITY  (landing-page detection)
        #    Count how many CTA phrases appear in paragraphs.
        # ────────────────────────────────────────────────────────────────
        cta_count = sum(
            1 for p in paragraphs if _MARKETING_CTA_RE.search(p)
        )
        cta_ratio = cta_count / n_para
        if cta_ratio > 0.5:
            score -= 20    # majority of paragraphs are CTAs
        elif cta_ratio > 0.25:
            score -= 8

        # ────────────────────────────────────────────────────────────────
        # 6. URL SHAPE  (structural signals, no site names)
        # ────────────────────────────────────────────────────────────────
        doc_url_keywords = re.compile(
            r"\b(docs?|documentation|manual|wiki|handbook|guide|tutorial|"
            r"reference|api|howto|faq|learn|kb|knowledge.?base|readme|"
            r"getting.?started|quickstart|introduction|overview|example|"
            r"sample|changelog|migration|install|setup|config|architecture|"
            r"concepts?|internals?|blog|article|post)\b",
            re.I,
        )
        if doc_url_keywords.search(url_lower):
            score += 12

        # Shallow paths tend to be hub pages (not leaf content)
        depth = len([s for s in url_lower.split("/") if s]) - 2  # minus scheme+host
        if depth >= 2:
            score += 5    # leaf page is likely real content
        elif depth == 1:
            score += 2    # one level deep
        # depth == 0 (root): no bonus

        # ────────────────────────────────────────────────────────────────
        # 7. TITLE SIGNALS
        # ────────────────────────────────────────────────────────────────
        doc_title_keywords = re.compile(
            r"\b(guide|tutorial|how\s+to|howto|reference|api\s+docs?|"
            r"documentation|readme|changelog|introduction|overview|"
            r"getting\s+started|quickstart|installation|configuration|"
            r"architecture|concepts?|examples?|cookbook|faq|"
            r"troubleshoot|deep\s+dive)\b",
            re.I,
        )
        if doc_title_keywords.search(title_lower):
            score += 10

        # Very short title (1–2 words) = probably a nav/landing page
        if 1 <= len(title.split()) <= 2:
            score -= 5

        # ────────────────────────────────────────────────────────────────
        # 8. META DESCRIPTION  (adds to evidence of real content)
        # ────────────────────────────────────────────────────────────────
        if meta and len(meta) > 50:
            score += 4

        return max(0, min(100, score))

    # ------------------------------------------------------------------
    # Private — content assembly
    # ------------------------------------------------------------------

    def _build_content(
        self,
        meta: str,
        headings: list[str],
        paragraphs: list[str],
        code_blocks: list[dict],
    ) -> str:
        """Assemble cleaned prose into a single searchable string."""
        parts: list[str] = []

        if meta and len(meta) > 30:
            parts.append(meta)

        # Interleave headings and paragraphs in document order.
        # Since we don't track order from the raw dict, headings come first
        # (they're typically fewer) then paragraphs.
        for h in headings[:30]:
            parts.append(f"## {h}")

        parts.extend(paragraphs[:200])

        # Append code snippets for full-text searchability
        for block in code_blocks[:30]:
            snippet = block.get("snippet", "")
            lang    = block.get("language", "")
            if snippet:
                parts.append(f"```{lang}\n{snippet}\n```")

        return "\n\n".join(parts)
