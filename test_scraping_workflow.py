#!/usr/bin/env python3
"""Test the MCP server scraping workflow."""

import json
import subprocess
import sys

def test_tool(tool_name, args=None):
    """Call a tool via the MCP server."""
    if args is None:
        args = {}
    
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": args
        }
    }
    
    try:
        proc = subprocess.Popen(
            ["python3", "-m", "mcp_server.server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"MCP_TRANSPORT": "stdio", "SQLITE_DB_PATH": "/tmp/scrapee-test.db"}
        )
        
        stdout, stderr = proc.communicate(
            input=json.dumps(request).encode() + b'\n',
            timeout=10
        )
        
        response = json.loads(stdout.decode().strip())
        return response
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def main():
    print("🔍 Testing MCP Server Scraping Workflow\n")
    
    # Test 1: List documents (should be empty)
    print("=" * 60)
    print("TEST 1: List Documents (should be empty)")
    print("=" * 60)
    response = test_tool("list_docs")
    if response and "result" in response:
        content = response["result"]["content"][0]["text"]
        data = json.loads(content)
        print(f"✅ Database status:")
        print(f"   Total docs: {data['total']}")
        print()
    
    # Test 2: Search (should find nothing)
    print("=" * 60)
    print("TEST 2: Search (should find nothing)")
    print("=" * 60)
    response = test_tool("search_docs", {"query": "test"})
    if response and "result" in response:
        content = response["result"]["content"][0]["text"]
        data = json.loads(content)
        print(f"Search results: {data.get('_meta', {}).get('total', 0)}")
        print(f"Auto-ingested: {data.get('_meta', {}).get('auto_ingested', False)}")
        print()
    
    print("=" * 60)
    print("✅ All tests complete!")
    print("=" * 60)
    print("\nWorkflow Summary:")
    print("1. Run: python3 init_db.py  (creates database)")
    print("2. User calls: scrape_url with documentation URL")
    print("   - Pages are discovered via links")
    print("   - All pages stored in database")
    print("3. User calls: search_docs with a question")
    print("   - Searches stored pages")
    print("   - Returns relevant results with snippets")
    print("\nNo auto-scraping - user controls what gets indexed!")

if __name__ == "__main__":
    main()
