#!/usr/bin/env python3
"""
Scrapee CLI — Boot system & orchestrator.

Philosophy:
  CLI = orchestrator (loads docs, configures VS Code)
  MCP = intelligence layer (serves context)
  Copilot = reasoner (thinks with context)

Flow:
  scrapee → boot system → detect project → auto-load docs → REPL → /load/status/reset
"""

import sys
import os
import json
import random
import re
from datetime import datetime
from pathlib import Path

try:
    import requests
    import urllib3
    urllib3.disable_warnings()  # Suppress LibreSSL warning
except ImportError:
    print("Error: requests not installed. Run: pip install requests", file=sys.stderr)
    sys.exit(1)

# ==================== CONFIG ====================
VERSION = "3.0.0"

# Real Vercel backend URL (set via env or hardcode)
# Set: export SCRAPEE_BASE_URL="https://scrapee-backend.vercel.app"
MCP_BASE_URL = os.environ.get("SCRAPEE_BASE_URL") or "https://scrapee-api.vercel.app"
VSCODE_CONFIG_PATH = Path(".vscode/mcp.json")
CONTEXT_FILE = Path(".scrapee/context.json")


# ==================== MCP HEALTH CHECK ====================
def check_mcp():
    """
    Verify MCP backend is reachable.
    
    Returns True if health check passes, False otherwise.
    """
    try:
        response = requests.get(f"{MCP_BASE_URL}/api/health", timeout=5)
        return response.status_code == 200
    except:
        return False


# Project → Documentation URL mapping
DOC_MAP = {
    "react": "https://react.dev",
    "vue": "https://vuejs.org",
    "next": "https://nextjs.org/docs",
    "svelte": "https://svelte.dev/docs",
    "angular": "https://angular.io/docs",
    "python": "https://docs.python.org/3/",
    "fastapi": "https://fastapi.tiangolo.com/",
    "django": "https://docs.djangoproject.com/",
    "flask": "https://flask.palletsprojects.com/",
    "rust": "https://doc.rust-lang.org/",
    "go": "https://golang.org/doc/",
    "typescript": "https://www.typescriptlang.org/docs/",
    "nodejs": "https://nodejs.org/docs/",
}

# Import name → DOC_MAP key mapping
IMPORT_MAP = {
    "react": "react",
    "react-dom": "react",
    "next": "next",
    "@next/": "next",
    "vue": "vue",
    "svelte": "svelte",
    "@angular/core": "angular",
    "fastapi": "fastapi",
    "flask": "flask",
    "django": "django",
    "axios": "nodejs",
    "express": "nodejs",
    "numpy": "python",
    "pandas": "python",
    "requests": "python",
    "sqlalchemy": "python",
}

# ==================== BANNER ====================
def show_banner():
    """Display ASCII banner."""
    banner = r"""
                _==/          i     i          \==_
              /XX/            |\___/|            \XX\
            /XXXX\            |XXXXX|            /XXXX\
           |XXXXXX\_         _/XXXXX\_         _/XXXXXX|
          XXXXXXXXXXXxxxxxxxXXXXXXXXXXXxxxxxxxXXXXXXXXXXX
         |XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX|
         XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
         |XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX|
          XXXXXX/^^^^"\XXXXXXXXXXXXXXXXXXXXX/^^^^^\XXXXXX
           |XXX|       \XXX/^^\XXXXX/^^\XXX/       |XXX|
             \XX\       \X/    \XXX/    \X/       /XX/
                "\       "      \X/      "      /"

███████╗ ██████╗ ██████╗  █████╗ ██████╗ ███████╗███████╗
██╔════╝██╔════╝ ██╔══██╗██╔══██╗██╔══██╗██╔════╝██╔════╝
███████╗██║      ██████╔╝███████║██████╔╝█████╗  █████╗  
╚════██║██║      ██╔══██╗██╔══██║██.║.   ██╔══╝  ██╔══╝  
███████║╚██████╗ ██║  ██║██║  ██║██ ║    ███████╗███████╗
╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚══╝    ╚══════╝╚══════╝

scrapee CLI v{} — context engine ready
    """
    print(banner.format(VERSION))


