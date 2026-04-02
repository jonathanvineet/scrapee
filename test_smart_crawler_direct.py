#!/usr/bin/env python3
import sys
sys.path.insert(0, '/Users/jonathan/elco/scrapee/backend')

from smart_crawler import SmartCrawler

# Test SmartCrawler directly
url = "https://docs.python.org/3/library/asyncio.html"
print(f"Testing SmartCrawler with {url}\n")

try:
    crawler = SmartCrawler(
        timeout=15,
        delay_between_requests=0.3,
        min_good_docs=5,
        cross_domain_budget=3,
    )
    
    print("Starting crawl...")
    docs = crawler.crawl(seed_url=url, max_pages=30, max_depth=1)
    
    print(f"\n✓ Crawl completed!")
    print(f"  Documents returned: {len(docs)}")
    print(f"  Type: {type(docs)}")
    
    if docs:
        print(f"\n  First document:")
        first = docs[0]
        print(f"    URL: {first.url}")
        print(f"    Title: {first.title}")
        print(f"    Content length: {len(first.content)}")
        print(f"    Paragraphs: {len(first.paragraphs)}")
        print(f"    Headings: {len(first.headings)}")
        print(f"    Links count: {first.links_count}")
    else:
        print(f"\n  ✗ No documents returned!")
        
except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
