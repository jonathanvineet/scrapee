from flask import Flask, request, jsonify
from flask_cors import CORS
import os
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from selenium_crawler import SeleniumCrawler
from smart_crawler import SmartCrawler
from pipeline_crawler import UltraFastCrawler

load_dotenv()

app = Flask(__name__)
CORS(app)


def parse_html(url, html, mode):
    """Parse raw HTML into structured data."""
    soup = BeautifulSoup(html, 'html.parser')

    # Links — always extracted
    links = []
    for tag in soup.find_all('a', href=True):
        href = urljoin(url, tag['href'])
        if href.startswith('http'):
            links.append({
                'url': href.rstrip('/'),
                'text': tag.get_text(strip=True) or href
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
            if text:
                headings.append({'level': tag.name, 'text': text})

        paragraphs = []
        for p in soup.find_all('p'):
            text = p.get_text(strip=True)
            if len(text) > 40:
                paragraphs.append(text)

        images = []
        for img in soup.find_all('img', src=True):
            src = urljoin(url, img['src'])
            alt = img.get('alt', '')
            images.append({'src': src, 'alt': alt})

        result['meta_description'] = meta_desc
        result['headings'] = headings[:30]
        result['paragraphs'] = paragraphs[:30]
        result['images'] = images[:30]

    return result


@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'message': 'Scrapee API is running'}), 200


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
                    crawler = SeleniumCrawler(start_url=start_url, max_depth=max_depth)
                elif mode == 'pipeline':
                    crawler = UltraFastCrawler(start_url=start_url, max_depth=max_depth, max_workers=8)
                else:  # smart (default)
                    crawler = SmartCrawler(start_url=start_url, max_depth=max_depth)

                raw = crawler.crawl()  # {url: html, ...}

                for page_url, html in raw.items():
                    parsed = parse_html(page_url, html, mode)
                    all_results.append(parsed)

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
    return jsonify({'data': []}), 200


if __name__ == '__main__':
    debug = os.getenv('FLASK_DEBUG', 'False') == 'True'
    port = int(os.getenv('FLASK_PORT', 5000))
    app.run(debug=debug, host='0.0.0.0', port=port)

