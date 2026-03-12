from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import os
import sys
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

load_dotenv()


def normalize_url(url):
    """Normalize URL by removing trailing slashes and standardizing format.
    
    This ensures consistent URL matching across scraping and retrieval.
    Example: 'https://example.com/page/' -> 'https://example.com/page'
    """
    if not url:
        return url
    parsed = urlparse(url)
    # Reconstruct URL without trailing slash on path
    normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
    if parsed.query:
        normalized += f"?{parsed.query}"
    if parsed.fragment:
        normalized += f"#{parsed.fragment}"
    return normalized


# Redis client setup for persistent storage (Vercel-compatible)
redis_client = None
try:
    import redis
    
    redis_url = os.getenv('REDIS_URL')
    if redis_url:
        redis_client = redis.from_url(redis_url, decode_responses=True)
    else:
        # Fallback to individual connection params
        redis_host = os.getenv('REDIS_HOST', 'localhost')
        redis_port = int(os.getenv('REDIS_PORT', 6379))
        redis_password = os.getenv('REDIS_PASSWORD')
        
        redis_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            password=redis_password,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5
        )
        # Test connection
        redis_client.ping()
except Exception as e:
    _import_errors = {}
    _import_errors['redis'] = str(e)
    redis_client = None

# Track import errors
_import_errors = {}

try:
    from selenium_crawler import SeleniumCrawler
except Exception as e:
    _import_errors['selenium_crawler'] = str(e)
    SeleniumCrawler = None

try:
    from smart_crawler import SmartCrawler
except Exception as e:
    _import_errors['smart_crawler'] = str(e)
    SmartCrawler = None

try:
    from pipeline_crawler import UltraFastCrawler
except Exception as e:
    _import_errors['pipeline_crawler'] = str(e)
    UltraFastCrawler = None

app = Flask(__name__)

# Enable CORS for all routes
CORS(app, resources={
    r"/api/*": {
        "origins": ["*"],
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
        "expose_headers": ["Content-Type"]
    },
    r"/mcp*": {
        "origins": ["*"],
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    }
})

# Global history storage for scraped pages (keyed by URL)
_history = {}
SCRAPED_PAGES = {}  # For MCP server (fallback if Redis unavailable)

# TF-IDF based semantic search (lightweight, Vercel-compatible)
_vectorizer = None
_tfidf_matrix = None
DOC_INDEX = []


# ============================================================================
# REDIS PERSISTENCE LAYER
# ============================================================================

def save_page(url, content, metadata=None):
    """Save scraped page content to Redis with fallback to memory.
    
    Args:
        url: The page URL (will be normalized)
        content: Text content of the page
        metadata: Optional dict with title, paragraphs, etc.
    """
    normalized = normalize_url(url)
    
    if redis_client:
        try:
            # Store content
            redis_client.set(f"page:{normalized}", content)
            
            # Store metadata if provided
            if metadata:
                import json
                redis_client.set(f"meta:{normalized}", json.dumps(metadata))
            
            # Add to index
            redis_client.sadd("doc_index", normalized)
            return True
        except Exception as e:
            print(f"Redis save error: {e}")
            # Fallback to memory
    
    # Fallback: use in-memory storage
    SCRAPED_PAGES[normalized] = {"content": content}
    if normalized not in DOC_INDEX:
        DOC_INDEX.append(normalized)
    return False


def get_page(url):
    """Retrieve page content from Redis or memory.
    
    Args:
        url: The page URL (will be normalized)
        
    Returns:
        String content or None if not found
    """
    normalized = normalize_url(url)
    
    if redis_client:
        try:
            content = redis_client.get(f"page:{normalized}")
            if content:
                return content
        except Exception as e:
            print(f"Redis get error: {e}")
    
    # Fallback to memory
    page = SCRAPED_PAGES.get(normalized)
    return page.get("content") if page else None


