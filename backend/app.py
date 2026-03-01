from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import os
from dotenv import load_dotenv
import subprocess
import sys

load_dotenv()

app = Flask(__name__)
CORS(app)

@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'message': 'Scrapee API is running'}), 200

@app.route('/api/scrape', methods=['POST'])
def scrape():
    """
    Main scraping endpoint
    Expected JSON body:
    {
        "urls": ["url1", "url2"],
        "mode": "fast" | "detailed",
        "output_format": "json" | "csv"
    }
    """
    try:
        data = request.get_json()
        
        if not data or 'urls' not in data:
            return jsonify({'error': 'URLs are required'}), 400
        
        urls = data.get('urls', [])
        mode = data.get('mode', 'fast')
        output_format = data.get('output_format', 'json')
        
        if not isinstance(urls, list) or len(urls) == 0:
            return jsonify({'error': 'URLs must be a non-empty list'}), 400
        
        # Here you would integrate with your scraper
        # For now, returning a mock response
        results = {
            'status': 'success',
            'mode': mode,
            'urls_processed': len(urls),
            'output_format': output_format,
            'data': []
        }
        
        return jsonify(results), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/scrape/history', methods=['GET'])
def get_history():
    """Get scraping history"""
    try:
        if os.path.exists('scraped_output.json'):
            with open('scraped_output.json', 'r') as f:
                data = json.load(f)
            return jsonify(data), 200
        else:
            return jsonify({'data': []}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/scrape/validate-urls', methods=['POST'])
def validate_urls():
    """Validate URLs before scraping"""
    try:
        data = request.get_json()
        urls = data.get('urls', [])
        
        results = []
        for url in urls:
            is_valid = url.startswith(('http://', 'https://'))
            results.append({
                'url': url,
                'valid': is_valid
            })
        
        return jsonify({'results': results}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    debug = os.getenv('FLASK_DEBUG', 'False') == 'True'
    port = int(os.getenv('FLASK_PORT', 5000))
    app.run(debug=debug, host='0.0.0.0', port=port)
