#!/usr/bin/env bash
# Scrapee CLI Quick Reference Card
# Print this to see all available commands and options

cat << 'EOF'

╔════════════════════════════════════════════════════════════════╗
║                   SCRAPEE CLI QUICK REFERENCE                  ║
║                  AI-Powered Context Engine                      ║
╚════════════════════════════════════════════════════════════════╝

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 INTERACTIVE MODE (Recommended)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  $ scrapee                    # Start interactive session


  COMMANDS IN SESSION:

  /scrape <url>               # Load and cache documentation
                              # Usage: /scrape https://docs.python.org

  /ask <query>                # Ask about loaded context (default, no / needed)
                              # Usage: /ask what is asyncio
                              # Or just: what is asyncio

  /help                       # Show available commands

  /exit, exit, quit, :q       # Exit session


  EXAMPLE SESSION:

  $ scrapee
  > /scrape https://fastapi.tiangolo.com
  ✓ Context loaded successfully.

  > how do I validate request bodies
  ---
  To validate request bodies, use Pydantic models...
  ---
  
  Sources:
    • FastAPI Request Bodies

  > middleware
  ---
  Middleware wraps your application lifecycle...
  ---

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ONE-SHOT COMMANDS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  $ scrapee scrape <url>      # Scrape and display context
  
  $ scrapee scrape https://docs.python.org
  ✓ Context loaded:
    • 30 pages indexed
    • 245 code blocks extracted

  $ scrapee --help            # Show help

  $ scrapee --version         # Show version (if available)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ENVIRONMENT VARIABLES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  SCRAPEE_MCP_URL             # Override MCP endpoint
                              # Default: http://localhost:8080/mcp
  
  $ export SCRAPEE_MCP_URL=https://api.example.com/mcp
  $ scrapee

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 INSTALLATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  macOS (Homebrew):
    $ brew tap jonathanvineet/scrapee
    $ brew install scrapee

  macOS / Linux (Curl):
    $ curl -fsSL https://raw.githubusercontent.com/\
      jonathanvineet/scrapee/main/scripts/install.sh | sh

  Windows (PowerShell):
    $ iwr https://raw.githubusercontent.com/jonathanvineet/scrapee/\
      main/scripts/install.ps1 | iex

  Python Developers:
    $ pip install scrapee-cli

  From Source:
    $ python3 cli/scrapee.py

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 TIPS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  💡 Load context once, ask multiple questions
  💡 Context persists across queries (until new /scrape)
  💡 Results improve as you interact (adaptive learning)
  💡 No trailing slash needed for queries (just start typing)
  💡 Press Ctrl+C or type /exit to quit gracefully

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 DOCUMENTATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  README.md                   Full platform guide
  BUILDING.md                 Build & distribution guide
  PLATFORM_OVERVIEW.md        Architecture & features
  NEW_TOOLS_GUIDE.md          MCP tools reference
  VERCEL_QUICK_START.md       Deployment guide

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 GETTING HELP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Repository:  https://github.com/jonathanvineet/scrapee
  Issues:      https://github.com/jonathanvineet/scrapee/issues
  Discussions: https://github.com/jonathanvineet/scrapee/discussions

╔════════════════════════════════════════════════════════════════╗
║         Built for developers. By developers. Forever free.      ║
╚════════════════════════════════════════════════════════════════╝

EOF
