#!/usr/bin/env python3
import sys
sys.path.insert(0, '/Users/jonathan/elco/scrapee/backend')

from bs4 import BeautifulSoup
import requests
import re
from urllib.parse import urlparse

# Fetch a real page
url = "https://docs.python.org/3/library/asyncio.html"
print(f"Fetching {url}...\n")

resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
soup = BeautifulSoup(resp.text, "html.parser")

_NOISE_TAGS = {"script", "style", "nav", "footer", "header", "aside",
               "form", "noscript", "iframe", "svg", "button", "input"}

_PROSE_TAGS = {"p", "li", "td", "dd", "blockquote", "article",
               "section", "main", "h1", "h2", "h3", "h4", "h5", "h6"}

# Remove noise tags
soup_copy = BeautifulSoup(str(soup), "html.parser")
for tag in soup_copy(list(_NOISE_TAGS)):
    tag.decompose()

# Find main content - step by step
print(f"Checking for main content container...")
main = soup_copy.find("main")
print(f"  main: {main.name if main else None}")

article = soup_copy.find("article")
print(f"  article: {article.name if article else None}")

id_match = soup_copy.find(id=re.compile(r"(content|main|docs?)", re.I))
print(f"  id_match: {id_match.name if id_match else None}")

class_match = soup_copy.find(class_=re.compile(r"(content|main|docs?|markdown|prose)", re.I))
print(f"  class_match: {class_match.name if class_match else None}")

body = soup_copy.body
print(f"  body: {body.name if body else None}")

# Pick the first non-None
main = (main or article or id_match or class_match or body or soup_copy)
print(f"\nUsing main: {main.name if hasattr(main, 'name') else type(main)}")

# Extract prose
parts = []
all_prose_tags = main.find_all(_PROSE_TAGS)
print(f"\nFound {len(all_prose_tags)} prose tags")

for i, tag in enumerate(all_prose_tags[:5]):
    text = tag.get_text(separator=" ", strip=True)
    if len(text) > 20:
        parts.append(text)
        print(f"  [{i}] {tag.name}: {len(text)} chars, text: {text[:50]}...")

print(f"\nTotal parts found: {len(parts)}")
print(f"Total prose length: {sum(len(p) for p in parts)} chars")

if not parts:
    print(f"\n✗ No prose parts extracted!")
    print(f"\nDEBUG: Looking for p tags...")
    for p in soup_copy.find_all("p")[:3]:
        text = p.get_text(separator=" ", strip=True)
        print(f"  Found p: {len(text)} chars, text: {text[:60]}...")
