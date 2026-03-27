#!/usr/bin/env python3
"""Comprehensive MCP server test suite."""

import subprocess
import json
import sys

def test_mcp(name, request, transport="stdio"):
    """Test a single MCP request"""
    print(f"\n{'='*60}")
    print(f"Test: {name}")
    print(f"{'='*60}")
    print(f"Request: {json.dumps(request, indent=2)}")
    
    try:
        proc = subprocess.Popen(
            ['/usr/bin/python3', '-m', 'mcp_server.server'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={'MCP_TRANSPORT': transport, 'SQLITE_DB_PATH': '/tmp/scrapee-test.db'}
        )
        
        stdout, stderr = proc.communicate(
            input=json.dumps(request).encode() + b'\n',
            timeout=10
        )
        
        response = json.loads(stdout.decode().strip())
        print(f"\nResponse:")
        print(json.dumps(response, indent=2))
        
        # Validate response structure
        if 'jsonrpc' not in response or response['jsonrpc'] != '2.0':
            print("❌ FAIL: Missing or invalid jsonrpc field")
            return False
        
        if 'id' not in response or response['id'] != request.get('id'):
            print("❌ FAIL: Missing or mismatched id field")
            return False
        
        if 'error' in response:
            print(f"✓ Error response (expected for some tests): {response['error']['message']}")
            return True
        
        if 'result' in response:
            print("✓ PASS: Valid response structure")
            return True
        
        print("❌ FAIL: Response missing both result and error")
        return False
        
    except subprocess.TimeoutExpired:
        print("❌ FAIL: Request timeout")
        return False
    except json.JSONDecodeError as e:
        print(f"❌ FAIL: Invalid JSON response: {e}")
        return False
    except Exception as e:
        print(f"❌ FAIL: {e}")
        return False

# Run tests
tests = [
    ("Initialize", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
    ("Tools List", {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
    ("Ping", {"jsonrpc": "2.0", "id": 3, "method": "ping", "params": {}}),
    ("Invalid Method", {"jsonrpc": "2.0", "id": 4, "method": "invalid/method", "params": {}}),
    ("Missing jsonrpc", {"id": 5, "method": "initialize", "params": {}}),
    ("Missing method", {"jsonrpc": "2.0", "id": 6, "params": {}}),
]

results = []
for name, request in tests:
    results.append((name, test_mcp(name, request)))

print(f"\n{'='*60}")
print("TEST SUMMARY")
print(f"{'='*60}")
for name, passed in results:
    status = "✓ PASS" if passed else "❌ FAIL"
    print(f"{status}: {name}")

total = len(results)
passed = sum(1 for _, p in results if p)
print(f"\nTotal: {passed}/{total} tests passed")

sys.exit(0 if passed == total else 1)
