#!/usr/bin/env python3
import sys
sys.path.insert(0, '/Users/jonathan/elco/scrapee/backend')

from content_filter import ContentFilter
from bs4 import BeautifulSoup

# Simulate what the crawler returns
html = """
<html>
<head>
<title>Python asyncio Documentation</title>
<meta name="description" content="Learn about Python asyncio">
</head>
<body>
<h1>asyncio — Asynchronous I/O</h1>
<p>asyncio is a library to write concurrent code using the async/await syntax. This module provides infrastructure for writing single-threaded concurrent code using coroutines, multiplexing I/O access over sockets and other resources, running network clients and servers, and other related primitives.</p>
<p>Here is a Table of Contents listing the asyncio API:</p>
<a href="#">Link 1</a>
<a href="#">Link 2</a>
<a href="#">Link 3</a>
<p>asyncio has multiple layers. The high-level API (used by most Python developers) consists of tasks, events, and some utility functions.</p>
<p>The low-level API is built around a low-level event loop. The event loop infrastructure and protocols are available for library developers.</p>
<h2>High-level API Index</h2>
<p>Run an asyncio Program</p>
<p>Coroutines and Tasks</p>
<h2>Streams</h2>
<p>The asyncio streams API provides high-level async/await-ready primitives to work with network connections.</p>
<code>async def main():</code>
<pre><code>import asyncio

async def hello():
    print("Hello")
    
asyncio.run(hello())</code></pre>
</body>
</html>
"""

# Extract data like the crawler does
soup = BeautifulSoup(html, "html.parser")

title = ""
title_tag = soup.find("title")
if title_tag:
    title = title_tag.get_text().strip()

meta_desc = ""
meta_tag = soup.find("meta", attrs={"name": "description"})
if meta_tag and meta_tag.get("content"):
    meta_desc = meta_tag.get("content").strip()

paragraphs = []
for p in soup.find_all("p"):
    text = p.get_text().strip()
    if len(text) > 20:
        paragraphs.append(text)

headings = []
for heading in soup.find_all(["h1", "h2", "h3", "h4"]):
    text = heading.get_text().strip()
    if len(text) > 0:
        headings.append({
            "level": heading.name,
            "text": text
        })

links_count = len(soup.find_all("a", href=True))

code_blocks = []
for code in soup.find_all(["code", "pre"]):
    snippet = code.get_text().strip()
    if len(snippet) > 0:
        code_blocks.append({
            "snippet": snippet[:500],
            "language": ""
        })

# Create the page dict like crawler does
page_dict = {
    "url": "https://docs.python.org/3/library/asyncio.html",
    "title": title,
    "content": html,
    "meta_description": meta_desc,
    "paragraphs": paragraphs,
    "headings": headings,
    "links_count": links_count,
    "code_blocks": code_blocks,
}

print("Extracted data from HTML:")
print(f"  Title: {page_dict['title']}")
print(f"  Paragraphs: {len(page_dict['paragraphs'])}")
print(f"  Headings: {len(page_dict['headings'])}")
print(f"  Links: {page_dict['links_count']}")
print(f"  Code blocks: {len(page_dict['code_blocks'])}")
print()

# Test ContentFilter
cf = ContentFilter()
result = cf.process(page_dict)

if result:
    print(f"✓ Page PASSED filter!")
    print(f"  Score: {result['quality_score']}")
else:
    print(f"✗ Page was REJECTED by filter!")
    
    # Debug the score
    url = page_dict['url']
    title = page_dict['title']
    paragraphs = page_dict['paragraphs']
    headings = page_dict['headings']
    code_blocks = page_dict['code_blocks']
    links_count = page_dict['links_count']
    meta = page_dict['meta_description']
    
    # Clean them like the filter does
    paragraphs = cf._clean_paragraphs(paragraphs)
    headings = cf._clean_headings(headings)
    code_blocks = cf._clean_code_blocks(code_blocks)
    
    score = cf._quality_score(url, title, paragraphs, headings, code_blocks, links_count, meta)
    
    print(f"\n  Debug info:")
    print(f"    After cleaning:")
    print(f"      Paragraphs: {len(paragraphs)}")
    print(f"      Headings: {len(headings)}")
    print(f"      Code blocks: {len(code_blocks)}")
    print(f"    Quality score: {score}")
    print(f"    Min required: {cf.min_quality}")
    print(f"    Prose length: {sum(len(p) for p in paragraphs)} chars")
    print(f"    Min prose: {cf.min_chars}")
