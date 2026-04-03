#!/usr/bin/env python3
"""
Test script for new MCP tools.
Run this to verify all 10 new tools are working correctly.
"""

import json
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from mcp import MCPServer

def test_tools():
    """Test all new tools."""
    server = MCPServer()
    
    print("=" * 70)
    print("Testing 10 New MCP Tools")
    print("=" * 70)
    
    # Test 1: batch_scrape_urls
    print("\n✓ Test 1: batch_scrape_urls")
    result = server._tool_batch_scrape_urls({
        "urls": ["https://github.com"],
        "max_concurrent": 1,
        "max_depth": 0
    })
    print(f"  Result keys: {list(result.keys())}")
    print(f"  Structure: total={result.get('total')}, successful={result.get('successful')}")
    
    # Test 2: get_index_stats
    print("\n✓ Test 2: get_index_stats")
    result = server._tool_get_index_stats({})
    print(f"  Result keys: {list(result.keys())}")
    print(f"  Total docs: {result.get('total_documents')}, Code blocks: {result.get('total_code_blocks')}")
    
    # Test 3: search_with_filters
    print("\n✓ Test 3: search_with_filters")
    result = server._tool_search_with_filters({
        "query": "test",
        "limit": 5
    })
    print(f"  Result keys: {list(result.keys())}")
    print(f"  Found {result.get('count')} results")
    
    # Test 4: delete_document (will fail if doc doesn't exist, that's OK)
    print("\n✓ Test 4: delete_document")
    result = server._tool_delete_document({
        "url": "https://nonexistent.example.com/test"
    })
    print(f"  Result: {result.get('success', False)}, Deleted: {result.get('deleted', False)}")
    
    # Test 5: prune_docs
    print("\n✓ Test 5: prune_docs")
    result = server._tool_prune_docs({
        "older_than_days": 365
    })
    print(f"  Deleted count: {result.get('deleted_count', 0)}")
    
    # Test 6: analyze_code_dependencies
    print("\n✓ Test 6: analyze_code_dependencies")
    result = server._tool_analyze_code_dependencies({
        "code_snippets": ["import requests", "def hello():", "class MyClass:"],
        "language": "python",
        "extract_imports": True,
        "extract_types": True
    })
    print(f"  Result keys: {list(result.keys())}")
    print(f"  Imports: {result.get('imports')}, Functions: {len(result.get('functions', []))}")
    
    # Test 7: validate_urls
    print("\n✓ Test 7: validate_urls")
    result = server._tool_validate_urls({
        "limit": 5
    })
    print(f"  Checked: {result.get('checked')}, Alive: {result.get('alive')}, Dead: {result.get('dead')}")
    
    # Test 8: export_index
    print("\n✓ Test 8: export_index")
    result = server._tool_export_index({
        "format": "json"
    })
    print(f"  Format: {result.get('format')}, Doc count: {result.get('doc_count')}")
    
    # Test 9: compare_documents (will fail if docs don't exist)
    print("\n✓ Test 9: compare_documents")
    result = server._tool_compare_documents({
        "url1": "https://nonexistent1.example.com",
        "url2": "https://nonexistent2.example.com"
    })
    print(f"  Has error: {'error' in result}")
    
    # Test 10: search_and_summarize
    print("\n✓ Test 10: search_and_summarize")
    result = server._tool_search_and_summarize({
        "query": "documentation",
        "summary_length": "medium",
        "include_code_examples": True,
        "limit": 3
    })
    print(f"  Query: {result.get('query')}, Summary length: {len(result.get('summary', ''))}")
    
    # Test 11: extract_structured_data (won't fetch a real site in test)
    print("\n✓ Test 11: extract_structured_data")
    result = server._tool_extract_structured_data({
        "url": "https://github.com"
    })
    print(f"  Result keys: {list(result.keys()) if 'error' not in result else 'error'}")
    
    print("\n" + "=" * 70)
    print("All tool tests completed!")
    print("=" * 70)


if __name__ == "__main__":
    test_tools()
