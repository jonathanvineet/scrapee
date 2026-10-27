#!/usr/bin/env python3
"""
Scrapee CLI — boot system & orchestrator.

Philosophy:
  CLI = orchestrator (loads docs, configures your editor)
  MCP = intelligence layer (serves context)
  Copilot / Claude / Cursor = reasoner (thinks with that context)

Flow:
  scrapee → boot → detect project → auto-load docs → REPL (/load /ask /status ...)

One-shot use:
  scrapee load <url> [--pages N]   scrapee ask "<question>"   scrapee status
  scrapee sources                  scrapee remove <domain>    scrapee connect
"""

import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

try:
    import requests
    import urllib3
    urllib3.disable_warnings()  # Suppress LibreSSL warning
except ImportError:
    print("Error: requests not installed. Run: pip install requests", file=sys.stderr)
    sys.exit(1)

try:
    import readline  # noqa: F401 - gives input() history and line editing
except ImportError:
    pass

# ==================== CONFIG ====================
VERSION = "3.1.0"

VSCODE_CONFIG_PATH = Path(".vscode/mcp.json")
CONTEXT_FILE = Path(".scrapee/context.json")

HOSTED_BASE_URL = "https://scrapee-api.vercel.app"

# Crawls of a whole docs site take minutes, not seconds.
SCRAPE_TIMEOUT = 600
DEFAULT_PAGES = 40


def find_local_stdio_server():
    """Locate a local backend/mcp_stdio.py, if one is reachable.

    Returns an absolute Path to the stdio entrypoint, or None. This is what
    lets the CLI wire an editor straight into a locally-running engine
    instead of the hosted service.
    """
    explicit = os.environ.get("SCRAPEE_MCP_STDIO")
    candidates = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    candidates.append(Path.cwd() / "backend" / "mcp_stdio.py")
    # When run from a checkout: cli/scrapee.py -> ../backend/mcp_stdio.py
    candidates.append(Path(__file__).resolve().parent.parent / "backend" / "mcp_stdio.py")
    for path in candidates:
        try:
            if path.is_file():
                return path.resolve()
        except OSError:
            continue
    return None


def stdio_python_for(stdio_path):
    """Best interpreter for launching the stdio server: the backend venv if
    it exists next to the script, otherwise this interpreter / python3."""
    venv_py = stdio_path.parent / "venv" / "bin" / "python3"
    if venv_py.is_file():
        return str(venv_py)
    return sys.executable or "python3"


LOCAL_STDIO_SERVER = find_local_stdio_server()

# Hosted URL unless the user overrode it; when a local engine is present and no
# override was given, talk to the local Flask instance instead.
MCP_BASE_URL = os.environ.get("SCRAPEE_BASE_URL")
if not MCP_BASE_URL:
    MCP_BASE_URL = "http://localhost:8080" if LOCAL_STDIO_SERVER else HOSTED_BASE_URL
MCP_BASE_URL = MCP_BASE_URL.rstrip("/")


# Project → Documentation URL mapping
DOC_MAP = {
    "react": "https://react.dev/learn",
    "vue": "https://vuejs.org/guide/",
    "next": "https://nextjs.org/docs",
    "svelte": "https://svelte.dev/docs",
    "angular": "https://angular.dev/overview",
    "tailwind": "https://tailwindcss.com/docs",
    "express": "https://expressjs.com/en/guide/routing.html",
    "python": "https://docs.python.org/3/",
    "fastapi": "https://fastapi.tiangolo.com/",
    "django": "https://docs.djangoproject.com/en/stable/",
    "flask": "https://flask.palletsprojects.com/",
    "rust": "https://doc.rust-lang.org/book/",
    "go": "https://go.dev/doc/",
    "typescript": "https://www.typescriptlang.org/docs/",
    "nodejs": "https://nodejs.org/docs/latest/api/",
}

# package.json dependency → DOC_MAP key
NPM_MAP = {
    "react": "react",
    "react-dom": "react",
    "next": "next",
    "vue": "vue",
    "svelte": "svelte",
    "@sveltejs/kit": "svelte",
    "@angular/core": "angular",
    "tailwindcss": "tailwind",
    "express": "express",
    "typescript": "typescript",
}

# requirements.txt / pyproject package → DOC_MAP key
PY_MAP = {
    "fastapi": "fastapi",
    "django": "django",
    "flask": "flask",
}

