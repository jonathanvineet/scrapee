#!/usr/bin/env python3
import sys
sys.path.insert(0, '/Users/jonathan/elco/scrapee/backend')

from pipeline_crawler import UltraFastCrawler

# Test with a real documentation site
url = "https://docs.python.org/3/library/asyncio.html"
print(f"Testing Pipeline Crawler with URL: {url}\n")

try:
    crawler = UltraFastCrawler(start_url=url, max_depth=1, max_workers=2)
    results = crawler.crawl()
    
    print(f"✓ Crawled {len(results)} pages\n")
    
    # Show the first page structure
    if results:
        first_url = list(results.keys())[0]
        first_page = results[first_url]
        
        print(f"First page URL: {first_url}")
        print(f"Type of first page: {type(first_page)}")
        
        if isinstance(first_page, dict):
            print(f"\n✓ Dict format - Keys: {list(first_page.keys())}")
            print(f"  Paragraphs: {len(first_page.get('paragraphs', []))}")
            print(f"  Headings: {len(first_page.get('headings', []))}")
            print(f"  Links count: {first_page.get('links_count', 0)}")
            print(f"  Title: {first_page.get('title', 'N/A')[:60]}")
        else:
            print(f"\n✗ NOT a dict! It's a {type(first_page)}")
            if isinstance(first_page, str):
                print(f"  String length: {len(first_page)}")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
