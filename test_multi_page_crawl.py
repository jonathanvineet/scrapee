#!/usr/bin/env python3
"""Test: Scrape root URL, discover & store all pages, search across them"""
import sys
sys.path.insert(0, '/Users/jonathan/elco/scrapee/backend')

from mcp import mcp_server

print("=" * 70)
print("TEST: Give root URL, crawl & store ALL pages, search across all")
print("=" * 70)

print("\n[1] Scraping https://docs.expo.dev/ (will discover & crawl child pages)")
print("    max_depth=2 allows following links to related documentation")

scrape_res = mcp_server._tool_scrape_url({
    'url': 'https://docs.expo.dev/',
    'mode': 'smart',
    'max_depth': 2  # Now default - crawls multiple levels
})

stored_urls = scrape_res.get('stored_urls', [])
error = scrape_res.get('error')

print(f"\n[RESULT] Scraped {len(stored_urls)} pages")
if error:
    print(f"⚠ Error: {error}")
    
if stored_urls:
    print("\nPages stored:")
    for i, url in enumerate(stored_urls[:10], 1):
        print(f"  {i}. {url}")
    if len(stored_urls) > 10:
        print(f"  ... and {len(stored_urls) - 10} more")

print("\n" + "=" * 70)
print("[2] Now searching across ALL stored pages")
print("=" * 70)

search_res = mcp_server._tool_search_and_get({
    'query': 'authentication setup login oauth',
    'limit': 5
})

results = search_res.get('results', [])
print(f"\nFound {len(results)} relevant docs across all {len(stored_urls)} pages:")

for i, result in enumerate(results[:3], 1):
    url = result.get('url', '')
    content = result.get('content', '')[:150]
    print(f"\n[{i}] {url}")
    print(f"    {content}...")

print("\n" + "=" * 70)
print("[3] Search for code examples across all pages")
print("=" * 70)

code_res = mcp_server._tool_search_code({
    'query': 'authentication login expo',
    'limit': 5
})

code_results = code_res.get('results', [])
print(f"\nFound {len(code_results)} code blocks across stored pages:")

for i, code in enumerate(code_results[:2], 1):
    url = code.get('url', '')
    lang = code.get('language', 'unknown')
    snippet = code.get('snippet', '')[:100]
    print(f"\n[{i}] {url}")
    print(f"    Language: {lang}")
    print(f"    Code: {snippet}...")

print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print(f"✅ Stored {len(stored_urls)} pages from root URL")
print(f"✅ Found {len(results)} docs matching search query")
print(f"✅ Found {len(code_results)} code blocks to return to agent")
print("\n✨ Complete! Agent can now query across ALL pages at once")
