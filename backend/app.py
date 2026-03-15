from flask import Flask, request, jsonify
from flask_cors import CORS
import os
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from mcp import (
    IMPORT_ERRORS,
    SCRAPE_TIMEOUT_SECONDS,
    SELENIUM_AVAILABLE,
    SMART_CRAWLER_AVAILABLE,
    ULTRAFAST_AVAILABLE,
    SeleniumCrawler,
    SmartCrawler,
    UltraFastCrawler,
    mcp_server,
)
from storage.sqlite_store import get_sqlite_store

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

_import_errors = dict(IMPORT_ERRORS)

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


# ============================================================================
# SQLITE PERSISTENCE LAYER
# ============================================================================

def save_page(url, content, metadata=None):
    """Save scraped page content to SQLite.
    
    Args:
        url: The page URL (will be normalized)
        content: Text content of the page
        metadata: Optional dict with title, paragraphs, etc.
    """
    normalized = normalize_url(url)
    return get_sqlite_store().save_doc(normalized, content, metadata=metadata or {})


def get_page(url):
    """Retrieve page content from SQLite.
    
    Args:
        url: The page URL (will be normalized)
        
    Returns:
        String content or None if not found
    """
    normalized = normalize_url(url)
    page = get_sqlite_store().get_doc(normalized)
    return page.get("content") if page else None


def list_all_pages():
    """List all indexed page URLs.
    
    Returns:
        List of normalized URLs
    """
    return get_sqlite_store().list_docs()


def search_pages(query, top_k=5):
    """Search pages using SQLite FTS5.
    
    Args:
        query: Search query string
        top_k: Number of results to return
        
    Returns:
        List of matching URLs, ranked by relevance
    """
    return [result["url"] for result in get_sqlite_store().search_docs(query, limit=top_k)]


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
    return get_sqlite_store().search_and_get(query, limit=k, snippet_length=snippet_length)


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

    store = get_sqlite_store()
    stats = store.get_stats()
    status_code = 200 if stats.get('sqlite_ok') else 503
    return jsonify({
        'status': 'ok' if stats.get('sqlite_ok') else 'degraded',
        'storage': 'sqlite',
        'sqlite': {
            'status': 'ok' if stats.get('sqlite_ok') else 'error',
            'path': stats.get('db_path')
        },
        'docs': stats.get('total_docs', 0),
        'code_blocks': stats.get('total_code_blocks', 0),
        'crawlers': {
            'smart': SMART_CRAWLER_AVAILABLE,
            'selenium': SELENIUM_AVAILABLE,
            'ultrafast': ULTRAFAST_AVAILABLE,
        },
        'import_errors': _import_errors,
        'environment': {
            'flask_env': os.getenv('FLASK_ENV', 'production'),
            'port': os.getenv('PORT', '5001'),
            'vercel': bool(os.getenv('VERCEL')),
            'vercel_url': os.getenv('VERCEL_URL'),
            'scrape_timeout_seconds': SCRAPE_TIMEOUT_SECONDS,
            'database_path': stats.get('db_path')
        }
    }), status_code


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
    """Proxy MCP JSON-RPC requests to the shared backend server."""
    if request.method != 'POST':
        return jsonify({'error': 'MCP endpoint expects POST JSON-RPC requests'}), 405

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({
            'jsonrpc': '2.0',
            'error': {'code': -32700, 'message': 'Parse error'}
        }), 400

    response = mcp_server.handle_request(data)
    if response is None:
        return '', 204
    return jsonify(response)


if __name__ == '__main__':
    # Preload default docs on startup
    preload_docs()
    
    debug = os.getenv('FLASK_DEBUG', 'False') == 'True'
    port = int(os.getenv('FLASK_PORT', 8080))
    app.run(debug=debug, host='0.0.0.0', port=port)

