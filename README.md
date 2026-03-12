# Scrapee - Production MCP Documentation Assistant

Production-grade Model Context Protocol (MCP) server for AI agents (GitHub Copilot, Cursor, ChatGPT).

## What It Does

Ask GitHub Copilot: "How do I create a Hedera token?"

The MCP automatically:
1. Searches documentation
2. Finds code examples
3. Returns results to Copilot
4. Copilot writes the code

**No manual tool invocation needed!**

## Project Structure

```
scrapee/
├── backend/
│   ├── api/mcp.py              # Production MCP Server
│   ├── storage/sqlite_store.py # SQLite + FTS5
│   ├── smart_scraper.py        # Code extraction
│   └── requirements.txt
├── .vscode/mcp.json            # MCP config
├── MCP_README.md               # Complete docs
├── start_mcp.py                # Quick start
└── test_mcp_production.py      # Tests
```

## Quick Start

```bash
# 1. Install
cd backend && pip install -r requirements.txt

# 2. Run
python start_mcp.py

# 3. Test
python test_mcp_production.py
```

VS Code config already set in `.vscode/mcp.json` - just restart!

## Features

- SQLite with FTS5 indexing
- Smart code extraction
- Domain security allowlist
- Response caching
- Zero AI dependencies

## Documentation

See **[MCP_README.md](MCP_README.md)** for complete guide.

## Support

- Docs: [MCP_README.md](MCP_README.md)
- Issues: [GitHub](https://github.com/jonathanvineet/scrapee/issues)

---

Built with ❤️ for developers
