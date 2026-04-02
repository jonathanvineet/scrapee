#!/usr/bin/env python3
import sys
sys.path.insert(0, '/Users/jonathan/elco/scrapee/backend')

from smart_crawler import _extract_prose, _extract_paragraphs, _extract_headings
from bs4 import BeautifulSoup
import requests

# Fetch a real page
url = "https://docs.python.org/3/library/asyncio.html"
print(f"Fetching {url}...\n")

try:
    resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    
    # Extract data
    prose = _extract_prose(soup)
    paragraphs = _extract_paragraphs(soup)
    headings = _extract_headings(soup)
    
    print(f"Extracted data:")
    print(f"  Prose length: {len(prose)} chars")
    print(f"  Paragraphs: {len(paragraphs)}")
    print(f"  Headings: {len(headings)}")
    
    if prose:
        print(f"\n  First 200 chars of prose:")
        print(f"  {prose[:200]}...")
    else:
        print(f"\n  ✗ Prose is EMPTY!")
        print(f"  This is why the crawler returns 0 documents!")
        
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