# ==================== PROJECT DETECTION ====================
def detect_project():
    """
    Auto-detect project types in current directory.
    
    Returns list of detected project types (react, python, rust, etc.)
    """
    detected = []
    files = set(os.listdir("."))
    
    # Frontend frameworks
    if "package.json" in files:
        # Read to see what's in dependencies
        try:
            with open("package.json") as f:
                pkg = json.load(f)
                deps = pkg.get("dependencies", {})
                
                if "react" in deps or "react-dom" in deps:
                    detected.append("react")
                elif "vue" in deps:
                    detected.append("vue")
                elif "next" in deps:
                    detected.append("next")
                elif "@angular/core" in deps:
                    detected.append("angular")
                elif "svelte" in deps:
                    detected.append("svelte")
                
                # Also add Node.js generically
                if "nodejs" not in detected:
                    detected.append("nodejs")
        except:
            detected.append("nodejs")
    
    # Python
    if "requirements.txt" in files or "pyproject.toml" in files or "setup.py" in files:
        try:
            if "requirements.txt" in files:
                with open("requirements.txt") as f:
                    reqs = f.read()
                    
                    if "fastapi" in reqs:
                        detected.append("fastapi")
                    elif "django" in reqs:
                        detected.append("django")
                    elif "flask" in reqs:
                        detected.append("flask")
            
            if "python" not in detected:
                detected.append("python")
        except:
            if "python" not in detected:
                detected.append("python")
    
    # Rust
    if "Cargo.toml" in files:
        detected.append("rust")
    
    # Go
    if "go.mod" in files:
        detected.append("go")
    
    # TypeScript
    if "tsconfig.json" in files and "typescript" not in detected:
        detected.append("typescript")
    
    return list(set(detected))


# ==================== CONTEXT PERSISTENCE ====================
def save_context(url):
    """
    Save context to local file (URL + timestamp).
    
    This makes the CLI stateful — it remembers what was loaded.
    """
    CONTEXT_FILE.parent.mkdir(exist_ok=True)
    
    data = {
        "last_url": url,
        "updated": datetime.utcnow().isoformat()
    }
    
    with open(CONTEXT_FILE, "w") as f:
        json.dump(data, f)


def load_context():
    """
    Load context from local file.
    
    Returns dict with context data or empty dict if no context exists.
    """
    if CONTEXT_FILE.exists():
        try:
            with open(CONTEXT_FILE) as f:
                return json.load(f)
        except:
            return {}
    return {}


# ==================== VS CODE CONNECTION ====================
def connect_vscode(auto=False):
    """
    Auto-generate and write .vscode/mcp.json for VS Code integration.
    
    If auto=True, don't print output (silent startup).
    """
    config = {
        "servers": {
            "scrapee": {
                "type": "http",
                "url": f"{MCP_BASE_URL}/mcp"
            }
        }
    }
    
    try:
        VSCODE_CONFIG_PATH.parent.mkdir(exist_ok=True)
        with open(VSCODE_CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)
        
        if not auto:
            print("✓ VS Code connected")
    except Exception as e:
        if not auto:
            print(f"✗ Failed to connect: {e}")


# ==================== MCP INTERACTION ====================
def call_mcp(method, params):
    """
    Call MCP endpoint with JSON-RPC 2.0 format.
    
    Args:
        method: JSON-RPC method (e.g. "tools/call")
        params: Parameters dict
    
    Returns:
        Response dict or None on error
    """
    try:
        response = requests.post(
            f"{MCP_BASE_URL}/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": method,
                "params": params
            },
            timeout=60
        )
        
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        pass
    
    return None


def scrape_url(url):
    """Scrape and index a URL via MCP."""
    return call_mcp("tools/call", {
        "name": "scrape_url",
        "arguments": {"url": url}
    })


# ==================== CODE READING / AUTO-SCRAPE ====================
def get_project_files():
    """
    Scan project directory for source code files.
    
    Returns list of file paths (limited to 20 for speed).
    """
    files = []
    try:
        for root, _, filenames in os.walk("."):
            # Skip common ignore patterns
            if any(x in root for x in [".git", "node_modules", "__pycache__", ".venv", "dist", "build"]):
                continue
            
            for f in filenames:
                if f.endswith((".py", ".js", ".ts", ".tsx", ".rs", ".go", ".jsx")):
                    files.append(os.path.join(root, f))
    except:
        pass
    
    return files[:20]  # limit for speed


