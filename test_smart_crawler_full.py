#!/usr/bin/env python3
import sys
sys.path.insert(0, '/Users/jonathan/elco/scrapee/backend')

from smart_crawler import SmartCrawler

# Test with depth to get all crawled pages
urls = [
    "https://nodejs.org/api/",
    "https://docs.python.org/3/library/asyncio.html",
]

for test_url in urls:
    print(f"\n{'='*70}")
    print(f"Testing: {test_url}")
    print(f"{'='*70}")
    
    try:
        crawler = SmartCrawler(
            timeout=15,
            delay_between_requests=0.2,
            min_good_docs=3,
            cross_domain_budget=2,
        )
        
        docs = crawler.crawl(seed_url=test_url, max_pages=50, max_depth=1)
        
        print(f"\n✓ Crawl completed!")
        print(f"  Total documents: {len(docs)}")
        
        # Show breakdown
        good_docs = [d for d in docs if len(d.content) >= 50]
        thin_docs = [d for d in docs if len(d.content) < 50]
        
        print(f"  Good content (>50 chars): {len(good_docs)}")
        print(f"  Thin content (<50 chars): {len(thin_docs)}")
        
        # Show details for first 5
        for i, doc in enumerate(docs[:5]):
            print(f"\n  [{i+1}] {doc.url[:60]}")
            print(f"      Content: {len(doc.content)} chars")
            print(f"      Paragraphs: {len(doc.paragraphs)}")
            print(f"      Headings: {len(doc.headings)}")
            print(f"      Links: {doc.links_count}")
            
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
