"""
Quick Start Test Script for Scrapee MCP Server
Run this to verify your MCP server is working correctly.
"""
import json
import requests

# Change this to your deployed URL or keep as localhost for local testing
MCP_URL = "http://localhost:5001/api/mcp"
# MCP_URL = "https://your-project.vercel.app/api/mcp"


def test_mcp_server():
    """Test all MCP server capabilities."""
    
    print("🧪 Testing Scrapee MCP Server\n")
    print(f"Target: {MCP_URL}\n")
    print("=" * 60)
    
    # Test 1: Initialize
    print("\n1️⃣ Testing Initialize...")
    response = requests.post(MCP_URL, json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {}
    })
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Server initialized: {result['result']['serverInfo']['name']} v{result['result']['serverInfo']['version']}")
        print(f"   Capabilities: {list(result['result']['capabilities'].keys())}")
    else:
        print(f"❌ Failed: {response.status_code}")
        return
    
    # Test 2: List Tools
    print("\n2️⃣ Testing List Tools...")
    response = requests.post(MCP_URL, json={
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {}
    })
    
    if response.status_code == 200:
        result = response.json()
        tools = result['result']['tools']
        print(f"✅ Found {len(tools)} tools:")
        for tool in tools:
            print(f"   - {tool['name']}: {tool['description']}")
    else:
        print(f"❌ Failed: {response.status_code}")
    
    # Test 3: List Resources
    print("\n3️⃣ Testing List Resources...")
    response = requests.post(MCP_URL, json={
        "jsonrpc": "2.0",
        "id": 3,
        "method": "resources/list",
        "params": {}
    })
    
    if response.status_code == 200:
        result = response.json()
        resources = result['result']['resources']
        print(f"✅ Found {len(resources)} resources:")
        for resource in resources:
            print(f"   - {resource['uri']}: {resource['name']}")
    else:
        print(f"❌ Failed: {response.status_code}")
    
    # Test 4: List Prompts
    print("\n4️⃣ Testing List Prompts...")
    response = requests.post(MCP_URL, json={
        "jsonrpc": "2.0",
        "id": 4,
        "method": "prompts/list",
        "params": {}
    })
    
    if response.status_code == 200:
        result = response.json()
        prompts = result['result']['prompts']
        print(f"✅ Found {len(prompts)} prompts:")
        for prompt in prompts:
            print(f"   - {prompt['name']}: {prompt['description']}")
    else:
        print(f"❌ Failed: {response.status_code}")
    
    # Test 5: List Docs (should be empty initially)
    print("\n5️⃣ Testing List Docs...")
    response = requests.post(MCP_URL, json={
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "list_docs",
            "arguments": {}
        }
    })
    
    if response.status_code == 200:
        result = response.json()
        content = json.loads(result['result']['content'][0]['text'])
        print(f"✅ Current docs: {content['total']} documents")
        if content['urls']:
            for url in content['urls'][:5]:
                print(f"   - {url}")
    else:
        print(f"❌ Failed: {response.status_code}")
    
    # Test 6: Scrape URL (optional - uncomment to test)
    print("\n6️⃣ Testing Scrape URL (skipped - uncomment to test)...")
    print("   💡 To test scraping, uncomment the code below")
    
    # Uncomment to test scraping:
    # response = requests.post(MCP_URL, json={
    #     "jsonrpc": "2.0",
    #     "id": 6,
    #     "method": "tools/call",
    #     "params": {
    #         "name": "scrape_url",
    #         "arguments": {
    #             "url": "https://example.com",
    #             "max_depth": 1
    #         }
    #     }
    # })
    # 
    # if response.status_code == 200:
    #     result = response.json()
    #     content = json.loads(result['result']['content'][0]['text'])
    #     print(f"✅ Scraped: {content.get('pages_scraped', 0)} pages")
    # else:
    #     print(f"❌ Failed: {response.status_code}")
    
    print("\n" + "=" * 60)
    print("✅ MCP Server Test Complete!")
    print("\n💡 Next Steps:")
    print("   1. Update .vscode/mcp.json with your server URL")
    print("   2. Restart VS Code")
    print("   3. Ask Copilot to scrape documentation")
    print("   4. Ask questions about the documentation")


if __name__ == "__main__":
    try:
        test_mcp_server()
    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to MCP server")
        print("   Make sure the server is running:")
        print("   $ cd backend && python api/mcp.py")
    except Exception as e:
        print(f"❌ Error: {e}")
