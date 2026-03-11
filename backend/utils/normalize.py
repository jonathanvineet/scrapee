"""
Utility functions for MCP server
"""
from urllib.parse import urlparse, urldefrag


def normalize_url(url: str) -> str:
    """
    Normalize URL by removing trailing slashes and fragments.
    
    Args:
        url: Input URL
    
    Returns:
        Normalized URL
    
    Example:
        'https://example.com/page/' -> 'https://example.com/page'
    """
    if not url:
        return url
    
    # Remove fragment
    url, _ = urldefrag(url)
    
    # Parse URL
    parsed = urlparse(url)
    
    # Reconstruct URL without trailing slash on path
    normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
    
    if parsed.query:
        normalized += f"?{parsed.query}"
    
    return normalized


def extract_domain(url: str) -> str:
    """
    Extract domain from URL.
    
    Args:
        url: Input URL
    
    Returns:
        Domain name
    
    Example:
        'https://docs.python.org/3/tutorial/' -> 'docs.python.org'
    """
    parsed = urlparse(url)
    return parsed.netloc


def truncate_text(text: str, max_length: int = 1500, suffix: str = "...") -> str:
    """
    Truncate text to maximum length with suffix.
    
    Args:
        text: Input text
        max_length: Maximum length
        suffix: Suffix to append if truncated
    
    Returns:
        Truncated text
    """
    if len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix


def format_doc_for_context(url: str, content: str, max_length: int = 2000) -> str:
    """
    Format document for LLM context.
    
    Args:
        url: Document URL
        content: Document content
        max_length: Maximum content length
    
    Returns:
        Formatted string
    """
    truncated = truncate_text(content, max_length)
    return f"=== {url} ===\n{truncated}\n"
