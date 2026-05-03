#!/usr/bin/env python3
"""
Scrapee CLI — persistent session for context-driven queries.
A thin client to the scrapee MCP endpoint.

Usage:
  scrapee                    # Start interactive session
  scrapee ask "your query"   # Direct query (requires prior /scrape)
  scrapee scrape <url>       # Scrape + load context

Commands in session:
  /scrape <url>              # Scrape and load context
  /ask <query>               # Query (default, no slash needed)
  /help                      # Show commands
  /exit                      # Exit
"""

import json
import os
import sys

try:
    import requests
except ImportError:
    print("Error: requests not installed. Run: pip install requests", file=sys.stderr)
    sys.exit(1)

VERSION = "1.0.0"
MCP_URL = os.environ.get("SCRAPEE_MCP_URL") or "http://localhost:8080/mcp"
TIMEOUT = 30

SESSION = {
    "active": False,
    "last_context": None,
    "last_sources": [],
    "last_query": None,
}


def show_banner():
    """Display scrapee introduction."""
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
""".format(VERSION)
    print(banner)


def show_help():
    """Display available commands."""
    print("""
Commands:
  /scrape <url>   → Scrape and load context
  /ask <query>    → Query loaded content (default if no slash)
  /help           → Show this help
  /exit           → Exit

Examples:
  > /scrape https://docs.python.org
  > asyncio patterns
  > /ask what is a coroutine
""")


def call_mcp(method, params):
    """Send JSON-RPC request to MCP endpoint."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }
    try:
        r = requests.post(MCP_URL, json=payload, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def scrape_url(url):
    """Call MCP scrape_url tool."""
    return call_mcp("tools/call", {
        "name": "scrape_url",
        "arguments": {"url": url, "max_depth": 1}
    })


def ask_mcp(query):
    """Call MCP get_context tool."""
    return call_mcp("tools/call", {
        "name": "get_context",
        "arguments": {"query": query}
    })


def extract_result(res):
    """Extract context and sources from MCP response."""
    if isinstance(res, dict) and "error" in res:
        return None, []
    try:
        result = res.get("result", {})
        structured = result.get("structuredContent", result)
        
        ctx = structured.get("context") or structured.get("summary") or ""
        sources = structured.get("sources") or structured.get("documents") or []
        
        return ctx, sources
    except Exception:
        return None, []


def format_context(ctx):
    """Pretty-print context."""
    if not ctx:
        return ""
    if isinstance(ctx, str):
        return ctx
    try:
        return json.dumps(ctx, indent=2)
    except Exception:
        return str(ctx)


def format_sources(sources):
    """Pretty-print sources."""
    if not sources:
        return ""
    lines = []
    for s in sources:
        if isinstance(s, dict):
            title = s.get("title") or s.get("url") or s.get("id")
            url = s.get("url") or s.get("link")
            if title and url and title != url:
                lines.append(f"  • {title} — {url}")
            elif url:
                lines.append(f"  • {url}")
        else:
            lines.append(f"  • {s}")
    return "\n".join(lines)


def handle_scrape(url):
    """Handle /scrape command."""
    if not url:
        print("Usage: /scrape <url>\n")
        return
    
    print(f"\n[+] Scraping: {url}...\n")
    res = scrape_url(url)
    
    ctx, sources = extract_result(res)
    
    if ctx is None:
        print("✗ Failed to load content.\n")
        return
    
    SESSION["active"] = True
    SESSION["last_context"] = ctx
    SESSION["last_sources"] = sources
    
    print("✓ Context loaded successfully.")
    print("You're good. Ask anything.\n")


def handle_ask(query):
    """Handle /ask or default query command."""
    if not query:
        print("(nothing to ask)\n")
        return
    
    if not SESSION["active"]:
        print("✗ No context loaded. Use /scrape first.\n")
        return
    
    print()
    res = ask_mcp(query)
    
    ctx, sources = extract_result(res)
    
    if ctx is None:
        print("✗ Error retrieving response.\n")
        return
    
    SESSION["last_query"] = query
    SESSION["last_context"] = ctx
    SESSION["last_sources"] = sources
    
    print("---")
    print(format_context(ctx))
    print("---\n")
    
    if sources:
        print("Sources:")
        print(format_sources(sources))
        print()


def run_cli():
    """Main interactive session loop."""
    show_banner()
    show_help()
    
    while True:
        try:
            user_input = input("> ").strip()
            
            if not user_input:
                continue
            
            # EXIT
            if user_input in ("/exit", "exit", "quit", ":q"):
                print("Goodbye.")
                break
            
            # HELP
            if user_input in ("/help", "help", "?"):
                show_help()
                continue
            
            # SCRAPE
            if user_input.startswith("/scrape"):
                url = user_input.replace("/scrape", "").strip()
                handle_scrape(url)
                continue
            
            # ASK (explicit)
            if user_input.startswith("/ask"):
                query = user_input.replace("/ask", "").strip()
                handle_ask(query)
                continue
            
            # DEFAULT = ASK
            handle_ask(user_input)
        
        except KeyboardInterrupt:
            print("\nExiting.")
            break
        except EOFError:
            break


def main():
    """Entry point."""
    if len(sys.argv) > 1:
        # One-shot mode: scrapee ask "query" or scrapee scrape <url>
        cmd = sys.argv[1]
        
        if cmd == "ask" and len(sys.argv) > 2:
            # scrapee ask "query"  (but we need context, so error)
            print("✗ Use interactive mode to ask questions.")
            print("  Try: scrapee")
            sys.exit(1)
        
        elif cmd == "scrape" and len(sys.argv) > 2:
            # scrapee scrape <url>
            url = sys.argv[2]
            res = scrape_url(url)
            ctx, sources = extract_result(res)
            
            if ctx:
                print("✓ Context loaded:")
                print(format_context(ctx))
                if sources:
                    print("\nSources:")
                    print(format_sources(sources))
            else:
                print("✗ Failed to scrape")
                sys.exit(1)
            sys.exit(0)
        
        else:
            print("Usage: scrapee [ask|scrape]")
            print("       scrapee scrape <url>")
            print("       scrapee (interactive)")
            sys.exit(1)
    
    else:
        # Interactive mode (default)
        run_cli()


if __name__ == "__main__":
    main()
