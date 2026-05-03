#!/usr/bin/env python3
"""
Scrapee CLI — Platform orchestrator.

Ingestion + setup layer. NOT a chatbot.

Architecture:
  CLI:     Load URLs, index docs, configure VS Code
  MCP:     Serve indexed context to Copilot
  VS Code: Think and reason with context

Philosophy:
  ❌ CLI does NOT answer questions
  ✅ Copilot (in VS Code) does
"""

import sys
import os
import json
import subprocess
from datetime import datetime
from pathlib import Path

try:
    import requests
except ImportError:
    print("Error: requests not installed. Run: pip install requests", file=sys.stderr)
    sys.exit(1)

# ==================== CONFIG ====================
VERSION = "1.0.0"
MCP_BASE_URL = os.environ.get("SCRAPEE_BASE_URL") or "https://your-vercel-url.vercel.app"
VSCODE_CONFIG_PATH = Path(".vscode/mcp.json")
CONTEXT_FILE = Path(".scrapee/context.json")

# ==================== BANNER ====================
def show_banner():
    """Display introduction with elaborate ASCII art."""
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
╚════██║██║      ██╔══██╗██╔══██║██╔══██╗██╔══╝  ██╔══╝  
███████║╚██████╗ ██║  ██║██║  ██║██████╔╝███████╗███████╗
╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ ╚══════╝╚══════╝

scrapee CLI v{} — context engine ready
    """
    print(banner.format(VERSION))
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} • Base: {MCP_BASE_URL}\n")


# ==================== MCP CONFIG ====================
def connect_vscode():
    """
    Auto-generate .vscode/mcp.json for VS Code MCP integration.
    
    After scraping, call this to configure Copilot.
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
        
        print("\n✓ VS Code configuration updated.")
        print(f"  File: {VSCODE_CONFIG_PATH}")
        print("  → Restart VS Code or reload window (Cmd+R / Ctrl+R)")
        print("  → Copilot can now use Scrapee context.\n")
        return True
    except Exception as e:
        print(f"\n✗ Failed to write config: {e}\n")
        return False


# ==================== CONTEXT MANAGEMENT ====================
def get_loaded_docs():
    """Get currently indexed documents."""
    try:
        if CONTEXT_FILE.exists():
            with open(CONTEXT_FILE) as f:
                data = json.load(f)
                return data.get("docs", [])
    except:
        pass
    return []


def add_context(url, doc_count):
    """Record that a URL was indexed."""
    try:
        CONTEXT_FILE.parent.mkdir(exist_ok=True)
        docs = get_loaded_docs()
        docs.append({
            "url": url,
            "doc_count": doc_count,
            "indexed_at": datetime.now().isoformat()
        })
        with open(CONTEXT_FILE, "w") as f:
            json.dump({"docs": docs}, f, indent=2)
    except:
        pass


def clear_context():
    """Reset indexed context."""
    try:
        if CONTEXT_FILE.exists():
            CONTEXT_FILE.unlink()
        print("\n✓ Context cleared.\n")
    except Exception as e:
        print(f"\n✗ Failed to clear context: {e}\n")


# ==================== SCRAPE HANDLER ====================
def handle_load(url):
    """
    Load URL into MCP context.
    
    This scrapes and indexes the URL, making it available to Copilot.
    """
    print(f"\n[+] Loading: {url}")
    print("    Scraping + indexing...\n")
    
    try:
        # Call MCP scrape tool
        response = requests.post(
            f"{MCP_BASE_URL}/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "scrape_url",
                    "arguments": {"url": url}
                }
            },
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            
            # Check if successful
            if "result" in result:
                doc_count = result["result"].get("doc_count", 1)
                print(f"✓ Loaded successfully ({doc_count} docs).")
                
                # Record context
                add_context(url, doc_count)
                
                # Auto-connect VS Code
                print("\n[*] Configuring VS Code MCP connection...")
                connect_vscode()
                
                print(f"🧠 Copilot can now use this context.\n")
                return True
            else:
                print(f"✗ Error: {result.get('error', 'Unknown error')}\n")
                return False
        else:
            print(f"✗ Server error ({response.status_code}).\n")
            return False
    
    except Exception as e:
        print(f"✗ Failed: {e}\n")
        return False


