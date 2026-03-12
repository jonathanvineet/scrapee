"""
Production-Grade Model Context Protocol (MCP) Server
Universal developer documentation assistant with advanced features.
"""
import json
import sys
import os
from typing import Dict, List, Any, Optional
import re
from urllib.parse import urlparse
from datetime import datetime, timedelta

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request, jsonify
from flask_cors import CORS

from storage.sqlite_store import get_sqlite_store
from index.vector_search import get_search_engine
from utils.normalize import normalize_url
from smart_scraper import create_scraper

# Import crawler
try:
    from smart_crawler import SmartCrawler
    CRAWLER_AVAILABLE = True
except ImportError:
    CRAWLER_AVAILABLE = False
    print("⚠ SmartCrawler not available")


class SecurityConfig:
    """Security configuration for MCP server."""
    
    # Allowed domains for scraping (allowlist)
    ALLOWED_DOMAINS = [
        'docs.hedera.com',
        'docs.solana.com',
        'react.dev',
        'reactjs.org',
        'docs.rs',
        'doc.rust-lang.org',
        'docs.python.org',
        'developer.mozilla.org',
        'docs.docker.com',
        'kubernetes.io',
        'docs.npmjs.com',
        'github.com',
        'stackoverflow.com',
        'dev.to',
        'medium.com',
        # Add more as needed
    ]
    
    # Max content size (10MB)
    MAX_CONTENT_SIZE = 10 * 1024 * 1024
    
    # Max URLs per scrape session
    MAX_URLS_PER_SESSION = 100
    
    @classmethod
    def is_domain_allowed(cls, url: str) -> bool:
        """Check if domain is in allowlist."""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        # Check exact matches and subdomains
        for allowed in cls.ALLOWED_DOMAINS:
            if domain == allowed or domain.endswith('.' + allowed):
                return True
        
        return False
    
    @classmethod
    def validate_url(cls, url: str) -> Tuple[bool, str]:
        """
        Validate URL for scraping.
        
        Returns:
            (is_valid, error_message)
        """
        if not url:
            return False, "URL is required"
        
        if not url.startswith(('http://', 'https://')):
            return False, "URL must start with http:// or https://"
        
        if not cls.is_domain_allowed(url):
            return False, f"Domain not in allowlist. Allowed domains: {', '.join(cls.ALLOWED_DOMAINS[:5])}..."
        
        return True, ""


class CacheLayer:
    """Simple in-memory cache for performance."""
    
    def __init__(self, ttl_seconds: int = 300):
        """
        Initialize cache.
        
        Args:
            ttl_seconds: Time-to-live for cache entries
        """
        self.cache = {}
        self.ttl = timedelta(seconds=ttl_seconds)
    
    def get(self, key: str) -> Optional[Any]:
        """Get cached value if not expired."""
        if key in self.cache:
            value, timestamp = self.cache[key]
            if datetime.now() - timestamp < self.ttl:
                return value
            else:
                del self.cache[key]
        return None
    
    def set(self, key: str, value: Any):
        """Set cache value with timestamp."""
        self.cache[key] = (value, datetime.now())
    
    def clear(self):
        """Clear all cache entries."""
        self.cache.clear()
    
    def invalidate(self, pattern: str):
        """Invalidate cache entries matching pattern."""
        keys_to_delete = [k for k in self.cache.keys() if re.search(pattern, k)]
        for key in keys_to_delete:
            del self.cache[key]