def list_all_pages():
    """List all indexed page URLs.
    
    Returns:
        List of normalized URLs
    """
    if redis_client:
        try:
            urls = redis_client.smembers("doc_index")
            return list(urls) if urls else []
        except Exception as e:
            print(f"Redis list error: {e}")
    
    # Fallback to memory
    return DOC_INDEX.copy()


def search_pages(query, top_k=5):
    """Search pages using TF-IDF cosine similarity.
    
    Args:
        query: Search query string
        top_k: Number of results to return
        
    Returns:
        List of matching URLs, ranked by relevance
    """
    all_urls = list_all_pages()
    
    if not all_urls:
        return []
    
    try:
        # Get all page contents
        contents = []
        valid_urls = []
        
        for url in all_urls:
            content = get_page(url)
            if content:
                contents.append(content)
                valid_urls.append(url)
        
        if not contents:
            return []
        
        # TF-IDF search
        vectorizer = get_vectorizer()
        tfidf_matrix = vectorizer.fit_transform(contents)
        query_vec = vectorizer.transform([query])
        
        similarities = cosine_similarity(query_vec, tfidf_matrix)[0]
        top_indices = np.argsort(similarities)[::-1][:top_k]
        
        return [valid_urls[i] for i in top_indices if similarities[i] > 0]
    
    except Exception as e:
        print(f"Search error: {e}")
        return []


def search_and_get(query, k=3, snippet_length=1000):
    """Combined search and retrieve: reduces MCP tool calls from 2+ to 1.
    
    This is the recommended approach for production MCP servers.
    Instead of: search_docs → get_doc → get_doc → get_doc
    You get:    search_and_get → done (all results with snippets)
    
    Args:
        query: Search query string
        k: Number of top results to return (default 3)
        snippet_length: Max chars per snippet (default 1000)
        
    Returns:
        List of dicts with {url, title, snippet, full_content_available}
    """
    urls = search_pages(query, top_k=k)
    
    if not urls:
        return []
    
    results = []
    for url in urls:
        content = get_page(url)
        if content:
            # Extract title (first line usually)
            lines = content.split('\n')
            title = lines[0] if lines else url
            
            # Create snippet
            snippet = content[:snippet_length]
            if len(content) > snippet_length:
                snippet += "..."
            
            results.append({
                "url": url,
                "title": title,
                "snippet": snippet,
                "full_content_length": len(content)
            })
    
    return results


def get_vectorizer():
    """Get or create TF-IDF vectorizer (lazy-init)."""
    global _vectorizer
    if _vectorizer is None:
        _vectorizer = TfidfVectorizer(max_features=1000, stop_words='english')
    return _vectorizer


# ============================================================================
# PRELOAD DEFAULT DOCUMENTATION
# ============================================================================

DEFAULT_DOCS = [
    "https://docs.hedera.com/hedera/getting-started",
    "https://docs.hedera.com/hedera/sdks-and-apis/sdks/token-service/define-a-token",
    "https://docs.hedera.com/hedera/sdks-and-apis/sdks/token-service/transfer-tokens",
]


def preload_docs():
    """Preload default documentation into Redis on startup.
    
    This ensures MCP server has data available immediately without
    requiring manual scraping first.
    """
    if not SmartCrawler:
        print("SmartCrawler not available, skipping preload")
        return
    
    print("Preloading default documentation...")
    preloaded = 0
    
    for url in DEFAULT_DOCS:
        # Check if already loaded
        if get_page(url):
            print(f"  ✓ Already loaded: {url}")
            continue
        
        try:
            print(f"  → Scraping: {url}")
            crawler = SmartCrawler(start_url=url, max_depth=0)
            raw = crawler.crawl()
            
            for page_url, html in raw.items():
                parsed = parse_html(page_url, html, "smart")
                
                content_text = parsed.get('title', '') + "\n\n"
                for p in parsed.get('paragraphs', [])[:20]:
                    content_text += p + "\n"
                
                save_page(page_url, content_text, metadata=parsed)
                preloaded += 1
                print(f"  ✓ Saved: {page_url}")
        
        except Exception as e:
            print(f"  ✗ Failed to preload {url}: {e}")
    
    print(f"Preloading complete: {preloaded} pages loaded")


