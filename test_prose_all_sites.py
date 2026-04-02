#!/usr/bin/env python3
"""Debug prose extraction to understand what's working and what's not."""
import sys
sys.path.insert(0, '/Users/jonathan/elco/scrapee/backend')

from bs4 import BeautifulSoup
import requests
import re

# Test multiple sites
test_urls = [
    "https://docs.python.org/3/library/asyncio.html",
    "https://realpython.com/async-io-python/",
    "https://nodejs.org/en/docs/",
]

_NOISE_TAGS = {"script", "style", "nav", "footer", "header", "aside",
               "form", "noscript", "iframe", "svg", "button", "input"}

_PROSE_TAGS = {"p", "li", "td", "dd", "blockquote", "article",
               "section", "main", "h1", "h2", "h3", "h4", "h5", "h6"}

for url in test_urls:
    print(f"\n{'='*70}")
    print(f"URL: {url}")
    print(f"{'='*70}")
    
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Method 1: Just use body and extract all prose tags directly
        body = soup.body or soup
        prose_parts = []
        
        # Clone and clean
        soup_clean = BeautifulSoup(str(body), "html.parser")
        for noise_tag in soup_clean.find_all(list(_NOISE_TAGS)):
            noise_tag.decompose()
        
        # Extract from cleaned body
        for tag in soup_clean.find_all(_PROSE_TAGS):
            text = tag.get_text(separator=" ", strip=True)
            if len(text) > 20:  # Skip stubs
                prose_parts.append(text)
        
        prose = "\n".join(prose_parts)
        
        print(f"✓ Prose extracted: {len(prose)} chars, {len(prose_parts)} parts")
        
        if prose:
            print(f"  First 150 chars: {prose[:150]}...")
        else:
            print(f"  ✗ EMPTY PROSE!")
            
            # Debug: show what p tags we have
            p_tags = soup.find_all("p")
            print(f"  Found {len(p_tags)} <p> tags total")
            if p_tags:
                sample_p = p_tags[0].get_text(separator=" ", strip=True)
                print(f"  First p tag: {sample_p[:100]}...")
                
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
