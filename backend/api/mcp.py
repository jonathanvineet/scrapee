"""
Model Context Protocol (MCP) Server Implementation
Exposes tools, resources, and prompts for AI agent interaction.
"""
import json
import sys
import os
from typing import Dict, List, Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request, jsonify
from flask_cors import CORS

from storage.redis_store import get_store
from index.vector_search import get_search_engine
from utils.normalize import normalize_url, format_doc_for_context

# Import crawler
try:
    from smart_crawler import SmartCrawler
    CRAWLER_AVAILABLE = True
except ImportError:
    CRAWLER_AVAILABLE = False
    print("⚠ SmartCrawler not available")


class MCPServer:
    """
    Model Context Protocol Server
    
    Implements MCP specification: https://modelcontextprotocol.io/
    
    Capabilities:
    - Tools: search_and_get, scrape_url, list_docs
    - Resources: docs://* (all scraped documentation)
    - Prompts: build_feature, debug_code, explain_api
    """
    
    def __init__(self):
        self.store = get_store()
        self.search = get_search_engine()
        self.version = "1.0.0"
        self.name = "scrapee"
    
    def handle_request(self, data: Dict) -> Dict:
        """
        Handle incoming MCP request.
        
        Args:
            data: JSON-RPC 2.0 request
        
        Returns:
            JSON-RPC 2.0 response
        """
        method = data.get("method")
        request_id = data.get("id")
        params = data.get("params", {})
        
        # Route to appropriate handler
        if method == "initialize":
            return self._handle_initialize(request_id)
        
        elif method == "tools/list":
            return self._handle_tools_list(request_id)
        
        elif method == "tools/call":
            return self._handle_tools_call(request_id, params)
        
        elif method == "resources/list":
            return self._handle_resources_list(request_id)
        
        elif method == "resources/read":
            return self._handle_resources_read(request_id, params)
        
        elif method == "prompts/list":
            return self._handle_prompts_list(request_id)
        
        elif method == "prompts/get":
            return self._handle_prompts_get(request_id, params)
        
        else:
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
        """List available tools."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [
                    {
                        "name": "search_docs",
                        "description": "Search scraped documentation using semantic search. Returns relevant doc snippets.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Search query (e.g., 'how to create smart contract')"
                                },
                                "k": {
                                    "type": "integer",
                                    "description": "Number of results to return (default: 3)",
                                    "default": 3
                                }
                            },
                            "required": ["query"]
                        }
                    },
                    {
                        "name": "scrape_url",
                        "description": "Scrape and store documentation from a URL. Crawls related pages up to max_depth.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "url": {
                                    "type": "string",
                                    "description": "URL to scrape"
                                },
                                "max_depth": {
                                    "type": "integer",
                                    "description": "Maximum crawl depth (default: 1)",
                                    "default": 1
                                }
                            },
                            "required": ["url"]
                        }
                    },
                    {
                        "name": "list_docs",
                        "description": "List all stored documentation URLs in the knowledge base.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {}
                        }
                    },
                    {
                        "name": "get_doc",
                        "description": "Get full content of a specific document by URL.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "url": {
                                    "type": "string",
                                    "description": "Document URL"
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
            if tool_name == "search_docs":
                result = self._tool_search_docs(arguments)
            elif tool_name == "scrape_url":
                result = self._tool_scrape_url(arguments)
            elif tool_name == "list_docs":
                result = self._tool_list_docs(arguments)
            elif tool_name == "get_doc":
                result = self._tool_get_doc(arguments)
            else:
                return self._error_response(request_id, -32602, f"Unknown tool: {tool_name}")
            
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
    
    def _tool_search_docs(self, args: Dict) -> Dict:
        """Search documentation tool."""
        query = args.get("query", "")
        k = args.get("k", 3)
        
        if not query:
            return {"error": "Query parameter is required"}
        
        # Get all docs from storage
        docs = self.store.get_all_docs()
        
        if not docs:
            return {
                "message": "No documents in knowledge base. Use scrape_url to add documentation.",
                "results": []
            }
        
        # Perform semantic search
        results = self.search.search_and_get(query, docs, k=k)
        
        return {
            "query": query,
            "total_docs": len(docs),
            "results": results
        }
    
    def _tool_scrape_url(self, args: Dict) -> Dict:
        """Scrape URL tool."""
        url = args.get("url", "")
        max_depth = args.get("max_depth", 1)
        
        if not url:
            return {"error": "URL parameter is required"}
        
        if not CRAWLER_AVAILABLE:
            return {"error": "Crawler not available in this environment"}
        
        try:
            # Normalize URL
            url = normalize_url(url)
            
            # Create crawler
            crawler = SmartCrawler(start_url=url, max_depth=max_depth)
            
            # Crawl pages
            pages = crawler.crawl()
            
            if not pages:
                return {
                    "error": "No pages scraped. Check URL or crawler configuration.",
                    "url": url
                }
            
            # Parse and store pages
            from bs4 import BeautifulSoup
            stored_count = 0
            
            for page_url, html in pages.items():
                try:
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Extract title
                    title = soup.find('title')
                    title_text = title.get_text(strip=True) if title else ""
                    
                    # Extract text content
                    for script in soup(["script", "style"]):
                        script.decompose()
                    
                    text = soup.get_text(separator='\n', strip=True)
                    
                    # Combine title and content
                    content = f"{title_text}\n\n{text}"
                    
                    # Store in database
                    self.store.save_doc(
                        page_url,
                        content,
                        metadata={"title": title_text, "source_url": url}
                    )
                    
                    stored_count += 1
                    
                except Exception as e:
                    print(f"Error parsing {page_url}: {e}")
                    continue
            
            return {
                "message": f"Successfully scraped and stored {stored_count} pages",
                "url": url,
                "pages_scraped": stored_count,
                "max_depth": max_depth,
                "pages": list(pages.keys())
            }
            
        except Exception as e:
            return {"error": f"Scraping failed: {str(e)}", "url": url}
    
    def _tool_list_docs(self, args: Dict) -> Dict:
        """List documents tool."""
        urls = self.store.list_docs()
        
        return {
            "total": len(urls),
            "urls": urls
        }
    
    def _tool_get_doc(self, args: Dict) -> Dict:
        """Get document tool."""
        url = args.get("url", "")
        
        if not url:
            return {"error": "URL parameter is required"}
        
        doc = self.store.get_doc(url)
        
        if not doc:
            return {"error": f"Document not found: {url}"}
        
        return doc
    
    def _handle_resources_list(self, request_id: Any) -> Dict:
        """List available resources."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "resources": [
                    {
                        "uri": "docs://all",
                        "name": "All scraped documentation",
                        "description": "Combined content of all scraped documentation pages",
                        "mimeType": "text/plain"
                    }
                ]
            }
        }
    
    def _handle_resources_read(self, request_id: Any, params: Dict) -> Dict:
        """Read resource content."""
        uri = params.get("uri", "")
        
        if uri == "docs://all":
            # Get all docs
            docs = self.store.get_all_docs()
            
            if not docs:
                content = "No documentation available. Use scrape_url tool to add documentation."
            else:
                # Combine all docs with formatting
                formatted_docs = [
                    format_doc_for_context(url, content, max_length=2000)
                    for url, content in docs.items()
                ]
                content = "\n\n".join(formatted_docs)
                
                # Truncate if too large (max 50k chars for context window)
                if len(content) > 50000:
                    content = content[:50000] + "\n\n... (truncated)"
            
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
        
        return self._error_response(request_id, -32602, f"Unknown resource: {uri}")
    
    def _handle_prompts_list(self, request_id: Any) -> Dict:
        """List available prompts."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "prompts": [
                    {
                        "name": "build_feature",
                        "description": "Help developer implement a feature using scraped documentation",
                        "arguments": [
                            {
                                "name": "task",
                                "description": "Feature or task to implement",
                                "required": True
                            }
                        ]
                    },
                    {
                        "name": "debug_code",
                        "description": "Debug code using relevant documentation",
                        "arguments": [
                            {
                                "name": "code",
                                "description": "Code snippet to debug",
                                "required": True
                            },
                            {
                                "name": "error",
                                "description": "Error message or description",
                                "required": False
                            }
                        ]
                    },
                    {
                        "name": "explain_api",
                        "description": "Explain an API or concept from scraped documentation",
                        "arguments": [
                            {
                                "name": "api_name",
                                "description": "API or concept name",
                                "required": True
                            }
                        ]
                    }
                ]
            }
        }
    
    def _handle_prompts_get(self, request_id: Any, params: Dict) -> Dict:
        """Get prompt template."""
        prompt_name = params.get("name", "")
        arguments = params.get("arguments", {})
        
        if prompt_name == "build_feature":
            task = arguments.get("task", "")
            
            # Search for relevant docs
            docs = self.store.get_all_docs()
            results = self.search.search_and_get(task, docs, k=3) if docs else []
            
            context = ""
            if results:
                context = "\n\nRelevant documentation:\n"
                for r in results:
                    context += f"\n{r['url']}\n{r['snippet'][:500]}...\n"
            
            prompt_text = f"""Task: {task}