# ==================== STATUS ====================
def show_status():
    """Show currently loaded documentation sources."""
    docs = get_loaded_docs()
    
    if not docs:
        print("\n✗ No context loaded.\n")
        print("   Try: /load <url>\n")
        return
    
    print("\n📚 Loaded sources:\n")
    for i, doc in enumerate(docs, 1):
        url = doc.get("url", "unknown")
        count = doc.get("doc_count", "?")
        indexed_at = doc.get("indexed_at", "unknown")
        print(f"  {i}. {url}")
        print(f"     → {count} documents")
        print(f"     → Indexed: {indexed_at}\n")
    
    print(f"Total: {len(docs)} source(s)\n")


# ==================== HELP ====================
def show_help():
    """Display command reference."""
    help_text = r"""
╔════════════════════════════════════════════════════════════════╗
║               SCRAPEE CLI — COMMAND REFERENCE                 ║
╚════════════════════════════════════════════════════════════════╝

📥 INGESTION:

  /load <url>              Load a URL into MCP context
                           Example: /load https://react.dev
                           → Scrapes, indexes, configures VS Code

  /connect                 Manually update VS Code config
                           (Auto-run after /load)

📋 MANAGEMENT:

  /status                  Show loaded documentation sources

  /reset                   Clear all indexed context

ℹ️  HELP:

  /help                    Show this message

  /exit                    Exit Scrapee

╔════════════════════════════════════════════════════════════════╗
║                         WORKFLOW                              ║
╚════════════════════════════════════════════════════════════════╝

  1. Open terminal → scrapee
     (Starts orchestrator)

  2. /load https://react.dev
     (CLI scrapes + indexes)

  3. /connect
     (CLI configures .vscode/mcp.json)

  4. Open VS Code → Cmd+R (reload window)
     (VS Code loads MCP config)

  5. Open Copilot → Ask question about React
     (Copilot uses Scrapee context automatically)

╔════════════════════════════════════════════════════════════════╗
║                    KEY PRINCIPLE                              ║
╚════════════════════════════════════════════════════════════════╝

  ❌ Scrapee CLI does NOT answer questions
  ✅ Copilot (in VS Code) answers using loaded context

  CLI role:  Load docs, setup integration
  MCP role:  Serve context to Copilot
  Copilot:   Think and reason with context

═══════════════════════════════════════════════════════════════════

Docs:  https://github.com/jonathanvineet/scrapee
"""
    print(help_text)


# ==================== CLI LOOP ====================
def run_cli():
    """Interactive REPL loop."""
    show_banner()
    print("Type /help for commands.\n")
    
    while True:
        try:
            user_input = input("scrapee> ").strip()
            
            if not user_input:
                continue
            
            # Commands
            if user_input.startswith("/load "):
                url = user_input[6:].strip()
                if url:
                    handle_load(url)
                else:
                    print("\n✗ Usage: /load <url>\n")
            
            elif user_input == "/connect":
                connect_vscode()
            
            elif user_input == "/status":
                show_status()
            
            elif user_input == "/reset":
                clear_context()
            
            elif user_input == "/help":
                show_help()
            
            elif user_input == "/exit":
                print("\n👋 Goodbye!\n")
                sys.exit(0)
            
            else:
                print("\n✗ Unknown command. Type /help for available commands.\n")
        
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!\n")
            sys.exit(0)
        except EOFError:
            sys.exit(0)


# ==================== ONE-SHOT MODE ====================
def main():
    """CLI entry point."""
    if len(sys.argv) > 1:
        # One-shot mode: scrapee load <url>
        command = sys.argv[1]
        
        if command == "load" and len(sys.argv) > 2:
            url = sys.argv[2]
            show_banner()
            handle_load(url)
        
        elif command == "status":
            show_banner()
            show_status()
        
        elif command == "reset":
            show_banner()
            clear_context()
        
        elif command == "connect":
            show_banner()
            connect_vscode()
        
        elif command == "help" or command == "-h" or command == "--help":
            show_banner()
            show_help()
        
        else:
            print(f"Unknown command: {command}")
            print("Run: scrapee --help")
            sys.exit(1)
    else:
        # Interactive mode
        run_cli()


if __name__ == "__main__":
    main()