def extract_imports(files):
    """
    Extract imports from source files (multi-language).
    
    Supports: Python, JavaScript, TypeScript, Rust, Go
    """
    imports = set()
    
    patterns = [
        r"import\s+(?:(?:\{[^}]*\}|[^;]+)\s+from\s+)?['\"]([^'\"]+)['\"]",  # JS/TS imports
        r"import\s+([\w\.]+)",                                                  # python import X
        r"from\s+([\w\.]+)\s+import",                                           # python from X import
        r"require\(['\"]([^'\"]+)['\"]\)",                                      # node require
        r"use\s+(?:crate::)?([a-zA-Z0-9_:]+)",                                 # rust use
    ]
    
    for file in files:
        try:
            with open(file, "r", errors="ignore") as f:
                content = f.read(10000)  # read first 10KB only
            
            for pattern in patterns:
                matches = re.findall(pattern, content)
                for match in matches:
                    # Clean up and get base import name
                    base = match.split(".")[0].split("/")[0].lower().strip()
                    if base and len(base) > 1:  # skip single chars
                        imports.add(base)
        
        except:
            continue
    
    return list(imports)


def get_indexed_urls():
    """
    Get list of already-indexed URLs from MCP.
    
    Returns list of URLs or empty list on error.
    """
    try:
        res = call_mcp("tools/call", {
            "name": "list_docs",
            "arguments": {"limit": 100}
        })
        
        if res:
            return res.get("result", {}).get("structuredContent", {}).get("urls", [])
    except:
        pass
    
    return []


def auto_scrape_from_code():
    """
    Scan project code for imports and auto-load missing documentation.
    
    This is the magic: detects what libraries you use and loads their docs automatically.
    """
    print("\n🔍 scanning codebase...\n")
    
    files = get_project_files()
    
    if not files:
        print("(no source files found)\n")
        return
    
    imports = extract_imports(files)
    
    if not imports:
        print("(no imports detected)\n")
        return
    
    print(f"detected: {', '.join(imports[:8])}")
    if len(imports) > 8:
        print(f"  ... and {len(imports) - 8} more")
    print()
    
    # Get what's already indexed
    indexed_urls = get_indexed_urls()
    
    # Determine what docs to load
    to_load = []
    for imp in imports:
        doc_key = IMPORT_MAP.get(imp)
        
        if not doc_key:
            continue
        
        doc_url = DOC_MAP.get(doc_key)
        
        if not doc_url:
            continue
        
        # Skip if already indexed
        if any(doc_url in url for url in indexed_urls):
            continue
        
        to_load.append((imp, doc_key, doc_url))
    
    if not to_load:
        print("✓ everything already loaded\n")
        return
    
    # Load missing docs
    loaded = []
    for imp, doc_key, doc_url in to_load:
        print(f"→ loading {doc_key}...")
        res = scrape_url(doc_url)
        
        if res and "result" in res:
            loaded.append(doc_key)
            doc_count = res.get("result", {}).get("structuredContent", {}).get("doc_count", 1)
            print(f"  ✓ {doc_count} docs")
    
    if loaded:
        print(f"\n✓ auto-loaded: {', '.join(set(loaded))}\n")
    else:
        print(f"(unable to load docs)\n")


# ==================== COMMANDS ====================
def handle_load(url):
    """Load/scrape a URL into MCP context."""
    print(f"\n[+] loading: {url}")
    print("→ contacting MCP...")
    
    res = scrape_url(url)
    
    if not res:
        print("✗ MCP not responding\n")
        return False
    
    try:
        structured = res.get("result", {}).get("structuredContent", {})
        
        if not structured:
            print("✗ no usable content extracted\n")
            return False
        
        doc_count = structured.get("doc_count", 1)
        
        print(f"✓ indexed successfully ({doc_count} docs)")
        print("✓ stored in MCP")
        
        # Save to local context
        save_context(url)
        
        print("🧠 copilot now has access")
        
        # Random success message
        messages = [
            "That page didn't stand a chance.",
            "Knowledge absorbed.",
            "System upgraded.",
            "Context locked in.",
            "Ready for Copilot."
        ]
        print(f"→ {random.choice(messages)}\n")
        
        return True
    
    except Exception as e:
        print("✗ malformed MCP response\n")
        return False