Please help implement this feature using the following approach:

1. Review the relevant documentation below
2. Design the implementation
3. Write clean, production-ready code
4. Include error handling and edge cases
5. Add code comments explaining key decisions
{context}

Begin implementation:"""
            
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "description": f"Implement feature: {task}",
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
        
        elif prompt_name == "debug_code":
            code = arguments.get("code", "")
            error = arguments.get("error", "")
            
            # Search for relevant debugging info
            search_query = f"debug error {error}" if error else "debugging troubleshooting"
            docs = self.store.get_all_docs()
            results = self.search.search_and_get(search_query, docs, k=2) if docs else []
            
            context = ""
            if results:
                context = "\n\nRelevant documentation:\n"
                for r in results:
                    context += f"\n{r['url']}\n{r['snippet'][:400]}...\n"
            
            prompt_text = f"""Debug the following code:

```
{code}
```

Error: {error if error else "Unknown issue"}
{context}

Please:
1. Identify the issue
2. Explain what's wrong
3. Provide corrected code
4. Suggest prevention strategies"""
            
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "description": "Debug code",
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
        
        elif prompt_name == "explain_api":
            api_name = arguments.get("api_name", "")
            
            # Search for API documentation
            docs = self.store.get_all_docs()
            results = self.search.search_and_get(api_name, docs, k=3) if docs else []
            
            context = ""
            if results:
                context = "\n\nDocumentation found:\n"
                for r in results:
                    context += f"\n{r['url']}\n{r['snippet'][:600]}...\n"
            else:
                context = f"\n\nNo documentation found for '{api_name}'. Please scrape relevant documentation first."
            
            prompt_text = f"""Explain: {api_name}
{context}

Please provide:
1. Overview and purpose
2. Key methods/functions
3. Usage examples
4. Common patterns
5. Best practices"""
            
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "description": f"Explain API: {api_name}",
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
        
        return self._error_response(request_id, -32602, f"Unknown prompt: {prompt_name}")
    
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


# Flask application for Vercel deployment
app = Flask(__name__)
CORS(app)

# Create MCP server instance
mcp_server = MCPServer()


@app.route("/api/mcp", methods=["GET", "POST"])
def mcp_endpoint():
    """MCP server endpoint."""
    
    if request.method == "GET":
        # Health check
        return jsonify({
            "status": "running",
            "server": mcp_server.name,
            "version": mcp_server.version,
            "docs_count": len(mcp_server.store.list_docs())
        })
    
    # Handle MCP request
    try:
        data = request.json
        
        if not data:
            return jsonify({
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32700,
                    "message": "Parse error: Invalid JSON"
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
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "server": "scrapee-mcp",
        "version": mcp_server.version
    })


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)