# Import name (first path segment) → DOC_MAP key
IMPORT_MAP = {
    "react": "react",
    "react-dom": "react",
    "next": "next",
    "@next": "next",
    "vue": "vue",
    "svelte": "svelte",
    "@angular": "angular",
    "fastapi": "fastapi",
    "flask": "flask",
    "django": "django",
    "express": "express",
}

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env", "dist",
    "build", ".next", ".turbo", ".cache", "site-packages", "target", ".scrapee",
}
SOURCE_EXTS = (".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".rs", ".go", ".vue", ".svelte")


# ==================== OUTPUT ====================
_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def ok(text):
    return _c("32", text)


def bad(text):
    return _c("31", text)


def dim(text):
    return _c("2", text)


def bold(text):
    return _c("1", text)


def accent(text):
    return _c("33", text)


class Spinner:
    """A one-line progress indicator for long requests (crawls)."""

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, label):
        self.label = label
        self._stop = threading.Event()
        self._thread = None
        self.started = 0.0

    def __enter__(self):
        self.started = time.time()
        if sys.stdout.isatty():
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        else:
            print(f"  {self.label}...")
        return self

    def _spin(self):
        i = 0
        while not self._stop.wait(0.1):
            elapsed = int(time.time() - self.started)
            frame = self.FRAMES[i % len(self.FRAMES)]
            sys.stdout.write(f"\r  {accent(frame)} {self.label} {dim(f'{elapsed}s')}  ")
            sys.stdout.flush()
            i += 1

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread:
            self._thread.join()
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()


# ==================== BACKEND ====================
def api(method, path, timeout=15, **kwargs):
    """Call the Scrapee backend. Returns (json_or_None, error_or_None)."""
    try:
        response = requests.request(method, f"{MCP_BASE_URL}{path}", timeout=timeout, **kwargs)
    except requests.exceptions.ConnectionError:
        return None, f"cannot reach {MCP_BASE_URL}"
    except requests.exceptions.Timeout:
        return None, f"timed out after {timeout}s"
    except requests.exceptions.RequestException as e:
        return None, str(e)
    try:
        data = response.json()
    except ValueError:
        return None, f"HTTP {response.status_code} (not JSON)"
    if response.status_code >= 400:
        return data, data.get("error") or f"HTTP {response.status_code}"
    return data, None


def check_mcp():
    """True when the backend health check answers."""
    data, err = api("GET", "/api/health", timeout=5)
    return err is None and data is not None


def indexed_domains():
    data, err = api("GET", "/api/sources")
    if err or not data:
        return None
    return {s["domain"] for s in data.get("sources", [])}


# ==================== BANNER ====================
BANNER = r"""
   ▄▄▄▄▄   ▄▄▄▄▄  ▄▄▄▄▄▄   ▄▄▄▄   ▄▄▄▄▄▄  ▄▄▄▄▄▄ ▄▄▄▄▄▄
  █▀       █▀     █▄▄▄▄█  █▄▄▄▄█  █▄▄▄▄█  █▄▄▄   █▄▄▄
   ▀▀▀▀█   █      █   ▀▄  █    █  █       █      █
  ▄▄▄▄▄▀   ▀▄▄▄▄  █    █  █    █  █       █▄▄▄▄▄ █▄▄▄▄▄
"""


def show_banner():
    print(accent(BANNER))
    print(f"  {bold('scrapee')} {dim('v' + VERSION)} — any website, served to your AI over MCP\n")


# ==================== PROJECT DETECTION ====================
def detect_project(root="."):
    """Detect the stacks used in a project directory.

    Returns DOC_MAP keys (react, next, fastapi, ...) in a stable order.
    """
    found = []

    def add(key):
        if key in DOC_MAP and key not in found:
            found.append(key)

    root = Path(root)
    pkg_path = root / "package.json"
    if pkg_path.is_file():
        try:
            pkg = json.loads(pkg_path.read_text())
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            for dep, key in NPM_MAP.items():
                if dep in deps:
                    add(key)
        except (ValueError, OSError):
            pass
        add("nodejs")

    py_text = ""
    for name in ("requirements.txt", "pyproject.toml", "setup.py", "Pipfile"):
        path = root / name
        if path.is_file():
            try:
                py_text += path.read_text(errors="ignore").lower()
            except OSError:
                pass
    if py_text:
        for dep, key in PY_MAP.items():
            if re.search(rf"(^|[\s\"'\[]){dep}\b", py_text, re.M):
                add(key)
        add("python")

    if (root / "Cargo.toml").is_file():
        add("rust")
    if (root / "go.mod").is_file():
        add("go")
    if (root / "tsconfig.json").is_file():
        add("typescript")
    return found