# Configure CORS for local development and production (Vercel)
allowed_origins = [
    'http://localhost:3000',           # Local frontend
    'http://localhost:8080',           # Local backend proxy
    'http://127.0.0.1:3000',           # Local frontend (127.0.0.1)
    'https://localhost:3000',          # Local frontend (HTTPS)
    'https://scrapee-wine.vercel.app', # Production frontend
    'https://scrapee.vercel.app',      # Alternative production frontend
]

# Add production origins from environment variables if provided
vercel_url = os.getenv('VERCEL_URL')
frontend_url = os.getenv('FRONTEND_URL')
if vercel_url:
    allowed_origins.append(f'https://{vercel_url}')
    allowed_origins.append(f'http://{vercel_url}')  # Non-HTTPS for staging

if frontend_url:
    allowed_origins.append(frontend_url)

# Development mode: allow all origins (easier debugging)
flask_env = os.getenv('FLASK_ENV', 'development')
if flask_env == 'development':
    allowed_origins = '*'

# Configure CORS with explicit settings
cors_config = {
    "origins": allowed_origins,
    "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    "allow_headers": ["Content-Type", "Authorization"],
    "expose_headers": ["Content-Type"],
    "supports_credentials": True,
    "max_age": 3600
}

CORS(app, resources={
    r"/api/*": cors_config,
    r"/mcp/*": cors_config
})


def parse_html(url, html, mode):
    """Parse raw HTML into structured data with boilerplate filtering."""
    soup = BeautifulSoup(html, 'html.parser')

    # Common boilerplate/utility keywords to filter out
    JUNK_KEYWORDS = [
        'sign in', 'login', 'log in', 'logout', 'sign out', 'sign up', 'register', 
        'create account', 'my account', 'privacy policy', 'terms of service', 
        'terms of use', 'contact us', 'careers', 'jobs', 'about us', 'newsletter', 
        'subscribe', 'cookie policy', 'site map', 'sitemap', 'help center', 
        'support', 'faq', 'copyright', 'all rights reserved', 'advertisement', 'sponsor',
        'facebook', 'twitter', 'instagram', 'linkedin', 'youtube', 'tiktok', 'pinterest',
        'logo', 'icon', 'avatar'
    ]

    def is_junk(text):
        if not text:
            return False
        low = text.lower().strip()
        # Check if the text matches any junk keyword
        return any(kw in low for kw in JUNK_KEYWORDS)

    # Links — always extracted
    links = []
    for tag in soup.find_all('a', href=True):
        href = urljoin(url, tag['href'])
        text = tag.get_text(strip=True)
        
        # Skip junk links (by text or by URL fragment)
        if is_junk(text) or is_junk(href):
            continue
            
        if href.startswith('http'):
            links.append({
                'url': href.rstrip('/'),
                'text': text or href
            })

    result = {
        'url': url,
        'title': soup.title.string.strip() if soup.title and soup.title.string else '',
        'links': links,
        'links_count': len(links),
    }

    if mode in ('fast', 'smart', 'pipeline'):
        meta_desc = ''
        meta = soup.find('meta', attrs={'name': 'description'})
        if meta:
            meta_desc = meta.get('content', '')

        headings = []
        for tag in soup.find_all(['h1', 'h2', 'h3']):
            text = tag.get_text(strip=True)
            if text and not is_junk(text) and len(text) > 2:
                headings.append({'level': tag.name, 'text': text})

        paragraphs = []
        for p in soup.find_all('p'):
            text = p.get_text(strip=True)
            # Filter short or junk paragraphs
            if len(text) > 45 and not is_junk(text):
                paragraphs.append(text)

        images = []
        for img in soup.find_all('img', src=True):
            src = urljoin(url, img['src'])
            alt = img.get('alt', '')
            # Skip images with junk alt text or junk src (social icons etc)
            if is_junk(alt) or is_junk(src):
                continue
            images.append({'src': src, 'alt': alt})

        result['meta_description'] = meta_desc
        result['headings'] = headings[:30]
        result['paragraphs'] = paragraphs[:30]
        result['images'] = images[:30]

    return result


