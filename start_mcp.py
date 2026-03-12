#!/usr/bin/env python3
"""
Quick Start Script for Production MCP Server
Initializes database and starts the server.
"""
import os
import sys
import subprocess

# Add backend to path
backend_dir = os.path.join(os.path.dirname(__file__), 'backend')
sys.path.insert(0, backend_dir)

print("🚀 Starting Production MCP Server...\n")

# Check Python version
if sys.version_info < (3, 8):
    print("❌ Error: Python 3.8+ required")
    sys.exit(1)

print(f"✓ Python {sys.version_info.major}.{sys.version_info.minor}")

# Check dependencies
try:
    import flask
    import flask_cors
    import requests
    import bs4
    import sklearn
    print("✓ Dependencies installed")
except ImportError as e:
    print(f"❌ Missing dependency: {e}")
    print("\nInstall with: pip install -r backend/requirements.txt")
    sys.exit(1)

# Create database directory
db_dir = os.path.join(backend_dir, 'db')
os.makedirs(db_dir, exist_ok=True)
print(f"✓ Database directory: {db_dir}")

# Initialize server (will create database)
print("\n📦 Initializing server and database...")
from api.mcp import ProductionMCPServer

try:
    server = ProductionMCPServer(use_sqlite=True)
    print("✓ Server initialized")
    print(f"✓ Database: {server.store.db_path}")
    
    stats = server.store.get_stats()
    print(f"✓ Documents: {stats['total_docs']}")
    print(f"✓ Code blocks: {stats['total_code_blocks']}")
    
except Exception as e:
    print(f"❌ Initialization failed: {e}")
    sys.exit(1)

# Instructions
print("\n" + "="*60)
print("Production MCP Server Ready!")
print("="*60)

print("\n📖 Quick Start:\n")
print("1. Start the server:")
print("   cd backend")
print("   python api/mcp.py")
print("\n2. Connect to VS Code:")
print("   Add to .vscode/mcp.json:")
print('   {')
print('     "servers": {')
print('       "scrapee": {')
print('         "command": "python",')
print(f'         "args": ["{os.path.join(os.getcwd(), "backend/api/mcp.py")}"]')
print('       }')
print('     }')
print('   }')
print("\n3. Test the server:")
print("   python test_mcp_production.py")

print("\n📚 Documentation:")
print("   See MCP_README.md for complete guide")

print("\n🎯 Example Usage:")
print("   # In VS Code, ask Copilot:")
print('   "How do I create a Hedera token?"')
print("   # Copilot will automatically query the MCP!")

print("\n✨ Features:")
print("   ✓ SQLite storage with FTS5 indexing")
print("   ✓ Code block extraction and search")
print("   ✓ Security (domain allowlist)")
print("   ✓ Caching for performance")
print("   ✓ Comprehensive tools and prompts")

print("\n" + "="*60 + "\n")

# Offer to start server
response = input("Start server now? (y/n): ").strip().lower()
if response == 'y':
    print("\n🌐 Starting server on http://localhost:5001")
    print("Press Ctrl+C to stop\n")
    
    # Change to backend directory and start server
    os.chdir(backend_dir)
    try:
        subprocess.run([sys.executable, "api/mcp.py"])
    except KeyboardInterrupt:
        print("\n\n✓ Server stopped")
