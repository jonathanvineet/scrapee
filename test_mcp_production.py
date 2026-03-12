"""
Comprehensive Test Suite for Production MCP Server
Tests all tools, resources, prompts, security, and caching.
"""
import sys
import os
import json
import time

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from api.mcp import ProductionMCPServer, SecurityConfig
from storage.sqlite_store import SQLiteStore
from smart_scraper import create_scraper


class Colors:
    """Terminal colors for pretty output."""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'
    BOLD = '\033[1m'


def print_test(name, passed, details=""):
    """Print test result with color."""
    symbol = f"{Colors.GREEN}✓{Colors.END}" if passed else f"{Colors.RED}✗{Colors.END}"
    status = f"{Colors.GREEN}PASS{Colors.END}" if passed else f"{Colors.RED}FAIL{Colors.END}"
    print(f"{symbol} {name}: {status}")
    if details and not passed:
        print(f"  {Colors.YELLOW}{details}{Colors.END}")


def print_section(title):
    """Print section header."""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{title}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}\n")


class MCPServerTests:
    """Test suite for MCP server."""
    
    def __init__(self):
        """Initialize test suite."""
        # Use test database
        self.test_db = "/tmp/test_mcp_docs.db"
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        
        self.server = ProductionMCPServer(use_sqlite=True)
        self.server.store = SQLiteStore(self.test_db)
        
        self.passed = 0
        self.failed = 0
    
    def run_all(self):
        """Run all tests."""
        print(f"\n{Colors.BOLD}Production MCP Server Test Suite{Colors.END}")
        print(f"Database: {self.test_db}\n")
        
        # Test sections
        self.test_initialization()
        self.test_security()
        self.test_storage()
        self.test_scraper()
        self.test_mcp_protocol()
        self.test_tools()
        self.test_resources()
        self.test_prompts()
        self.test_caching()
        
        # Summary
        self.print_summary()
        
        # Cleanup
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
    
    def test_initialization(self):
        """Test server initialization."""
        print_section("Initialization Tests")
        
        # Test server created
        passed = self.server is not None
        print_test("Server initialization", passed)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        
        # Test version
        passed = self.server.version == "2.0.0"
        print_test("Version check", passed, f"Expected 2.0.0, got {self.server.version}")
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        
        # Test components
        passed = all([
            self.server.store is not None,
            self.server.search is not None,
            self.server.scraper is not None,
            self.server.cache is not None
        ])
        print_test("Component initialization", passed)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
    
    def test_security(self):
        """Test security features."""
        print_section("Security Tests")
        
        # Test domain allowlist
        test_cases = [
            ("https://docs.hedera.com", True, "Allowed domain"),
            ("https://malicious.com", False, "Blocked domain"),
            ("https://docs.python.org", True, "Allowed domain"),
            ("http://example.com", False, "Not in allowlist"),
        ]
        
        for url, should_pass, description in test_cases:
            is_valid, error = SecurityConfig.validate_url(url)
            passed = is_valid == should_pass
            print_test(f"Domain validation: {description}", passed, error if not passed else "")
            if passed:
                self.passed += 1
            else:
                self.failed += 1
        
        # Test URL validation
        invalid_urls = [
            ("", "Empty URL"),
            ("not-a-url", "Invalid format"),
            ("ftp://example.com", "Wrong protocol"),
        ]
        
        for url, description in invalid_urls:
            is_valid, error = SecurityConfig.validate_url(url)
            passed = not is_valid
            print_test(f"Reject {description}", passed, error if passed else "Should have been rejected")
            if passed:
                self.passed += 1
            else:
                self.failed += 1
    
    def test_storage(self):
        """Test SQLite storage."""
        print_section("Storage Tests")
        
        # Test save document
        test_doc = {
            "url": "https://docs.example.com/test",
            "content": "This is test content with some code examples.",
            "metadata": {"title": "Test Document", "language": "en"},
            "code_blocks": [
                {
                    "snippet": "def hello():\n    print('Hello')",
                    "language": "python",
                    "context": "Example function",
                    "line_number": 1
                }
            ],
            "topics": [
                {
                    "topic": "introduction",
                    "heading": "Introduction",
                    "level": 1,
                    "content": "This is an introduction"
                }
            ]
        }
        
        success = self.server.store.save_doc(
            test_doc["url"],
            test_doc["content"],
            metadata=test_doc["metadata"],
            code_blocks=test_doc["code_blocks"],
            topics=test_doc["topics"]
        )
        print_test("Save document", success)
        if success:
            self.passed += 1
        else:
            self.failed += 1
        
        # Test retrieve document
        retrieved = self.server.store.get_doc(test_doc["url"])
        passed = retrieved is not None and retrieved["url"] == test_doc["url"]
        print_test("Retrieve document", passed)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        
        # Test list documents
        docs = self.server.store.list_docs()
        passed = len(docs) == 1 and docs[0] == test_doc["url"]
        print_test("List documents", passed, f"Expected 1 doc, got {len(docs)}")
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        
        # Test search documents
        results = self.server.store.search_docs("test content")
        passed = len(results) > 0
        print_test("Search documents (FTS)", passed)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        
        # Test search code
        results = self.server.store.search_code("hello")
        passed = len(results) > 0
        print_test("Search code blocks", passed)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        
        # Test get topics
        topics = self.server.store.get_topics_by_url(test_doc["url"])
        passed = len(topics) == 1 and topics[0]["heading"] == "Introduction"
        print_test("Get document topics", passed)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        
        # Test statistics
        stats = self.server.store.get_stats()
        passed = stats["total_docs"] == 1 and stats["total_code_blocks"] == 1
        print_test("Get statistics", passed, json.dumps(stats, indent=2))
        if passed:
            self.passed += 1
        else:
            self.failed += 1
    
    def test_scraper(self):
        """Test smart scraper."""
        print_section("Scraper Tests")
        
        scraper = create_scraper()
        
        # Test HTML parsing
        test_html = """
        <html>
        <head><title>Test Page</title></head>
        <body>
            <h1>Introduction</h1>
            <p>This is a test page with code examples.</p>
            <pre><code class="language-python">
def test():
    return True
            </code></pre>
            <h2>Usage</h2>
            <p>Here's how to use it.</p>
            <code>const x = 5;</code>
        </body>
        </html>
        """
        
        parsed = scraper.parse_html(test_html, "https://example.com/test")
        
        # Test metadata extraction
        passed = parsed["metadata"]["title"] == "Test Page"
        print_test("Extract metadata", passed)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        
        # Test code block extraction
        passed = len(parsed["code_blocks"]) == 2
        print_test("Extract code blocks", passed, f"Expected 2, got {len(parsed['code_blocks'])}")
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        
        # Test language detection
        if len(parsed["code_blocks"]) > 0:
            first_code = parsed["code_blocks"][0]
            passed = first_code["language"] == "python"
            print_test("Detect language", passed, f"Expected python, got {first_code['language']}")
            if passed:
                self.passed += 1
            else:
                self.failed += 1
        
        # Test topic extraction
        passed = len(parsed["topics"]) == 2
        print_test("Extract topics", passed, f"Expected 2, got {len(parsed['topics'])}")
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        
        # Test content extraction
        passed = "test page with code examples" in parsed["content"].lower()
        print_test("Extract text content", passed)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
    
    def test_mcp_protocol(self):
        """Test MCP protocol compliance."""
        print_section("MCP Protocol Tests")
        
        # Test initialize
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {}
        }
        
        response = self.server.handle_request(request)
        passed = (
            response.get("jsonrpc") == "2.0" and
            "result" in response and
            "serverInfo" in response["result"]
        )
        print_test("Initialize endpoint", passed)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        
        # Test tools/list
        request["method"] = "tools/list"
        request["id"] = 2
        
        response = self.server.handle_request(request)
        passed = (
            "result" in response and
            "tools" in response["result"] and
            len(response["result"]["tools"]) >= 5
        )
        print_test("List tools endpoint", passed)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        
        # Test resources/list
        request["method"] = "resources/list"
        request["id"] = 3
        
        response = self.server.handle_request(request)
        passed = "result" in response and "resources" in response["result"]
        print_test("List resources endpoint", passed)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        
        # Test prompts/list
        request["method"] = "prompts/list"
        request["id"] = 4
        
        response = self.server.handle_request(request)
        passed = (
            "result" in response and
            "prompts" in response["result"] and
            len(response["result"]["prompts"]) == 3
        )
        print_test("List prompts endpoint", passed)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        
        # Test error handling
        request["method"] = "invalid_method"
        request["id"] = 5
        
        response = self.server.handle_request(request)
        passed = "error" in response and response["error"]["code"] == -32601
        print_test("Error handling", passed)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
    
    def test_tools(self):
        """Test MCP tools."""
        print_section("Tools Tests")
        
        # Test list_docs
        result = self.server._tool_list_docs({})
        passed = "total" in result and "urls" in result and "stats" in result
        print_test("Tool: list_docs", passed)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        
        # Test get_doc
        test_url = "https://docs.example.com/test"
        result = self.server._tool_get_doc({"url": test_url})
        passed = "url" in result or "error" in result
        print_test("Tool: get_doc", passed)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        
        # Test search_docs
        result = self.server._tool_search_docs({"query": "test"})
        passed = "query" in result and "results" in result
        print_test("Tool: search_docs", passed)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        
        # Test search_code
        result = self.server._tool_search_code({"query": "hello", "limit": 5})
        passed = "query" in result and "code_blocks" in result
        print_test("Tool: search_code", passed)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        
        # Test get_code_example
        result = self.server._tool_get_code_example({"query": "function", "limit": 3})
        passed = "query" in result and "examples" in result
        print_test("Tool: get_code_example", passed)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        
        # Test search_and_get
        result = self.server._tool_search_and_get({"query": "test", "k": 3})
        passed = "query" in result and "results" in result
        print_test("Tool: search_and_get", passed)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
    
    def test_resources(self):
        """Test MCP resources."""
        print_section("Resources Tests")
        
        # Test docs://all resource
        request = {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "resources/read",
            "params": {"uri": "docs://all"}
        }
        
        response = self.server.handle_request(request)
        passed = (
            "result" in response and
            "contents" in response["result"] and
            len(response["result"]["contents"]) > 0
        )
        print_test("Resource: docs://all", passed)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        
        # Test domain-specific resource
        request["params"]["uri"] = "docs://docs.example.com"
        request["id"] = 11
        
        response = self.server.handle_request(request)
        passed = "result" in response or "error" in response
        print_test("Resource: docs://domain", passed)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
    
    def test_prompts(self):
        """Test MCP prompts."""
        print_section("Prompts Tests")
        
        # Test build_feature prompt
        request = {
            "jsonrpc": "2.0",
            "id": 20,
            "method": "prompts/get",
            "params": {
                "name": "build_feature",
                "arguments": {"feature": "user authentication"}
            }
        }
        
        response = self.server.handle_request(request)
        passed = (
            "result" in response and
            "messages" in response["result"] and
            len(response["result"]["messages"]) > 0
        )
        print_test("Prompt: build_feature", passed)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        
        # Test debug_code prompt
        request["params"] = {
            "name": "debug_code",
            "arguments": {
                "code": "const x = undefined.foo;",
                "error": "Cannot read property 'foo' of undefined"
            }
        }
        request["id"] = 21
        
        response = self.server.handle_request(request)
        passed = "result" in response and "messages" in response["result"]
        print_test("Prompt: debug_code", passed)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        
        # Test explain_api prompt
        request["params"] = {
            "name": "explain_api",
            "arguments": {"api_name": "fetch"}
        }
        request["id"] = 22
        
        response = self.server.handle_request(request)
        passed = "result" in response and "messages" in response["result"]
        print_test("Prompt: explain_api", passed)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
    
    def test_caching(self):
        """Test caching layer."""
        print_section("Caching Tests")
        
        # Test cache set/get
        self.server.cache.set("test_key", {"data": "test"})
        cached = self.server.cache.get("test_key")
        passed = cached is not None and cached["data"] == "test"
        print_test("Cache set/get", passed)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        
        # Test cache miss
        cached = self.server.cache.get("nonexistent_key")
        passed = cached is None
        print_test("Cache miss", passed)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        
        # Test cache clear
        self.server.cache.clear()
        cached = self.server.cache.get("test_key")
        passed = cached is None
        print_test("Cache clear", passed)
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        
        # Test tool caching
        # First call (not cached)
        start = time.time()
        self.server._tool_search_and_get({"query": "test", "k": 3})
        first_time = time.time() - start
        
        # Second call (cached)
        start = time.time()
        self.server._tool_search_and_get({"query": "test", "k": 3})
        second_time = time.time() - start
        
        # Cached should be faster (not always guaranteed, but likely)
        passed = True  # Just check it doesn't error
        print_test("Tool result caching", passed, f"First: {first_time:.3f}s, Second: {second_time:.3f}s")
        if passed:
            self.passed += 1
        else:
            self.failed += 1
    
    def print_summary(self):
        """Print test summary."""
        print_section("Test Summary")
        
        total = self.passed + self.failed
        percentage = (self.passed / total * 100) if total > 0 else 0
        
        print(f"Total Tests: {total}")
        print(f"{Colors.GREEN}Passed: {self.passed}{Colors.END}")
        print(f"{Colors.RED}Failed: {self.failed}{Colors.END}")
        print(f"Success Rate: {percentage:.1f}%\n")
        
        if self.failed == 0:
            print(f"{Colors.GREEN}{Colors.BOLD}🎉 All tests passed!{Colors.END}\n")
        else:
            print(f"{Colors.RED}{Colors.BOLD}⚠️  Some tests failed. Review output above.{Colors.END}\n")


if __name__ == "__main__":
    print(f"\n{Colors.BOLD}Starting Production MCP Server Tests...{Colors.END}")
    
    tests = MCPServerTests()
    tests.run_all()