@app.route('/api/debug-scrape', methods=['POST'])
def debug_scrape():
    """Debug endpoint to trace crawl step by step."""
    import traceback
    import requests as req

    data = request.get_json()
    url = data.get('url', 'https://example.com')
    trace = []

    try:
        r = req.get(url, timeout=8, verify=False, headers={'User-Agent': 'Mozilla/5.0 (compatible; Scrapee/1.0)'})
        trace.append({'step': 'fetch', 'status_code': r.status_code, 'html_length': len(r.text)})

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, 'html.parser')
        title = soup.title.string.strip() if soup.title and soup.title.string else ''
        links = [tag['href'] for tag in soup.find_all('a', href=True)]
        trace.append({'step': 'parse', 'title': title, 'links_count': len(links), 'sample_links': links[:5]})

        # Now try SmartCrawler directly
        crawler = SmartCrawler(start_url=url, max_depth=0)
        result = crawler.crawl()
        trace.append({'step': 'smart_crawler', 'pages_returned': len(result), 'urls': list(result.keys())})

    except Exception as e:
        trace.append({'step': 'error', 'error': str(e), 'traceback': traceback.format_exc()})

    return jsonify({'trace': trace}), 200


@app.route('/api/health', methods=['GET', 'OPTIONS'])
def health():
    """Health check endpoint."""
    if request.method == 'OPTIONS':
        return '', 204
    
    return jsonify({
        'status': 'healthy',
        'message': 'Scrapee API is running',
        'import_errors': _import_errors,
        'crawlers': {
            'SeleniumCrawler': SeleniumCrawler is not None,
            'SmartCrawler': SmartCrawler is not None,
            'UltraFastCrawler': UltraFastCrawler is not None,
        }
    }), 200


