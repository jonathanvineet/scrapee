#!/usr/bin/env python3
"""
Test script for MCP integration with Scrapee backend.
Tests the /mcp/page endpoint with JSON-RPC calls.
"""

import requests
import json

BASE_URL = "http://localhost:8080"

def test_mcp_tools_list():
    """Test the tools/list JSON-RPC method"""
    print("Testing MCP tools/list...")
    
    url = f"{BASE_URL}/mcp/page?url=https://example.com"
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/list",
        "id": 1
    }
    
    response = requests.post(url, json=payload)
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    print()

def test_mcp_get_page_content():
    """Test the tools/call method with get_page_content tool"""
    print("Testing MCP tools/call with get_page_content...")
    
    url = f"{BASE_URL}/mcp/page?url=https://example.com"
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "get_page_content"
        },
        "id": 2
    }
    
    response = requests.post(url, json=payload)
    print(f"Status: {response.status_code}")
    result = response.json()
    if 'result' in result:
        print(f"Content preview: {result['result']['content'][0]['text'][:200]}...")
    else:
        print(f"Response: {json.dumps(result, indent=2)}")
    print()

def test_mcp_get_page_headings():
    """Test the tools/call method with get_page_headings tool"""
    print("Testing MCP tools/call with get_page_headings...")
    
    url = f"{BASE_URL}/mcp/page?url=https://example.com"
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "get_page_headings"
        },
        "id": 3
    }
    
    response = requests.post(url, json=payload)
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    print()

def scrape_test_page():
    """First scrape a test page to populate the history"""
    print("Scraping test page first...")
    
    url = f"{BASE_URL}/api/scrape"
    payload = {
        "urls": ["https://example.com"],
        "mode": "smart",
        "max_depth": 0
    }
    
    response = requests.post(url, json=payload)
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        print("Successfully scraped page")
    else:
        print(f"Error: {response.json()}")
    print()

if __name__ == "__main__":
    print("=" * 60)
    print("MCP Integration Test Suite")
    print("=" * 60)
    print()
    
    # First, scrape a test page
    scrape_test_page()
    
    # Then test MCP endpoints
    test_mcp_tools_list()
    test_mcp_get_page_content()
    test_mcp_get_page_headings()
    
    print("=" * 60)
    print("Test complete!")
    print("=" * 60)
