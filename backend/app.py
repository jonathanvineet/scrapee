from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import os
import sys
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

load_dotenv()

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

# Global history storage for scraped pages (keyed by URL)
_history = {}
SCRAPED_PAGES = {}  # For MCP server

# TF-IDF based semantic search (lightweight, Vercel-compatible)
_vectorizer = None
_tfidf_matrix = None
DOC_INDEX = []


def get_vectorizer():
    """Get or create TF-IDF vectorizer (lazy-init)."""
    global _vectorizer
    if _vectorizer is None:
        _vectorizer = TfidfVectorizer(max_features=1000, stop_words='english')
    return _vectorizer


def semantic_search(query, top_k=3):
    """Return top_k URLs most similar to query using TF-IDF cosine similarity."""
    global _tfidf_matrix
    
    if not DOC_INDEX:
        return []

    try:
        vectorizer = get_vectorizer()
        
        # If matrix not built yet, build it from all doc contents
        if _tfidf_matrix is None:
            doc_texts = [SCRAPED_PAGES.get(url, {}).get('content', '') for url in DOC_INDEX]
            _tfidf_matrix = vectorizer.fit_transform(doc_texts)
        
        # Transform query to TF-IDF vector
        query_vec = vectorizer.transform([query])
        
        # Compute cosine similarities
        sims = cosine_similarity(query_vec, _tfidf_matrix)[0]
        
        # Get top_k indices
        top_indices = np.argsort(sims)[::-1][:top_k]
        
        return [DOC_INDEX[i] for i in top_indices if sims[i] > 0]
    
    except Exception:
        return []

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


@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'ok',
        'message': 'Scrapee API is running',
        'import_errors': _import_errors,
        'crawlers': {
            'SeleniumCrawler': SeleniumCrawler is not None,
            'SmartCrawler': SmartCrawler is not None,
            'UltraFastCrawler': UltraFastCrawler is not None,
        }
    }), 200


@app.route('/api/scrape', methods=['POST'])
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
    try:
        data = request.get_json()
        if not data or 'urls' not in data:
            return jsonify({'error': 'urls is required'}), 400

        urls = data.get('urls', [])
        mode = data.get('mode', 'smart')
        max_depth = int(data.get('max_depth', 1))
        output_format = data.get('output_format', 'json')

        if not isinstance(urls, list) or len(urls) == 0:
            return jsonify({'error': 'urls must be a non-empty list'}), 400

        all_results = []

        for start_url in urls:
            try:
                if mode == 'fast':
                    if SeleniumCrawler is None:
                        return jsonify({'error': f"SeleniumCrawler failed to import: {_import_errors.get('selenium_crawler')}"}), 500
                    crawler = SeleniumCrawler(start_url=start_url, max_depth=max_depth)
                elif mode == 'pipeline':
                    if UltraFastCrawler is None:
                        return jsonify({'error': f"UltraFastCrawler failed to import: {_import_errors.get('pipeline_crawler')}"}), 500
                    crawler = UltraFastCrawler(start_url=start_url, max_depth=max_depth, max_workers=8)
                else:  # smart (default)
                    if SmartCrawler is None:
                        return jsonify({'error': f"SmartCrawler failed to import: {_import_errors.get('smart_crawler')}"}), 500
                    crawler = SmartCrawler(start_url=start_url, max_depth=max_depth)

                raw = crawler.crawl()  # {url: html, ...}

                for page_url, html in raw.items():
                    parsed = parse_html(page_url, html, mode)
                    all_results.append(parsed)
                    # Store in history for MCP access
                    _history[page_url] = parsed
                    # Store in SCRAPED_PAGES for MCP server
                    content_text = parsed.get('title', '') + " "

                    for p in parsed.get('paragraphs', [])[:10]:
                        content_text += p + " "

                    SCRAPED_PAGES[page_url] = {"content": content_text}

                    # Index for semantic search (no embedding needed, just store URL)
                    if page_url not in DOC_INDEX:
                        DOC_INDEX.append(page_url)

            except RuntimeError as e:
                # Selenium not available in this environment
                return jsonify({'error': str(e)}), 422
            except Exception as e:
                all_results.append({'url': start_url, 'error': str(e)})

        return jsonify({
            'status': 'success',
            'mode': mode,
            'urls_processed': len(urls),
            'pages_scraped': len(all_results),
            'output_format': output_format,
            'data': all_results
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


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
                        'name': 'search_docs',
                        'description': 'Search scraped documentation',
                        'inputSchema': {
                            'type': 'object',
                            'properties': {
                                'query': {'type': 'string'}
                            },
                            'required': ['query']
                        }
                    },

                    {
                        'name': 'get_doc',
                        'description': 'Get documentation content',
                        'inputSchema': {
                            'type': 'object',
                            'properties': {
                                'url': {'type': 'string'}
                            },
                            'required': ['url']
                        }
                    },

                    {
                        'name': 'list_docs',
                        'description': 'List all scraped docs',
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
        # list_docs: returns all indexed doc URLs
        if tool == 'list_docs':
            return jsonify({
                'jsonrpc': '2.0',
                'id': request_id,
                'result': {
                    'content': [
                        {'type': 'text', 'text': "\n".join(DOC_INDEX)}
                    ]
                }
            })

        # search_docs: semantic search over indexed docs
        if tool == 'search_docs':
            query = arguments.get('query', '')
            results = semantic_search(query)
            return jsonify({
                'jsonrpc': '2.0',
                'id': request_id,
                'result': {
                    'content': [
                        {'type': 'text', 'text': "\n".join(results)}
                    ]
                }
            })

        # get_doc: return a document's stored content
        if tool == 'get_doc':
            url = arguments.get('url')
            page = SCRAPED_PAGES.get(url)
            text = page['content'] if page else 'Document not found'

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
            page = SCRAPED_PAGES.get(url)

            if not page:
                try:
                    crawler = SmartCrawler(start_url=url, max_depth=0)
                    raw = crawler.crawl()

                    for page_url, html in raw.items():
                        parsed = parse_html(page_url, html, "smart")
                        content_text = parsed.get('title', '') + " "
                        for p in parsed.get('paragraphs', [])[:10]:
                            content_text += p + " "
                        SCRAPED_PAGES[page_url] = {"content": content_text}
                        try:
                            if page_url not in DOC_INDEX:
                                DOC_INDEX.append(page_url)
                        except Exception:
                            pass

                    page = SCRAPED_PAGES.get(url)

                except Exception as e:
                    return jsonify({
                        'jsonrpc': '2.0',
                        'id': request_id,
                        'error': {
                            'code': -32000,
                            'message': str(e)
                        }
                    })

            text = page['content'] if page else 'Failed to scrape page'
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
    debug = os.getenv('FLASK_DEBUG', 'False') == 'True'
    port = int(os.getenv('FLASK_PORT', 8080))
    app.run(debug=debug, host='0.0.0.0', port=port)

