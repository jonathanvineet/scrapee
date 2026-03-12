"""
Vercel API handler for Flask app
Maps Vercel serverless functions to Flask routes
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app

# Export app for Vercel
__all__ = ['app']

# For Vercel serverless functions
def handler(request):
    """Vercel serverless function handler"""
    return app(request.environ, request.start_response)
