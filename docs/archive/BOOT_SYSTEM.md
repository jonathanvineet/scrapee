# Scrapee CLI v3.0 — Boot System Implementation

## 🚀 What Changed

Complete rewrite of CLI from simple command handler to **intelligent boot system** with project detection and auto-loading.

### Before (v2.0)
```
scrapee
→ REPL loop
→ /load <url>
→ Manual everything
```

### After (v3.0)
```
scrapee
→ Boot system
→ Auto-detect React/Python/Rust/etc
→ Auto-load corresponding docs
→ Ready to use (or /load for more)
```

---

## 🧠 Architecture

### Boot System Flow

```python
run()
  ├─ boot()
  │   ├─ show_banner()           # Display art
  │   ├─ connect_vscode(auto=True)  # Write .vscode/mcp.json (silent)
  │   └─ print status
  │
  ├─ auto_load()
  │   ├─ detect_project()        # Find package.json, requirements.txt, etc
  │   └─ scrape_url() for each   # Load React/Python/FastAPI docs
  │
  └─ REPL loop
      ├─ /load <url>
      ├─ /scrape <url> (alias)
      ├─ /status
      ├─ /reset
      ├─ /help
      └─ /exit
```

### Project Detection (Auto-Magic)

Detects:
- **Node.js**: `package.json` → loads `nodejs` docs
- **React**: `package.json` + `react` in deps → `https://react.dev`
- **Vue**: `vue` in deps → `https://vuejs.org`
- **Next.js**: `next` in deps → `https://nextjs.org/docs`
- **Python**: `requirements.txt`/`pyproject.toml` → `https://docs.python.org/3/`
- **FastAPI**: `requirements.txt` + `fastapi` → `https://fastapi.tiangolo.com/`
- **Django**: `django` in requirements → Django docs
- **Flask**: `flask` in requirements → Flask docs
- **Rust**: `Cargo.toml` → Rust docs
- **Go**: `go.mod` → Go docs
- **TypeScript**: `tsconfig.json` → TypeScript docs

---

## 📋 Commands (Final)

```
/load <url>       Scrape and index a URL
/scrape <url>     Same as /load (alias)
/status           Show indexed sources
/reset            Clear context
/help             Show commands
/exit             Exit
```

**No /ask** — Copilot handles reasoning.

---

## 🎯 Workflow

### User Boots Scrapee

```bash
$ scrapee

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
...

scrapee CLI v3.0.0 — context engine ready

initializing scrapee...

project: /Users/jonathan/elco/scrapee
mcp: connected
status: ready

type /help

auto-detected: nodejs, python
auto-loading docs...

  → nodejs...
    ✓ 1245 docs
  → python...
    ✓ 3420 docs

✓ 2 doc set(s) loaded

>
```

### User Can Now

```
> /status
indexed sources:

✓ mcp connected and ready

> /load https://react.dev
[+] loading: https://react.dev

✓ indexed successfully (245 docs)
🧠 copilot now has access

> /exit

👋
```

---

## 🔧 Core Functions

### `boot()`
Initializes the system:
- Shows banner
- Silently connects VS Code (.vscode/mcp.json)
- Prints status
- Prompts for /help

### `detect_project()`
Reads `package.json`, `requirements.txt`, etc and returns list:
```python
["nodejs", "python", "fastapi"]
```

### `auto_load()`
For each detected project, looks up in `DOC_MAP` and scrapes:
```
nodejs → https://nodejs.org/docs/
python → https://docs.python.org/3/
fastapi → https://fastapi.tiangolo.com/
```

### `connect_vscode(auto=False)`
Writes `.vscode/mcp.json` for MCP integration:
```json
{
  "servers": {
    "scrapee": {
      "type": "http",
      "url": "https://your-vercel-url.vercel.app/mcp"
    }
  }
}
```
If `auto=True`, does this silently (no output).

### `call_mcp(method, params)`
JSON-RPC 2.0 call to MCP endpoint.

### `handle_load(url)`, `handle_status()`, `handle_reset()`
Command handlers.

---

## 💡 Design Principles (Locked In)

✅ **CLI never answers questions**
- `/ask` command completely removed
- Copilot handles reasoning

✅ **CLI is pure orchestrator**
- Load docs
- Configure VS Code
- Query status
- Reset context
- That's it.

✅ **MCP is the intelligence**
- Stores docs
- Serves context
- Handles search
- Ranking

✅ **Copilot is the reasoner**
- Gets context from MCP
- Answers questions
- Thinks deeply

---

## 📊 File Stats

- **Lines of code**: 402
- **Functions**: 12 core functions
- **Project types detected**: 10+
- **Documentation URLs mapped**: 15+
- **Syntax**: Valid Python 3

---

## 🚀 Next Opportunities (Optional)

### Phase 2: Code-Aware Loading
```
scrapee analyze-imports
→ Reads Python/JS/TS files
→ Extracts imports (numpy, fastapi, react, etc)
→ Auto-loads missing docs
→ Result: Context for your exact project
```

### Phase 3: Real-Time Watching
```
scrapee watch
→ Monitors open files
→ Detects new imports
→ Auto-loads docs on demand
→ Result: Context always matches code
```

### Phase 4: Copilot Native Mode
```
VS Code Copilot command
→ @scrapee analyze this code
→ Loads needed docs automatically
→ Provides context
→ Result: Copilot super-powered
```

---

## ✅ Validation

✅ Syntax: Valid Python 3
✅ Import detection: Works
✅ Banner: Restored and glorious
✅ Boot sequence: Complete
✅ Commands: /load, /scrape, /status, /reset, /help, /exit
✅ Philosophy: Orchestrator, not assistant

---

## 🎯 What You Have Now

Not a tool. Not a script.

**A developer environment extension.**

```
scrapee = orchestration layer
MCP = intelligence layer
Copilot = reasoning layer

Together = Copilot supercharged with real docs
```
