#!/usr/bin/env python3
"""End-to-end test: scrape → index → search"""
import sys
import json
sys.path.insert(0, '/Users/jonathan/elco/scrapee/backend')

from mcp import mcp_server

print("=" * 60)
print("STEP 1: Scrape Expo authentication page")
print("=" * 60)

scrape_res = mcp_server._tool_scrape_url({
    'url': 'https://docs.expo.dev/develop/authentication',
    'mode': 'smart',
    'max_depth': 0
})

stored = scrape_res.get('stored_urls', [])
print(f"✓ Scraped & stored {len(stored)} page(s)")
for url in stored:
    print(f"  - {url}")

print("\n" + "=" * 60)
print("STEP 2: Get document & check code_blocks extracted")
print("=" * 60)

get_res = mcp_server._tool_get_doc({
    'url': 'https://docs.expo.dev/develop/authentication'
})

code_blocks = get_res.get('code_blocks', [])
print(f"✓ Code blocks in document: {len(code_blocks)}")

if code_blocks:
    print("\nFirst 3 code blocks:")
    for i, block in enumerate(code_blocks[:3], 1):
        snippet = block.get('snippet', '')[:80]
        lang = block.get('language', 'unknown')
        context = block.get('context', '')[:60]
        print(f"\n  [{i}] Language: {lang}")
        print(f"      Context: {context}...")
        print(f"      Snippet: {snippet}...")
else:
    print("❌ NO CODE BLOCKS EXTRACTED - THIS IS THE BUG")

print("\n" + "=" * 60)
print("STEP 3: Search for code blocks")
print("=" * 60)

search_res = mcp_server._tool_search_code({
    'query': 'authenticate login user',
    'limit': 5
})

results = search_res.get('results', [])
print(f"✓ Search found {len(results)} code blocks")

if results:
    for i, code in enumerate(results[:2], 1):
        print(f"\n  [{i}] Language: {code.get('language')}")
        print(f"      URL: {code.get('url')}")
        print(f"      Snippet: {code.get('snippet')[:100]}...")

print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"Pages scraped: {len(stored)}")
print(f"Code blocks indexed: {len(code_blocks)}")
print(f"Searchable code blocks: {len(results)}")

if len(code_blocks) > 0:
    print("\n✅ SUCCESS: Code extraction pipeline working!")
else:
    print("\n❌ FAILED: Code blocks not being stored")
