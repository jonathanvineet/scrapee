"""
Enhanced Smart Scraper for Production MCP
Extracts structured content including code blocks, topics, and metadata.
"""
import re
from typing import Dict, List, Optional, Tuple
from bs4 import BeautifulSoup, NavigableString
from urllib.parse import urlparse


class SmartScraper:
    """
    Production-grade scraper that extracts structured content.
    
    Features:
    - Code block extraction with language detection
    - Topic/heading hierarchy extraction
    - Metadata extraction (title, description, language)
    - Context extraction for code blocks
    """
    
    # Language detection patterns
    LANGUAGE_PATTERNS = {
        'python': [r'\bdef\b', r'\bimport\b', r'\bclass\b', r'\.py\b'],
        'javascript': [r'\bfunction\b', r'\bconst\b', r'\blet\b', r'=>', r'\.js\b'],
        'typescript': [r':\s*\w+', r'\binterface\b', r'\btype\b', r'\.ts\b'],
        'java': [r'\bpublic\s+class\b', r'\bprivate\b', r'\bpackage\b', r'\.java\b'],
        'rust': [r'\bfn\b', r'\blet\s+mut\b', r'\bimpl\b', r'\.rs\b'],
        'go': [r'\bfunc\b', r'\bpackage\b', r':=', r'\.go\b'],
        'solidity': [r'\bcontract\b', r'\bpragma\b', r'\bsolidity\b', r'\.sol\b'],
        'bash': [r'#!/bin/bash', r'\becho\b', r'\$\{', r'\.sh\b'],
        'sql': [r'\bSELECT\b', r'\bFROM\b', r'\bWHERE\b', r'\bJOIN\b'],
        'html': [r'<html', r'<div', r'<body', r'\.html\b'],
        'css': [r'\{[^}]*:[^}]*\}', r'\.css\b'],
        'json': [r'^\s*\{', r':\s*["\[]', r'\.json\b'],
        'yaml': [r'^\s*\w+:', r'\.yml\b', r'\.yaml\b'],
        'docker': [r'\bFROM\b', r'\bRUN\b', r'\bCOPY\b', r'Dockerfile'],
    }

    MAX_CONTENT_LENGTH = 100000
    MAX_CODE_BLOCKS = 200
    MAX_TOPICS = 200
    
    def __init__(self):
        """Initialize scraper."""
        pass
    
    def parse_html(self, html: str, url: str) -> Dict:
        """
        Parse HTML and extract structured content.
        
        Args:
            html: HTML content
            url: Source URL
        
        Returns:
            Dict with content, code_blocks, topics, metadata
        """
        soup = BeautifulSoup(html or '', 'html.parser')
        
        # Remove unwanted elements
        for element in soup(['script', 'style', 'nav', 'footer', 'header', 'iframe']):
            element.decompose()
        
        # Extract metadata
        metadata = self._extract_metadata(soup, url)
        
        # Extract code blocks with context
        code_blocks = self._extract_code_blocks(soup, url)
        
        # Extract topics/headings structure
        topics = self._extract_topics(soup)
        
        # Extract clean text content
        content = self._extract_text(soup)
        
        return {
            "content": content,
            "code_blocks": code_blocks,
            "topics": topics,
            "metadata": metadata
        }
    
    def _extract_metadata(self, soup: BeautifulSoup, url: str) -> Dict:
        """Extract page metadata."""
        metadata = {
            "url": url,
            "domain": urlparse(url).netloc
        }
        
        # Title
        title_tag = soup.find('title')
        if title_tag:
            metadata["title"] = title_tag.get_text(strip=True)
        
        # Meta description
        desc_tag = soup.find('meta', attrs={'name': 'description'})
        if desc_tag and desc_tag.get('content'):
            metadata["description"] = desc_tag['content']
        
        # Open Graph data
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            metadata["og_title"] = og_title['content']
            metadata.setdefault("title", og_title['content'])
        
        og_desc = soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            metadata["og_description"] = og_desc['content']
            metadata.setdefault("description", og_desc['content'])
        
        # Language
        html_tag = soup.find('html')
        if html_tag and html_tag.get('lang'):
            metadata["language"] = html_tag['lang']
        
        if not metadata.get("title"):
            first_heading = soup.find(['h1', 'h2'])
            if first_heading:
                metadata["title"] = first_heading.get_text(strip=True)

        return metadata
    
    def _extract_code_blocks(self, soup: BeautifulSoup, url: str) -> List[Dict]:
        """
        Extract code blocks with language and context.
        
        Returns:
            List of dicts with snippet, language, context
        """
        code_blocks = []
        seen = set()
        
        # Find all code elements
        code_elements = soup.find_all(['code', 'pre'])
        
        for idx, element in enumerate(code_elements[:self.MAX_CODE_BLOCKS]):
            # Get code text
            code_text = element.get_text()
            
            # Skip empty or very short snippets
            if not code_text or len(code_text.strip()) < 10:
                continue
            
            # Detect language
            language = self._normalize_language(self._detect_language(element, code_text))
            
            # Extract context (surrounding text)
            context = self._extract_context(element)
            
            snippet = code_text.strip()
            fingerprint = (snippet, language, context)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)

            code_blocks.append({
                "snippet": snippet[:5000],
                "language": language,
                "context": context[:400],
                "line_number": idx + 1
            })
        
        return code_blocks
    
    def _detect_language(self, element, code_text: str) -> str:
        """
        Detect programming language from code block.
        
        Args:
            element: BeautifulSoup element
            code_text: Code content
        
        Returns:
            Language name or 'unknown'
        """
        # Check class attributes first (most reliable)
        classes = element.get('class', [])
        for cls in classes:
            cls_lower = str(cls).lower()
            # Common patterns: language-python, lang-js, highlight-rust
            if 'language-' in cls_lower:
                return cls_lower.split('language-')[1].split()[0]
            if 'lang-' in cls_lower:
                return cls_lower.split('lang-')[1].split()[0]
            if cls_lower in self.LANGUAGE_PATTERNS:
                return cls_lower
        
        # Check data attributes
        data_lang = element.get('data-language') or element.get('data-lang')
        if data_lang:
            return str(data_lang).lower()
        
        # Pattern matching on content
        scores = {}
        for lang, patterns in self.LANGUAGE_PATTERNS.items():
            score = 0
            for pattern in patterns:
                if re.search(pattern, code_text, re.IGNORECASE | re.MULTILINE):
                    score += 1
            if score > 0:
                scores[lang] = score
        
        if scores:
            return max(scores.items(), key=lambda x: x[1])[0]
        
        return "unknown"

    def _normalize_language(self, language: str) -> str:
        aliases = {
            'js': 'javascript',
            'ts': 'typescript',
            'py': 'python',
            'shell': 'bash',
            'sh': 'bash',
            'yml': 'yaml',
        }
        value = (language or 'unknown').strip().lower()
        return aliases.get(value, value or 'unknown')
    
    def _extract_context(self, element, max_chars: int = 200) -> str:
        """
        Extract surrounding context for a code block.
        
        Args:
            element: Code element
            max_chars: Maximum context length
        
        Returns:
            Context string
        """
        context_parts = []
        
        # Get previous sibling text
        prev = element.find_previous(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li'])
        if prev:
            text = prev.get_text(strip=True)
            if text and len(text) < max_chars:
                context_parts.append(text)
        
        # Get parent heading
        parent = element.find_parent(['section', 'div', 'article'])
        if parent:
            heading = parent.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
            if heading:
                heading_text = heading.get_text(strip=True)
                if heading_text and heading_text not in context_parts:
                    context_parts.insert(0, heading_text)
        
        context = " | ".join(context_parts)
        return context[:max_chars] if context else ""
    
    def _extract_topics(self, soup: BeautifulSoup) -> List[Dict]:
        """
        Extract document structure (headings/topics).
        
        Returns:
            List of dicts with topic, heading, level, content
        """
        topics = []
        seen = set()
        
        # Find all headings
        headings = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
        
        for heading in headings[:self.MAX_TOPICS]:
            level = int(heading.name[1])  # h1 -> 1, h2 -> 2, etc.
            heading_text = heading.get_text(strip=True)
            
            if not heading_text:
                continue
            
            # Extract content under this heading (until next heading)
            content_parts = []
            for sibling in heading.find_next_siblings():
                if sibling.name and sibling.name.startswith('h'):
                    # Stop at next heading
                    break
                if sibling.name in ['p', 'li', 'div']:
                    text = sibling.get_text(strip=True)
                    if text:
                        content_parts.append(text)
            
            content = " ".join(content_parts[:5])  # Limit to first 5 paragraphs
            
            # Generate topic slug
            topic = re.sub(r'[^a-z0-9]+', '-', heading_text.lower()).strip('-')
            
            fingerprint = (topic, heading_text)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)

            topics.append({
                "topic": topic,
                "heading": heading_text,
                "level": level,
                "content": content[:500]  # Limit content length
            })
        
        return topics
    
    def _extract_text(self, soup: BeautifulSoup) -> str:
        """
        Extract clean text content.
        
        Returns:
            Cleaned text
        """
        # Get text with separators
        text = soup.get_text(separator='\n', strip=True)
        
        # Clean up extra whitespace
        text = re.sub(r'\n\s*\n+', '\n\n', text)
        text = re.sub(r' +', ' ', text)
        
        return text.strip()[:self.MAX_CONTENT_LENGTH]


# Factory function
def create_scraper() -> SmartScraper:
    """Create scraper instance."""
    return SmartScraper()