def handle_status():
    """Show system status with intelligence."""
    print("\n=== SYSTEM STATUS ===\n")
    
    # MCP connectivity
    if check_mcp():
        print("MCP: ✓ connected")
    else:
        print("MCP: ✗ offline")
    
    # Context
    ctx = load_context()
    if ctx.get("last_url"):
        print(f"Last URL: {ctx['last_url']}")
    
    # Indexed documents
    try:
        res = call_mcp("tools/call", {
            "name": "list_docs",
            "arguments": {"limit": 20}
        })
        
        if res:
            data = res.get("result", {}).get("structuredContent", {})
            urls = data.get("urls", [])
            
            print(f"Documents: {len(urls)}")
            
            if urls:
                for u in urls[:5]:
                    print(f"  - {u}")
                
                if len(urls) > 5:
                    print(f"  ... +{len(urls)-5} more")
        else:
            print("Documents: unavailable")
    
    except Exception as e:
        print("Documents: unavailable")
    
    print()


def handle_reset():
    """Reset/clear local context."""
    print("\nclearing local context...")
    
    if CONTEXT_FILE.exists():
        try:
            CONTEXT_FILE.unlink()
            print("✓ local context cleared")
        except Exception as e:
            print(f"✗ error clearing context: {e}")
    else:
        print("(no context to clear)")
    
    print("⚠️  MCP reset not implemented yet\n")


def show_help():
    """Display command reference."""
    help_text = """
Commands:

  /load <url>     scrape & index a URL
  /scrape <url>   same as /load (alias)
  /status         show indexed sources
  /reset          clear context
  /help           show this
  /exit           exit

Example:

  /load https://react.dev
  /status
  /exit

Philosophy:
  
  CLI orchestrates (loads docs, configures)
  MCP serves context
  Copilot thinks with context
"""
    print(help_text)


# ==================== BOOT SYSTEM ====================
def boot():
    """Initialize Scrapee system."""
    show_banner()
    print("\ninitializing scrapee...\n")
    
    # Connect to VS Code (silent)
    connect_vscode(auto=True)
    
    # Check real MCP health
    mcp_ok = check_mcp()
    
    # Load context
    ctx = load_context()
    
    # Show status
    print(f"project: {os.getcwd()}")
    
    if mcp_ok:
        print("mcp: ✓ connected")
    else:
        print("mcp: ✗ not reachable")
    
    if ctx.get("last_url"):
        print(f"last loaded: {ctx['last_url']}")
    
    # 🔥 NEW: Auto-scrape from code (reads imports, loads missing docs)
    auto_scrape_from_code()
    
    print("status: ready\n")
    print("type /help\n")


# ==================== REPL LOOP ====================
def run():
    """Main REPL loop."""
    boot()
    
    while True:
        try:
            cmd = input("> ").strip()
            
            if not cmd:
                continue
            
            # Exit commands
            if cmd in ["/exit", "exit", "quit"]:
                print("\n👋\n")
                break
            
            # Help
            if cmd == "/help":
                show_help()
                continue
            
            # Load/scrape
            if cmd.startswith("/load ") or cmd.startswith("/scrape "):
                parts = cmd.split(" ", 1)
                if len(parts) < 2:
                    print("usage: /load <url>\n")
                    continue
                
                handle_load(parts[1])
                continue
            
            # Status
            if cmd == "/status":
                handle_status()
                continue
            
            # Reset
            if cmd == "/reset":
                handle_reset()
                continue
            
            # Unknown
            print("unknown command. type /help\n")
        
        except KeyboardInterrupt:
            print("\n\n👋\n")
            break
        except EOFError:
            break


# ==================== ENTRY ====================
if __name__ == "__main__":
    run()
