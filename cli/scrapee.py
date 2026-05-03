#!/usr/bin/env python3
"""
Simple CLI client for the Scrapee MCP endpoint.
Usage:
  python cli/scrapee.py scrape <url>
  python cli/scrapee.py ask "query"
  python cli/scrapee.py interactive

The tool is a thin client: it sends JSON-RPC requests to the MCP endpoint
and prints a succinct, human-friendly summary (context + sources).
"""

import argparse
import json
import os
import sys
import time

try:
    import requests
except Exception:
    print("Missing dependency: requests. Install with `pip install requests`", file=sys.stderr)
    raise

DEFAULT_MCP_URL = os.environ.get("SCRAPEE_MCP_URL") or os.environ.get("MCP_URL") or "http://localhost:8080/mcp"

TIMEOUT = 30


def call_mcp(mcp_url, method, params):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }

    try:
        r = requests.post(mcp_url, json=payload, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def scrape(mcp_url, url, max_depth=1):
    return call_mcp(mcp_url, "tools/call", {
        "name": "scrape_url",
        "arguments": {"url": url, "max_depth": max_depth}
    })


def query(mcp_url, q):
    return call_mcp(mcp_url, "tools/call", {
        "name": "get_context",
        "arguments": {"query": q}
    })


def print_structured_result(res):
    if not isinstance(res, dict):
        print(json.dumps(res, indent=2))
        return

    if "error" in res:
        print("[ERROR]", res["error"]) 
        return

    result = res.get("result") or res.get("data") or {}

    # Try common locations
    structured = result.get("structuredContent") if isinstance(result, dict) else None
    if structured is None:
        structured = result

    ctx = None
    sources = None

    if isinstance(structured, dict):
        ctx = structured.get("context") or structured.get("summary") or structured.get("text")
        sources = structured.get("sources") or structured.get("documents") or structured.get("refs")

    # Fallback: show raw result
    print("\n=== RAW RESPONSE ===\n")
    print(json.dumps(res, indent=2))

    if ctx:
        print("\n=== CONTEXT ===\n")
        if isinstance(ctx, (list, dict)):
            try:
                print(json.dumps(ctx, indent=2))
            except Exception:
                print(str(ctx))
        else:
            print(ctx)

    if sources:
        print("\n=== SOURCES ===\n")
        if isinstance(sources, dict):
            # sometimes sources are keyed
            for k, v in sources.items():
                print(f"- {k}: {v}")
        else:
            for s in sources:
                if isinstance(s, dict):
                    title = s.get("title") or s.get("url") or s.get("id")
                    url = s.get("url") or s.get("link")
                    if title and url:
                        print(f"- {title} — {url}")
                    elif url:
                        print(f"- {url}")
                    else:
                        print(f"- {json.dumps(s)}")
                else:
                    print(f"- {s}")


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(prog="scrapee", description="Scrapee CLI: thin client for the MCP API")
    parser.add_argument("--mcp", default=DEFAULT_MCP_URL, help="MCP endpoint URL (env SCRAPEE_MCP_URL or MCP_URL)")
    sub = parser.add_subparsers(dest="cmd")

    s = sub.add_parser("scrape", help="Ask MCP to scrape a URL")
    s.add_argument("url")
    s.add_argument("--depth", type=int, default=1)

    q = sub.add_parser("ask", help="Ask MCP for context for a query")
    q.add_argument("query")

    inter = sub.add_parser("interactive", help="Start an interactive REPL session")

    args = parser.parse_args(argv)

    mcp_url = args.mcp

    if args.cmd == "scrape":
        res = scrape(mcp_url, args.url, max_depth=args.depth)
        print_structured_result(res)
        return

    if args.cmd == "ask":
        res = query(mcp_url, args.query)
        print_structured_result(res)
        return

    if args.cmd == "interactive":
        print("Scrapee interactive mode. Type 'exit' or 'quit' to leave.")
        try:
            while True:
                qstr = input("\n> ")
                if not qstr:
                    continue
                if qstr.lower() in ("exit", "quit"):
                    break
                res = query(mcp_url, qstr)
                print_structured_result(res)
        except (KeyboardInterrupt, EOFError):
            print("\nbye")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