# ==================== CONTEXT PERSISTENCE ====================
def save_context(url):
    """Remember the last URL loaded from this project."""
    CONTEXT_FILE.parent.mkdir(exist_ok=True)
    data = {"last_url": url, "updated": datetime.now(timezone.utc).isoformat()}
    CONTEXT_FILE.write_text(json.dumps(data))


def load_context():
    if CONTEXT_FILE.exists():
        try:
            return json.loads(CONTEXT_FILE.read_text())
        except (ValueError, OSError):
            return {}
    return {}


# ==================== EDITOR CONNECTION ====================
def build_mcp_server_config():
    """Return (server_entry, mode) for .vscode/mcp.json.

    Prefers a local stdio server (editor spawns backend/mcp_stdio.py directly)
    and falls back to the HTTP endpoint.
    """
    if LOCAL_STDIO_SERVER:
        return (
            {
                "type": "stdio",
                "command": stdio_python_for(LOCAL_STDIO_SERVER),
                "args": [str(LOCAL_STDIO_SERVER)],
            },
            "stdio (local)",
        )
    return ({"type": "http", "url": f"{MCP_BASE_URL}/mcp"}, "http")


def connect_vscode(quiet=False):
    """Write the scrapee entry into .vscode/mcp.json, keeping other servers."""
    server_entry, mode = build_mcp_server_config()
    config = {}
    if VSCODE_CONFIG_PATH.is_file():
        try:
            config = json.loads(VSCODE_CONFIG_PATH.read_text())
        except (ValueError, OSError):
            config = {}
    config.setdefault("servers", {})["scrapee"] = server_entry

    try:
        VSCODE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        VSCODE_CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")
    except OSError as e:
        if not quiet:
            print(f"{bad('✗')} could not write {VSCODE_CONFIG_PATH}: {e}")
        return False
    if not quiet:
        print(f"{ok('✓')} editor connected — {mode}")
        print(dim(f"  {VSCODE_CONFIG_PATH} written; reload VS Code to pick it up"))
    return True


# ==================== CODE READING / AUTO-LOAD ====================
def get_project_files(limit=200):
    """Source files in the project, skipping dependencies and build output."""
    files = []
    for root, dirs, filenames in os.walk("."):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if name.endswith(SOURCE_EXTS):
                files.append(os.path.join(root, name))
                if len(files) >= limit:
                    return files
    return files


IMPORT_PATTERNS = [
    re.compile(r"""^\s*import\s+(?:[\w*{}\s,]+\s+from\s+)?['"]([^'"]+)['"]""", re.M),  # JS/TS import
    re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)"""),                            # node require
    re.compile(r"^\s*from\s+([\w.]+)\s+import\b", re.M),                              # python from X import
    re.compile(r"^\s*import\s+([\w.]+)\s*$", re.M),                                   # python import X
]


def extract_imports(files):
    """First path segment of every import in the given files (multi-language)."""
    imports = set()
    for file in files:
        try:
            with open(file, "r", errors="ignore") as f:
                content = f.read(20000)
        except OSError:
            continue
        for pattern in IMPORT_PATTERNS:
            for match in pattern.findall(content):
                if match.startswith("."):
                    continue  # relative import, part of this project
                # "@next/font" → "@next", "react-dom/client" → "react-dom",
                # "fastapi.security" → "fastapi"
                base = match.split("/")[0].split(".")[0].lower().strip()
                if len(base) > 1:
                    imports.add(base)
    return sorted(imports)


def docs_to_load():
    """[(key, url)] the project uses (manifest + imports) and isn't indexed yet."""
    keys = detect_project()
    for imp in extract_imports(get_project_files()):
        key = IMPORT_MAP.get(imp)
        if key and key not in keys:
            keys.append(key)
    if not keys:
        return [], []
    have = indexed_domains() or set()
    missing = [(k, DOC_MAP[k]) for k in keys if urlparse(DOC_MAP[k]).netloc not in have]
    return keys, missing


def auto_load():
    keys, missing = docs_to_load()
    if not keys:
        print(dim("  no known frameworks detected in this project"))
        return
    print(f"  stack     {', '.join(keys)}")
    if not missing:
        print(f"  docs      {ok('all indexed')}")
        return
    for key, url in missing:
        handle_load(url, pages=20, label=key, quiet=True)