@app.route('/api/scrape', methods=['POST', 'OPTIONS'])
def scrape():
    """
    POST /api/scrape
    {
        "urls": ["https://example.com"],
        "mode": "fast" | "smart" | "pipeline",
        "max_depth": 1,
        "output_format": "json"
    }
    Modes:
      fast     → SeleniumCrawler (pure Selenium, full JS render)
      smart    → SmartCrawler (requests first, Selenium fallback for JS-heavy pages)
      pipeline → UltraFastCrawler (threaded, requests first, Selenium fallback)
    """
    if request.method == 'OPTIONS':
        return '', 204
    try:
        data = request.get_json()
        if not data or 'urls' not in data:
            return jsonify({'error': 'urls is required', 'status': 'failed'}), 400

        urls = data.get('urls', [])
        mode = data.get('mode', 'smart')
        max_depth = int(data.get('max_depth', 1))
        output_format = data.get('output_format', 'json')

        if not isinstance(urls, list) or len(urls) == 0:
            return jsonify({'error': 'urls must be a non-empty list', 'status': 'failed'}), 400

        all_results = []

        for start_url in urls:
            try:
                # Validate URL format
                if not start_url.startswith(('http://', 'https://')):
                    all_results.append({'url': start_url, 'error': 'Invalid URL format - must start with http:// or https://', 'status': 'failed'})
                    continue

                if mode == 'fast':
                    if SeleniumCrawler is None:
                        return jsonify({
                            'error': f"SeleniumCrawler not available: {_import_errors.get('selenium_crawler', 'Unknown error')}",
                            'status': 'failed'
                        }), 422
                    crawler = SeleniumCrawler(start_url=start_url, max_depth=max_depth)
                elif mode == 'pipeline':
                    if UltraFastCrawler is None:
                        return jsonify({
                            'error': f"UltraFastCrawler not available: {_import_errors.get('pipeline_crawler', 'Unknown error')}",
                            'status': 'failed'
                        }), 422
                    crawler = UltraFastCrawler(start_url=start_url, max_depth=max_depth, max_workers=8)
                else:  # smart (default)
                    if SmartCrawler is None:
                        return jsonify({
                            'error': f"SmartCrawler not available: {_import_errors.get('smart_crawler', 'Unknown error')}",
                            'status': 'failed'
                        }), 422
                    crawler = SmartCrawler(start_url=start_url, max_depth=max_depth)

                try:
                    # Crawling with timeout protection (Vercel function timeout is ~30s)
                    raw = crawler.crawl()  # {url: html, ...}
                    
                    if not raw:
                        all_results.append({'url': start_url, 'error': 'No content scraped from URL', 'status': 'failed'})
                        continue

                    for page_url, html in raw.items():
                        if not html:
                            all_results.append({'url': page_url, 'error': 'Empty response from URL', 'status': 'failed'})
                            continue
                            
                        parsed = parse_html(page_url, html, mode)
                        all_results.append(parsed)
                        
                        # Store in history for API access
                        _history[page_url] = parsed
                        
                        # Build content text for MCP server
                        content_text = parsed.get('title', '') + "\n\n"
                        for p in parsed.get('paragraphs', [])[:20]:
                            content_text += p + "\n"
                        
                        # Save to Redis (with memory fallback)
                        save_page(page_url, content_text, metadata=parsed)
                        
                except TimeoutError as te:
                    all_results.append({'url': start_url, 'error': f'Request timeout: {str(te)}', 'status': 'timeout'})
                except Exception as crawl_err:
                    all_results.append({'url': start_url, 'error': f'Crawl failed: {str(crawl_err)}', 'status': 'failed'})

            except RuntimeError as e:
                # Selenium not available in this environment
                all_results.append({'url': start_url, 'error': str(e), 'status': 'error'})
            except Exception as e:
                all_results.append({'url': start_url, 'error': str(e), 'status': 'error'})

        return jsonify({
            'status': 'success' if any(r.get('status') != 'failed' for r in all_results if 'status' in r) else 'partial',
            'mode': mode,
            'urls_processed': len(urls),
            'pages_scraped': len([r for r in all_results if 'error' not in r]),
            'output_format': output_format,
            'data': all_results
        }), 200

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        return jsonify({
            'error': str(e),
            'status': 'failed',
            'trace': error_trace if os.getenv('FLASK_ENV') != 'production' else None
        }), 500


