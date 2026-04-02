#!/usr/bin/env python3
import sys
sys.path.insert(0, '/Users/jonathan/elco/scrapee/backend')

from content_filter import ContentFilter

# Create a sample page with real content
sample_page = {
    "url": "https://example.com/docs",
    "title": "Python Documentation",
    "meta_description": "Learn Python",
    "paragraphs": [
        "Python is a high-level programming language. " * 3,
        "It supports multiple programming paradigms. " * 3,
        "Python is widely used in data science and machine learning. " * 3,
        "The language emphasizes code readability and simplicity. " * 3,
        "It has a comprehensive standard library. " * 3,
    ],
    "headings": [
        {"level": "h1", "text": "Python Guide"},
        {"level": "h2", "text": "Getting Started"},
        {"level": "h2", "text": "Advanced Topics"},
    ],
    "links_count": 15,
    "code_blocks": [
        {"snippet": "def hello():\n    print('Hello')", "language": "python"},
    ],
    "content": "<html>...</html>",
}

print("Testing ContentFilter with sample page...\n")

cf = ContentFilter()
result = cf.process(sample_page)

if result:
    print(f"✓ Page PASSED filter")
    print(f"  Quality Score: {result.get('quality_score')}")
    print(f"  URL: {result.get('url')}")
    print(f"  Title: {result.get('title')}")
    print(f"  Content length: {len(result.get('content', ''))}")
else:
    print(f"✗ Page was REJECTED by filter")
    
    # Run the scoring to see why
    url = sample_page['url']
    title = sample_page['title']
    paragraphs = sample_page['paragraphs']
    headings = sample_page['headings']
    code_blocks = sample_page['code_blocks']
    links_count = sample_page['links_count']
    meta = sample_page['meta_description']
    
    score = cf._quality_score(url, title, paragraphs, headings, code_blocks, links_count, meta)
    print(f"\n  Score calculation:")
    print(f"    Paragraphs: {len(paragraphs)}")
    print(f"    Headings: {len(headings)}")
    print(f"    Links: {links_count}")
    print(f"    Code blocks: {len(code_blocks)}")
    print(f"    Final score: {score}")
    print(f"    Min required: {cf.min_quality}")
    print(f"    Reason: Score {score} < Min {cf.min_quality}")