# ==================== COMMANDS ====================
def handle_load(url, pages=DEFAULT_PAGES, label=None, quiet=False):
    """Crawl a site and index it."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    label = label or urlparse(url).netloc
    if not quiet:
        print()
    with Spinner(f"crawling {label} (up to {pages} pages)"):
        data, err = api(
            "POST", "/api/scrape", timeout=SCRAPE_TIMEOUT,
            json={"urls": [url], "mode": "smart", "max_pages": pages, "max_depth": 3},
        )

    if err:
        print(f"  {bad('✗')} {label}: {err}")
        return False
    pages_out = data.get("data", [])
    indexed = [p for p in pages_out if p.get("status") == "indexed"]
    skipped = [p for p in pages_out if p.get("status") == "skipped"]
    failed = [p for p in pages_out if p.get("status") in ("failed", "error")]
    if not indexed:
        reason = failed[0].get("error") if failed else (
            "every page was already indexed or too thin" if skipped else "no content found")
        print(f"  {bad('✗')} {label}: {reason}")
        return False

    code = sum(p.get("code_blocks", 0) for p in indexed)
    print(f"  {ok('✓')} {label}: {len(indexed)} pages, {code} code blocks indexed"
          + (dim(f" ({len(skipped)} skipped)") if skipped else ""))
    if not quiet:
        for p in indexed[:6]:
            print(dim(f"      {p.get('title') or p.get('url')}"))
        if len(indexed) > 6:
            print(dim(f"      … and {len(indexed) - 6} more"))
        print(f"\n  your AI client can now answer from {label}\n")
    save_context(url)
    return True


def handle_ask(query):
    """Show exactly what an MCP client receives from get_context."""
    data, err = api("POST", "/api/context", timeout=60, json={"query": query})
    if err:
        print(f"\n  {bad('✗')} {err}\n")
        return
    status = data.get("status")
    if status == "learning":
        seed = data.get("seed", "likely docs")
        print(f"\n  {accent('…')} nothing indexed for that yet — fetching {seed} in the background.")
        print(dim("    ask again in a minute, or /load the docs site yourself.\n"))
        return
    if status == "not_found":
        print(f"\n  {accent('·')} nothing indexed answers that. /load the docs site that covers it.\n")
        return
    sources = data.get("sources", [])
    print(f"\n  {bold(str(len(sources)) + ' sources')} {dim('· intent: ' + str(data.get('intent')))}")
    for s in sources:
        print(f"    {accent('→')} {s}")
    print()
    context = data.get("context", "")
    print("\n".join("  " + line for line in context[:2400].splitlines()))
    if len(context) > 2400:
        print(dim(f"\n  … {len(context) - 2400} more characters"))
    print()


def handle_sources():
    data, err = api("GET", "/api/sources")
    if err:
        print(f"\n  {bad('✗')} {err}\n")
        return
    sources = data.get("sources", [])
    print(f"\n  {bold(str(data.get('total_docs', 0)) + ' pages')} from {len(sources)} sites, "
          f"{data.get('total_code_blocks', 0)} code blocks\n")
    if not sources:
        print(dim("  nothing indexed yet — try /load https://react.dev/learn\n"))
        return
    width = max(len(s["domain"]) for s in sources)
    for s in sources:
        when = (s.get("last_scraped") or "")[:10]
        print(f"  {s['domain'].ljust(width)}  {str(s['docs']).rjust(4)} pages  "
              f"{str(s['code_blocks']).rjust(5)} code  {dim(when)}")
    print()


def handle_remove(domain):
    domain = urlparse(domain).netloc or domain
    data, err = api("DELETE", f"/api/sources/{domain}")
    if err:
        print(f"\n  {bad('✗')} {err}\n")
        return
    removed = data.get("removed", 0)
    mark = ok("✓") if removed else accent("·")
    print(f"\n  {mark} removed {removed} pages from {domain}\n")


def handle_status():
    print()
    print(f"  project   {os.getcwd()}")
    if LOCAL_STDIO_SERVER:
        print(f"  mcp       stdio → {LOCAL_STDIO_SERVER}")
    if check_mcp():
        print(f"  backend   {ok('●')} {MCP_BASE_URL}")
    else:
        print(f"  backend   {bad('●')} {MCP_BASE_URL} {bad('offline')}")
        if LOCAL_STDIO_SERVER:
            print(dim("            start it with: npm run dev:backend"))
    ctx = load_context()
    if ctx.get("last_url"):
        print(f"  last load {ctx['last_url']}")
    handle_sources()


def handle_reset(args=""):
    """Clear this project's context; with 'all', empty the whole index."""
    if CONTEXT_FILE.exists():
        CONTEXT_FILE.unlink()
        print(f"\n  {ok('✓')} local context cleared")
    if args.strip() != "all":
        print(dim("  (to empty the whole index too: /reset all)\n"))
        return
    try:
        answer = input(f"  empty the index at {MCP_BASE_URL}? this deletes every page [y/N] ")
    except EOFError:
        answer = ""
    if answer.strip().lower() not in ("y", "yes"):
        print(dim("  kept the index\n"))
        return
    data, err = api("POST", "/api/reset", json={"confirm": True})
    if err:
        print(f"  {bad('✗')} {err}\n")
        return
    print(f"  {ok('✓')} index emptied ({data.get('removed', 0)} pages)\n")