@app.route('/api/scrape/validate-urls', methods=['POST'])
def validate_urls():
    try:
        data = request.get_json()
        urls = data.get('urls', [])
        results = [{'url': u, 'valid': u.startswith(('http://', 'https://'))} for u in urls]
        return jsonify({'results': results}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/scrape/history', methods=['GET'])
def get_history():
    return jsonify({'data': list(_history.values())}), 200


@app.route('/mcp', methods=['GET', 'POST'])
def mcp():
    """Full MCP lifecycle handler (initialize, tools/list, tools/call).

    - GET: SSE stream for async notifications (keeps connection alive)
    - POST: JSON-RPC 2.0 requests from MCP client (VS Code)
    """

    # SSE notification stream for VS Code persistent connection
    if request.method == 'GET':
        def event_stream():
            # Send keepalive comments every 30 seconds
            import time
            while True:
                yield ': keepalive\n\n'
                time.sleep(30)
        
        return Response(event_stream(), mimetype='text/event-stream')

    # POST — JSON-RPC requests
    data = request.get_json() or {}
    method = data.get('method')
    request_id = data.get('id')

    # Notifications have no id — just acknowledge them silently
    if request_id is None and method != 'initialize':
        return '', 204

    # MCP INITIALIZE HANDSHAKE
    if method == 'initialize':
        return jsonify({
            'jsonrpc': '2.0',
            'id': request_id,
            'result': {
                'protocolVersion': '2025-03-26',
                'capabilities': {
                    'tools': {}
                },
                'serverInfo': {
                    'name': 'scrapee',
                    'version': '1.0'
                }
            }
        })

    # TOOL DISCOVERY
    if method == 'tools/list':
        return jsonify({
            'jsonrpc': '2.0',
            'id': request_id,
            'result': {
                'tools': [
                    {
                        'name': 'scrape_url',
                        'description': 'Scrape a webpage and store it in the knowledge base',
                        'inputSchema': {
                            'type': 'object',
                            'properties': {
                                'url': {
                                    'type': 'string',
                                    'description': 'The URL to scrape'
                                },
                                'max_depth': {
                                    'type': 'number',
                                    'description': 'Maximum crawl depth (default: 0)',
                                    'default': 0
                                }
                            },
                            'required': ['url']
                        }
                    },
                    
                    {
                        'name': 'search_and_get',
                        'description': 'Search docs and return results with snippets in ONE call (recommended - reduces token cost)',
                        'inputSchema': {
                            'type': 'object',
                            'properties': {
                                'query': {
                                    'type': 'string',
                                    'description': 'Search query'
                                },
                                'k': {
                                    'type': 'number',
                                    'description': 'Number of results (default: 3)',
                                    'default': 3
                                },
                                'snippet_length': {
                                    'type': 'number',
                                    'description': 'Max characters per snippet (default: 1000)',
                                    'default': 1000
                                }
                            },
                            'required': ['query']
                        }
                    },
                    
                    {
                        'name': 'search_docs',
                        'description': 'Search scraped documentation using semantic search (returns URLs only)',
                        'inputSchema': {
                            'type': 'object',
                            'properties': {
                                'query': {
                                    'type': 'string',
                                    'description': 'Search query'
                                }
                            },
                            'required': ['query']
                        }
                    },

                    {
                        'name': 'get_doc',
                        'description': 'Get full documentation content by URL',
                        'inputSchema': {
                            'type': 'object',
                            'properties': {
                                'url': {
                                    'type': 'string',
                                    'description': 'The exact URL of the document'
                                }
                            },
                            'required': ['url']
                        }
                    },

                    {
                        'name': 'list_docs',
                        'description': 'List all URLs in the knowledge base',
                        'inputSchema': {
                            'type': 'object',
                            'properties': {}
                        }
                    }
                ]
            }
        })

    # TOOL EXECUTION
    if method == 'tools/call':
        params = data.get('params', {})
        tool = params.get('name')
        arguments = params.get('arguments', {})
        
        # search_and_get: combined search+retrieval (recommended)
        if tool == 'search_and_get':
            query = arguments.get('query', '')
            k = arguments.get('k', 3)
            snippet_length = arguments.get('snippet_length', 1000)
            
            results = search_and_get(query, k=k, snippet_length=snippet_length)
            
            # Format as markdown for readability
            text = f"Found {len(results)} result(s) for: {query}\n\n"
            for i, res in enumerate(results, 1):
                text += f"**{i}. {res['title']}**\n"
                text += f"URL: {res['url']}\n"
                text += f"Snippet: {res['snippet']}\n"
                text += f"Full content: {res['full_content_length']} chars\n\n"
            
            return jsonify({
                'jsonrpc': '2.0',
                'id': request_id,
                'result': {
                    'content': [{'type': 'text', 'text': text}]
                }
            })
        
        # scrape_url: scrape a webpage and store in knowledge base
        if tool == 'scrape_url':
            url = arguments.get('url')
            max_depth = arguments.get('max_depth', 0)
            
            if not url:
                return jsonify({
                    'jsonrpc': '2.0',
                    'id': request_id,
                    'error': {'code': -32602, 'message': 'URL is required'}
                })
            
            try:
                if SmartCrawler is None:
                    return jsonify({
                        'jsonrpc': '2.0',
                        'id': request_id,
                        'error': {'code': -32000, 'message': 'SmartCrawler not available'}
                    })
                
                crawler = SmartCrawler(start_url=url, max_depth=max_depth)
                raw = crawler.crawl()
                
                scraped_urls = []
                for page_url, html in raw.items():
                    parsed = parse_html(page_url, html, "smart")
                    
                    # Build content
                    content_text = parsed.get('title', '') + "\n\n"
                    for p in parsed.get('paragraphs', [])[:20]:
                        content_text += p + "\n"
                    
                    # Save to Redis/memory
                    save_page(page_url, content_text, metadata=parsed)
                    scraped_urls.append(page_url)
                
                result_text = f"Successfully scraped {len(scraped_urls)} page(s):\n" + "\n".join(scraped_urls)
                
                return jsonify({
                    'jsonrpc': '2.0',
                    'id': request_id,
                    'result': {
                        'content': [{'type': 'text', 'text': result_text}]
                    }
                })
            
            except Exception as e:
                return jsonify({
                    'jsonrpc': '2.0',
                    'id': request_id,
                    'error': {'code': -32000, 'message': f'Scraping failed: {str(e)}'}
                })
        
        # list_docs: returns all indexed doc URLs
        if tool == 'list_docs':
            all_urls = list_all_pages()
            text = "\n".join(all_urls) if all_urls else "No documents in knowledge base"
            
            return jsonify({
                'jsonrpc': '2.0',
                'id': request_id,
                'result': {
                    'content': [{'type': 'text', 'text': text}]
                }
            })

        # search_docs: semantic search over indexed docs
        if tool == 'search_docs':
            query = arguments.get('query', '')
            results = search_pages(query, top_k=5)
            text = "\n".join(results) if results else "No results found"
            
            return jsonify({
                'jsonrpc': '2.0',
                'id': request_id,
                'result': {
                    'content': [{'type': 'text', 'text': text}]
                }
            })

        # get_doc: return a document's stored content
        if tool == 'get_doc':
            url = arguments.get('url')
            content = get_page(url)
            text = content if content else 'Document not found'

            return jsonify({
                'jsonrpc': '2.0',
                'id': request_id,
                'result': {
                    'content': [
                        {'type': 'text', 'text': text}
                    ]
                }
            })

        # Backwards-compatible: get_page_context behaves like get_doc and auto-scrapes if missing
        if tool == 'get_page_context':
            url = arguments.get('url')
            content = get_page(url)

            if not content:
                try:
                    if SmartCrawler is None:
                        return jsonify({
                            'jsonrpc': '2.0',
                            'id': request_id,
                            'error': {'code': -32000, 'message': 'SmartCrawler not available'}
                        })
                    
                    crawler = SmartCrawler(start_url=url, max_depth=0)
                    raw = crawler.crawl()

                    for page_url, html in raw.items():
                        parsed = parse_html(page_url, html, "smart")
                        content_text = parsed.get('title', '') + "\n\n"
                        for p in parsed.get('paragraphs', [])[:20]:
                            content_text += p + "\n"
                        
                        save_page(page_url, content_text, metadata=parsed)

                    content = get_page(url)

                except Exception as e:
                    return jsonify({
                        'jsonrpc': '2.0',
                        'id': request_id,
                        'error': {
                            'code': -32000,
                            'message': str(e)
                        }
                    })

            text = content if content else 'Failed to scrape page'
            return jsonify({
                'jsonrpc': '2.0',
                'id': request_id,
                'result': {
                    'content': [
                        {'type': 'text', 'text': text}
                    ]
                }
            })

    # Method not found — always return HTTP 200 in JSON-RPC
    return jsonify({
        'jsonrpc': '2.0',
        'id': request_id,
        'error': {
            'code': -32601,
            'message': 'Method not found'
        }
    }), 200


if __name__ == '__main__':
    # Preload default docs on startup
    preload_docs()
    
    debug = os.getenv('FLASK_DEBUG', 'False') == 'True'
    port = int(os.getenv('FLASK_PORT', 8080))
    app.run(debug=debug, host='0.0.0.0', port=port)