class ProductionMCPServer:
    """
    Production-grade Model Context Protocol Server.
    
    Features:
    - SQLite storage with FTS
    - Code block indexing and search
    - Topic/heading extraction
    - Security (domain allowlist)
    - Caching for performance
    - Comprehensive tools, resources, and prompts
    """
    
    def __init__(self, use_sqlite: bool = True):
        """
        Initialize MCP server.
        
        Args:
            use_sqlite: Use SQLite storage (recommended for production)
        """
        self.store = get_sqlite_store() if use_sqlite else None
        self.search = get_search_engine()
        self.scraper = create_scraper()
        self.cache = CacheLayer(ttl_seconds=300)
        self.version = "2.0.0"
        self.name = "scrapee-production"
        
        print(f"✓ Production MCP Server initialized")
        print(f"  - SQLite: {'enabled' if use_sqlite else 'disabled'}")
        print(f"  - Security: domain allowlist active")
        print(f"  - Caching: 5-minute TTL")
    
    def handle_request(self, data: Dict) -> Dict:
        """Handle incoming MCP JSON-RPC request."""
        method = data.get("method")
        request_id = data.get("id")
        params = data.get("params", {})
        
        # Route to handler
        handlers = {
            "initialize": self._handle_initialize,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
            "resources/list": self._handle_resources_list,
            "resources/read": self._handle_resources_read,
            "prompts/list": self._handle_prompts_list,
            "prompts/get": self._handle_prompts_get,
        }
        
        handler = handlers.get(method)
        if handler:
            try:
                if method == "tools/call":
                    return handler(request_id, params)
                elif method in ["resources/read", "prompts/get"]:
                    return handler(request_id, params)
                else:
                    return handler(request_id)
            except Exception as e:
                return self._error_response(request_id, -32603, f"Handler error: {str(e)}")
        
        return self._error_response(request_id, -32601, f"Method not found: {method}")
    
    def _handle_initialize(self, request_id: Any) -> Dict:
        """Handle initialize request."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {},
                    "resources": {
                        "subscribe": False,
                        "listChanged": False
                    },
                    "prompts": {
                        "listChanged": False
                    }
                },
                "serverInfo": {
                    "name": self.name,
                    "version": self.version
                }
            }
        }
    
    def _handle_tools_list(self, request_id: Any) -> Dict:
        """List all available tools."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [
                    {
                        "name": "search_and_get",
                        "description": "Search docs and return results with snippets in ONE call (recommended - reduces token cost). Returns comprehensive results including URLs, titles, and content snippets.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Search query"
                                },
                                "k": {
                                    "type": "integer",
                                    "description": "Number of results (default: 3)",
                                    "default": 3
                                },
                                "snippet_length": {
                                    "type": "integer",
                                    "description": "Max characters per snippet (default: 1000)",
                                    "default": 1000
                                }
                            },
                            "required": ["query"]
                        }
                    },
                    {
                        "name": "search_docs",
                        "description": "Search scraped documentation using semantic search (returns URLs only). Use search_and_get for better results.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Search query"
                                }
                            },
                            "required": ["query"]
                        }
                    },
                    {
                        "name": "search_code",
                        "description": "Search for code examples and snippets. Returns code blocks with language, context, and source URL.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Code search query (e.g., 'create token', 'async function')"
                                },
                                "language": {
                                    "type": "string",
                                    "description": "Filter by programming language (optional)"
                                },
                                "limit": {
                                    "type": "integer",
                                    "description": "Max results (default: 5)",
                                    "default": 5
                                }
                            },
                            "required": ["query"]
                        }
                    },
                    {
                        "name": "get_code_example",
                        "description": "Get specific code examples for a task or concept. Returns well-formatted code with explanations.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "What you want to do (e.g., 'initialize Hedera client', 'create React hook')"
                                },
                                "limit": {
                                    "type": "integer",
                                    "description": "Max examples (default: 3)",
                                    "default": 3
                                }
                            },
                            "required": ["query"]
                        }
                    },
                    {
                        "name": "scrape_url",
                        "description": "Scrape a webpage and store it in the knowledge base. Extracts structured content including code blocks and topics.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "url": {
                                    "type": "string",
                                    "description": "The URL to scrape"
                                },
                                "max_depth": {
                                    "type": "integer",
                                    "description": "Maximum crawl depth (default: 0)",
                                    "default": 0
                                }
                            },
                            "required": ["url"]
                        }
                    },
                    {
                        "name": "list_docs",
                        "description": "List all URLs in the knowledge base",
                        "inputSchema": {
                            "type": "object",
                            "properties": {}
                        }
                    },
                    {
                        "name": "get_doc",
                        "description": "Get full documentation content by URL",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "url": {
                                    "type": "string",
                                    "description": "The exact URL of the document"
                                }
                            },
                            "required": ["url"]
                        }
                    }
                ]
            }
        }
    
    def _handle_tools_call(self, request_id: Any, params: Dict) -> Dict:
        """Execute tool call."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        
        try:
            # Map tool names to handlers
            tools = {
                "search_and_get": self._tool_search_and_get,
                "search_docs": self._tool_search_docs,
                "search_code": self._tool_search_code,
                "get_code_example": self._tool_get_code_example,
                "scrape_url": self._tool_scrape_url,
                "list_docs": self._tool_list_docs,
                "get_doc": self._tool_get_doc,
            }
            
            handler = tools.get(tool_name)
            if not handler:
                return self._error_response(request_id, -32602, f"Unknown tool: {tool_name}")
            
            result = handler(arguments)
            
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2)
                        }
                    ]
                }
            }
            
        except Exception as e:
            return self._error_response(request_id, -32603, f"Tool execution error: {str(e)}")
    
    def _tool_search_and_get(self, args: Dict) -> Dict:
        """Combined search with results."""
        query = args.get("query", "")
        k = args.get("k", 3)
        snippet_length = args.get("snippet_length", 1000)
        
        if not query:
            return {"error": "Query is required"}
        
        # Check cache
        cache_key = f"search:{query}:{k}:{snippet_length}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        
        # Get docs
        docs = self.store.get_all_docs()
        
        if not docs:
            return {
                "message": "No documents in knowledge base. Use scrape_url to add documentation.",
                "results": []
            }
        
        # Search
        results = self.search.search_and_get(query, docs, k=k, snippet_length=snippet_length)
        
        response = {
            "query": query,
            "total_docs": len(docs),
            "results": results
        }
        
        # Cache result
        self.cache.set(cache_key, response)
        
        return response
    
    def _tool_search_docs(self, args: Dict) -> Dict:
        """Search documents (URLs only)."""
        query = args.get("query", "")
        
        if not query:
            return {"error": "Query is required"}
        
        results = self.store.search_docs(query, limit=10)
        
        return {
            "query": query,
            "total": len(results),
            "results": results
        }
    
    def _tool_search_code(self, args: Dict) -> Dict:
        """Search code blocks."""
        query = args.get("query", "")
        language = args.get("language")
        limit = args.get("limit", 5)
        
        if not query:
            return {"error": "Query is required"}
        
        # Check cache
        cache_key = f"code:{query}:{language}:{limit}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        
        results = self.store.search_code(query, language=language, limit=limit)
        
        response = {
            "query": query,
            "language": language,
            "total": len(results),
            "code_blocks": results
        }
        
        self.cache.set(cache_key, response)
        
        return response
    
    def _tool_get_code_example(self, args: Dict) -> Dict:
        """Get code examples for a task."""
        query = args.get("query", "")
        limit = args.get("limit", 3)
        
        if not query:
            return {"error": "Query is required"}
        
        examples = self.store.get_code_examples(query, limit=limit)
        
        # Format for better readability
        formatted = []
        for ex in examples:
            formatted.append({
                "language": ex.get("language", "unknown"),
                "code": ex.get("snippet", ""),
                "context": ex.get("context", ""),
                "source": ex.get("url", ""),
                "title": ex.get("title", "")
            })
        
        return {
            "query": query,
            "total": len(formatted),
            "examples": formatted
        }
    
    def _tool_scrape_url(self, args: Dict) -> Dict:
        """Scrape and store URL."""
        url = args.get("url", "")
        max_depth = args.get("max_depth", 0)
        
        if not url:
            return {"error": "URL is required"}
        
        # Validate URL
        is_valid, error_msg = SecurityConfig.validate_url(url)
        if not is_valid:
            return {"error": error_msg}
        
        # Normalize URL
        url = normalize_url(url)
        
        if not CRAWLER_AVAILABLE:
            return {"error": "Crawler not available in this environment"}
        
        try:
            # Create crawler
            crawler = SmartCrawler(start_url=url, max_depth=max_depth)
            
            # Crawl
            pages = crawler.crawl()
            
            if not pages:
                return {"error": "No pages scraped", "url": url}
            
            # Process and store each page
            stored_count = 0
            for page_url, html in pages.items():
                try:
                    # Parse with smart scraper
                    parsed = self.scraper.parse_html(html, page_url)
                    
                    # Store in SQLite
                    success = self.store.save_doc(
                        page_url,
                        parsed["content"],
                        metadata=parsed["metadata"],
                        code_blocks=parsed["code_blocks"],
                        topics=parsed["topics"]
                    )
                    
                    if success:
                        stored_count += 1
                    
                except Exception as e:
                    print(f"Error processing {page_url}: {e}")
                    continue
            
            # Invalidate search cache
            self.cache.clear()
            
            return {
                "message": f"Successfully scraped {stored_count} pages",
                "url": url,
                "pages_scraped": stored_count,
                "max_depth": max_depth,
                "pages": list(pages.keys())[:10]  # Limit output
            }
            
        except Exception as e:
            return {"error": f"Scraping failed: {str(e)}", "url": url}
    
    def _tool_list_docs(self, args: Dict) -> Dict:
        """List all documents."""
        urls = self.store.list_docs()
        stats = self.store.get_stats()
        
        return {
            "total": len(urls),
            "urls": urls[:50],  # Limit to first 50
            "stats": stats
        }
    
    def _tool_get_doc(self, args: Dict) -> Dict:
        """Get document by URL."""
        url = args.get("url", "")
        
        if not url:
            return {"error": "URL is required"}
        
        doc = self.store.get_doc(url)
        
        if not doc:
            return {"error": f"Document not found: {url}"}
        
        # Get topics for this doc
        topics = self.store.get_topics_by_url(url)
        doc["topics"] = topics
        
        return doc
    
    def _handle_resources_list(self, request_id: Any) -> Dict:
        """List available resources."""
        stats = self.store.get_stats()
        top_domains = stats.get("top_domains", [])
        
        resources = [
            {
                "uri": "docs://all",
                "name": "All Documentation",
                "description": "Complete knowledge base",
                "mimeType": "text/plain"
            }
        ]
        
        # Add resource for each domain
        for domain_info in top_domains:
            domain = domain_info.get("domain", "")
            count = domain_info.get("count", 0)
            if domain:
                resources.append({
                    "uri": f"docs://{domain}",
                    "name": f"{domain} Documentation",
                    "description": f"{count} documents from {domain}",
                    "mimeType": "text/plain"
                })
        
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "resources": resources
            }
        }
    
    def _handle_resources_read(self, request_id: Any, params: Dict) -> Dict:
        """Read resource content."""
        uri = params.get("uri", "")
        
        if uri == "docs://all":
            # Get all docs
            docs = self.store.get_all_docs()
            
            if not docs:
                content = "No documentation available."
            else:
                # Format as structured text
                parts = [f"Total documents: {len(docs)}\n"]
                for url, doc_content in list(docs.items())[:20]:  # Limit to 20
                    parts.append(f"\n## {url}\n{doc_content[:500]}...\n")
                content = "\n".join(parts)
        
        elif uri.startswith("docs://"):
            # Extract domain
            domain = uri.replace("docs://", "")
            docs_list = self.store.get_docs_by_domain(domain)
            
            if not docs_list:
                content = f"No documents for domain: {domain}"
            else:
                parts = [f"Documents for {domain}:\n"]
                for doc_info in docs_list[:20]:
                    url = doc_info.get("url", "")
                    title = doc_info.get("title", "")
                    parts.append(f"\n- {title or url}")
                content = "\n".join(parts)
        else:
            return self._error_response(request_id, -32602, f"Unknown resource: {uri}")
        
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "text/plain",
                        "text": content
                    }
                ]
            }
        }
    
    def _handle_prompts_list(self, request_id: Any) -> Dict:
        """List available prompts."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "prompts": [
                    {
                        "name": "build_feature",
                        "description": "Help developer implement a feature using documentation",
                        "arguments": [
                            {
                                "name": "feature",
                                "description": "Feature description",
                                "required": True
                            }
                        ]
                    },
                    {
                        "name": "debug_code",
                        "description": "Debug code using documentation",
                        "arguments": [
                            {
                                "name": "code",
                                "description": "Code to debug",
                                "required": True
                            },
                            {
                                "name": "error",
                                "description": "Error message",
                                "required": False
                            }
                        ]
                    },
                    {
                        "name": "explain_api",
                        "description": "Explain API or concept",
                        "arguments": [
                            {
                                "name": "api_name",
                                "description": "API name",
                                "required": True
                            }
                        ]
                    }
                ]
            }
        }
    
    def _handle_prompts_get(self, request_id: Any, params: Dict) -> Dict:
        """Get prompt with documentation context."""
        prompt_name = params.get("name", "")
        arguments = params.get("arguments", {})
        
        if prompt_name == "build_feature":
            feature = arguments.get("feature", "")
            
            # Search for relevant docs and code
            docs = self.store.search_docs(feature, limit=3)
            code = self.store.search_code(feature, limit=2)
            
            context = self._format_context(docs, code)
            
            prompt_text = f"""Task: Implement {feature}

{context}

Please:
1. Review the documentation and code examples above
2. Design a clean implementation
3. Write production-ready code with error handling
4. Add comments explaining key decisions
5. Suggest tests if applicable

Implementation:"""
            
            return self._create_prompt_response(request_id, prompt_text)
        
        elif prompt_name == "debug_code":
            code = arguments.get("code", "")
            error = arguments.get("error", "")
            
            search_query = f"debug {error}" if error else "debugging"
            docs = self.store.search_docs(search_query, limit=2)
            
            context = self._format_context(docs, [])
            
            prompt_text = f"""Debug this code:

```
{code}
```

Error: {error or "Unknown"}

{context}

Please:
1. Identify the issue
2. Explain what's wrong
3. Provide fixed code
4. Suggest how to prevent this"""
            
            return self._create_prompt_response(request_id, prompt_text)
        
        elif prompt_name == "explain_api":
            api_name = arguments.get("api_name", "")
            
            docs = self.store.search_docs(api_name, limit=3)
            code = self.store.search_code(api_name, limit=3)
            
            context = self._format_context(docs, code)
            
            prompt_text = f"""Explain: {api_name}

{context}

Please provide:
1. Overview and purpose
2. Key methods/functions
3. Usage examples
4. Best practices
5. Common pitfalls"""
            
            return self._create_prompt_response(request_id, prompt_text)
        
        return self._error_response(request_id, -32602, f"Unknown prompt: {prompt_name}")
    
    def _format_context(self, docs: List[Dict], code: List[Dict]) -> str:
        """Format documentation and code context."""
        parts = []
        
        if docs:
            parts.append("## Documentation\n")
            for doc in docs:
                url = doc.get("url", "")
                snippet = doc.get("snippet", "")
                parts.append(f"### {url}\n{snippet[:300]}...\n")
        
        if code:
            parts.append("\n## Code Examples\n")
            for block in code:
                lang = block.get("language", "")
                snippet = block.get("snippet", "")
                context = block.get("context", "")
                parts.append(f"```{lang}\n// {context}\n{snippet[:400]}\n```\n")
        
        return "\n".join(parts) if parts else "No relevant documentation found."
    
    def _create_prompt_response(self, request_id: Any, prompt_text: str) -> Dict:
        """Create prompt response."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": prompt_text
                        }
                    }
                ]
            }
        }
    
    def _error_response(self, request_id: Any, code: int, message: str) -> Dict:
        """Create error response."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message
            }
        }


# Flask app for deployment
app = Flask(__name__)
CORS(app)

# Create server instance
mcp_server = ProductionMCPServer(use_sqlite=True)


@app.route("/api/mcp", methods=["GET", "POST"])
def mcp_endpoint():
    """MCP server endpoint."""
    
    if request.method == "GET":
        stats = mcp_server.store.get_stats()
        return jsonify({
            "status": "running",
            "server": mcp_server.name,
            "version": mcp_server.version,
            "stats": stats
        })
    
    try:
        data = request.json
        
        if not data:
            return jsonify({
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32700,
                    "message": "Parse error"
                }
            }), 400
        
        response = mcp_server.handle_request(data)
        return jsonify(response)
        
    except Exception as e:
        return jsonify({
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": -32603,
                "message": f"Internal error: {str(e)}"
            }
        }), 500


@app.route("/api/health", methods=["GET"])
def health_check():
    """Health check."""
    return jsonify({
        "status": "healthy",
        "server": mcp_server.name,
        "version": mcp_server.version
    })


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)