HELP = """
  /load <url> [pages]   crawl a site and index it (default {pages} pages)
  /ask <question>       preview what your AI client gets from get_context
  /sources              list indexed sites
  /remove <domain>      drop a site from the index
  /status               backend, editor link and index summary
  /connect              rewrite .vscode/mcp.json
  /reset [all]          clear local context (all: empty the index)
  /help  /exit
"""


def show_help():
    print(HELP.format(pages=DEFAULT_PAGES))


# ==================== BOOT + REPL ====================
def boot(auto=True):
    show_banner()
    connect_vscode(quiet=True)
    print(f"  project   {os.getcwd()}")
    _, mode = build_mcp_server_config()
    print(f"  editor    .vscode/mcp.json → {mode}")
    online = check_mcp()
    if online:
        print(f"  backend   {ok('●')} {MCP_BASE_URL}")
    else:
        print(f"  backend   {bad('●')} {MCP_BASE_URL} {bad('offline')}")
        if LOCAL_STDIO_SERVER:
            print(dim("            start it with: npm run dev:backend"))
    if online and auto:
        auto_load()
    print(dim("\n  type /help for commands\n"))


def dispatch(line):
    """Run one REPL command. Returns False when the session should end."""
    cmd, _, rest = line.partition(" ")
    rest = rest.strip()
    cmd = cmd.lower()

    if cmd in ("/exit", "/quit", "exit", "quit"):
        return False
    if cmd in ("/help", "help", "?"):
        show_help()
    elif cmd in ("/load", "/scrape"):
        if not rest:
            print("  usage: /load <url> [pages]\n")
        else:
            parts = rest.split()
            pages = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else DEFAULT_PAGES
            handle_load(parts[0], pages=max(1, min(pages, 250)))
    elif cmd == "/ask":
        if rest:
            handle_ask(rest)
        else:
            print("  usage: /ask <question>\n")
    elif cmd in ("/sources", "/ls"):
        handle_sources()
    elif cmd in ("/remove", "/rm"):
        if rest:
            handle_remove(rest)
        else:
            print("  usage: /remove <domain>\n")
    elif cmd == "/status":
        handle_status()
    elif cmd == "/connect":
        connect_vscode()
    elif cmd == "/reset":
        handle_reset(rest)
    elif line.startswith(("http://", "https://")):
        handle_load(line)
    else:
        print(dim("  unknown command — type /help\n"))
    return True


def run():
    boot(auto="--no-auto" not in sys.argv)
    prompt = accent("scrapee› ") if _COLOR else "scrapee> "
    while True:
        try:
            line = input(prompt).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break
        if line and not dispatch(line):
            break


USAGE = f"""scrapee {VERSION} — any website, served to your AI over MCP

usage:
  scrapee                       interactive session (auto-loads your stack's docs)
  scrapee load <url> [--pages N]
  scrapee ask "<question>"
  scrapee sources | status | connect
  scrapee remove <domain>

options:
  --no-auto       skip auto-loading docs on start
  -v, --version   print version

backend: {MCP_BASE_URL}  (override with SCRAPEE_BASE_URL)
"""


def main(argv):
    args = [a for a in argv if a != "--no-auto"]
    if not args:
        run()
        return 0
    if args[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    if args[0] in ("-v", "--version"):
        print(VERSION)
        return 0

    cmd, rest = args[0], args[1:]
    if cmd in ("load", "scrape") and rest:
        pages = DEFAULT_PAGES
        if "--pages" in rest:
            i = rest.index("--pages")
            pages = int(rest[i + 1]) if i + 1 < len(rest) and rest[i + 1].isdigit() else pages
            rest = rest[:i] + rest[i + 2:]
        return 0 if handle_load(rest[0], pages=pages) else 1
    if cmd == "ask" and rest:
        handle_ask(" ".join(rest))
        return 0
    if cmd in ("sources", "ls"):
        handle_sources()
        return 0
    if cmd == "status":
        handle_status()
        return 0
    if cmd == "connect":
        return 0 if connect_vscode() else 1
    if cmd in ("remove", "rm") and rest:
        handle_remove(rest[0])
        return 0
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
