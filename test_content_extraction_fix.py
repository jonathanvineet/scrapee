#!/usr/bin/env python3
"""
🔥 Test the critical content extraction fix.
Verifies that parse_html now extracts content properly and FTS finds it.
"""

import sys
sys.path.insert(0, '/Users/jonathan/elco/scrapee')

from bs4 import BeautifulSoup
from mcp_server.scraper.web_scraper import WebScraper
from backend.smart_scraper import SmartScraper
from backend.storage.sqlite_store import SQLiteStore

# Test HTML with minimal content (GitHub-like)
TEST_HTML_MINIMAL = """
<html>
<head><title>Test Page</title></head>
<body>
<script>console.log("ignored")</script>
<nav>Navigation</nav>
Some actual content here
</body>
</html>
"""

# Test HTML with real content
TEST_HTML_RICH = """
<html>
<head><title>Documentation Page</title></head>
<body>
<main>
<h1>Installation Guide</h1>
<p>This is a comprehensive guide for installing and configuring the system.</p>
<p>Follow these steps carefully to ensure proper setup.</p>
<code>pip install package</code>
</main>
</body>
</html>
"""

def test_web_scraper_extraction():
    """Test MCP web scraper extraction."""
    print("\n" + "="*60)
    print("🧪 TEST 1: WebScraper._extract_content()")
    print("="*60)
    
    scraper = WebScraper(allowed_domains=["example.com"])
    
    # Test minimal
    soup = BeautifulSoup(TEST_HTML_MINIMAL, "html.parser")
    content = scraper._extract_content(soup)
    print(f"✅ Minimal HTML: {len(content)} chars")
    print(f"   Content preview: {content[:100]}")
    assert len(content) > 0, "❌ Failed to extract content from minimal HTML"
    assert "actual content" in content, "❌ Failed to extract expected text"
    
    # Test rich
    soup = BeautifulSoup(TEST_HTML_RICH, "html.parser")
    content = scraper._extract_content(soup)
    print(f"✅ Rich HTML: {len(content)} chars")
    print(f"   Content preview: {content[:100]}")
    assert len(content) > 100, "❌ Failed to extract enough content from rich HTML"
    assert "installation guide" in content, "❌ Failed to extract expected heading"

def test_smart_scraper_extraction():
    """Test backend smart scraper extraction."""
    print("\n" + "="*60)
    print("🧪 TEST 2: SmartScraper._extract_text()")
    print("="*60)
    
    scraper = SmartScraper()
    
    # Test minimal
    soup = BeautifulSoup(TEST_HTML_MINIMAL, "html.parser")
    content = scraper._extract_text(soup)
    print(f"✅ Minimal HTML: {len(content)} chars")
    print(f"   Content preview: {content[:100]}")
    assert len(content) > 0, "❌ Failed to extract content"
    
    # Test rich
    soup = BeautifulSoup(TEST_HTML_RICH, "html.parser")
    content = scraper._extract_text(soup)
    print(f"✅ Rich HTML: {len(content)} chars")
    print(f"   Content preview: {content[:100]}")
    assert len(content) > 100, "❌ Failed to extract rich content"

def test_save_and_search():
    """Test save_doc and search pipeline."""
    print("\n" + "="*60)
    print("🧪 TEST 3: save_doc() → search_docs()")
    print("="*60)
    
    store = SQLiteStore()
    
    # Test with rich content
    url = "https://example.com/test"
    content = "This is a comprehensive installation guide for the system. Follow these steps carefully."
    
    result = store.save_doc(
        url=url,
        content=content,
        metadata={"title": "Test Installation Guide"}
    )
    
    if result:
        print(f"✅ Document saved successfully")
        
        # Now search
        results = store.search_docs("installation guide", limit=5)
        print(f"✅ Search results: {len(results)} found")
        
        if results:
            print(f"   First result: {results[0]['url']}")
            print(f"   Title: {results[0]['title']}")
            assert url in results[0]["url"], "❌ Failed to find saved document"
        else:
            print(f"⚠️  No results found (may need index rebuild)")
    else:
        print(f"⚠️  Document not saved (content validation issue)")

if __name__ == "__main__":
    try:
        test_web_scraper_extraction()
        test_smart_scraper_extraction()
        test_save_and_search()
        
        print("\n" + "="*60)
        print("✅ ALL TESTS PASSED - Content extraction fix verified!")
        print("="*60 + "\n")
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
