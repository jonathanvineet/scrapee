"""
GitHub Repository Understanding Engine.

Understands an ENTIRE GitHub repository — not just one file:
  - Fetches the file tree via GitHub API (no authentication required for public repos)
  - Reads README, main entry points, and key source files
  - Extracts: purpose, architecture, public API surface, dependencies, code patterns
  - Stores a rich structured summary in the MCP index

Usage:
    engine = GitHubRepoEngine()
    result = engine.understand("https://github.com/user/repo")
"""
import json
import re
import time
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests

# GitHub API rate limit: 60 req/hour unauthenticated, 5000/hour with token
GITHUB_TOKEN = None  # Set GITHUB_TOKEN env var for higher rate limits
REQUEST_TIMEOUT = 10

# Files that reveal the most about a repo's purpose and API
PRIORITY_FILES = [
    "README.md", "readme.md", "README.rst",
    "setup.py", "setup.cfg", "pyproject.toml",
    "package.json", "Cargo.toml", "go.mod",
    "index.js", "index.ts", "main.py", "main.go", "main.rs",
    "src/index.js", "src/index.ts", "src/main.py",
    "src/lib.rs", "src/lib.js", "src/lib.ts",
    "CHANGELOG.md", "ARCHITECTURE.md", "DESIGN.md",
]

# File extensions we actually read (skip binaries, media, etc.)
READABLE_EXTENSIONS = {
    ".md", ".txt", ".rst", ".py", ".js", ".ts", ".jsx", ".tsx",
    ".go", ".rs", ".java", ".cpp", ".c", ".h", ".rb", ".php",
    ".yaml", ".yml", ".toml", ".json", ".env.example",
}

MAX_FILE_SIZE_BYTES = 64_000  # Skip files > 64 KB (usually generated/data files)
MAX_FILES_TO_READ = 20       # Read at most 20 source files per repo


class GitHubRepoEngine:
    """Understands entire GitHub repositories from structure + key files."""

    def __init__(self):
        import os
        token = os.getenv("GITHUB_TOKEN")
        self.headers = {"Accept": "application/vnd.github.v3+json"}
        if token:
            self.headers["Authorization"] = f"token {token}"

    # ──────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────

    def understand(self, repo_url: str) -> Dict:
        """Build a full semantic understanding of a GitHub repository.

        Returns a rich dict suitable for storing in the MCP index.
        """
        owner, repo = self._parse_repo_url(repo_url)
        if not owner or not repo:
            return {"error": f"Cannot parse GitHub URL: {repo_url}"}

        print(f"[GITHUB] Understanding {owner}/{repo}")

        # Parallel fetch: metadata + tree
        metadata = self._fetch_repo_metadata(owner, repo)
        if "error" in metadata:
            return metadata

        tree = self._fetch_file_tree(owner, repo)
        priority_files = self._select_priority_files(tree)

        print(f"[GITHUB] Reading {len(priority_files)} key files from {len(tree)} total")

        # Read files
        file_contents: Dict[str, str] = {}
        for path in priority_files[:MAX_FILES_TO_READ]:
            content = self._fetch_file(owner, repo, path)
            if content:
                file_contents[path] = content
            time.sleep(0.1)  # gentle rate limiting

        # Build structured understanding
        understanding = self._build_understanding(metadata, tree, file_contents)
        understanding["repo_url"] = repo_url
        understanding["owner"] = owner
        understanding["repo"] = repo

        print(f"[GITHUB] Understanding complete: {len(understanding.get('content', ''))} chars")
        return understanding

    # ──────────────────────────────────────────
    # Fetch helpers
    # ──────────────────────────────────────────

    def _fetch_repo_metadata(self, owner: str, repo: str) -> Dict:
        """Fetch core repo metadata from GitHub API."""
        url = f"https://api.github.com/repos/{owner}/{repo}"
        try:
            r = requests.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT)
            if r.status_code == 404:
                return {"error": f"Repository not found: {owner}/{repo}"}
            if r.status_code == 403:
                return {"error": "GitHub API rate limit exceeded. Set GITHUB_TOKEN env var."}
            r.raise_for_status()
            data = r.json()
            return {
                "name": data.get("name", ""),
                "full_name": data.get("full_name", ""),
                "description": data.get("description", ""),
                "language": data.get("language", ""),
                "topics": data.get("topics", []),
                "stars": data.get("stargazers_count", 0),
                "forks": data.get("forks_count", 0),
                "default_branch": data.get("default_branch", "main"),
                "homepage": data.get("homepage", ""),
                "license": (data.get("license") or {}).get("name", ""),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
                "open_issues": data.get("open_issues_count", 0),
            }
        except Exception as e:
            return {"error": f"GitHub API error: {e}"}

    def _fetch_file_tree(self, owner: str, repo: str, branch: str = "main") -> List[str]:
        """Return flat list of all file paths in the repo."""
        for b in [branch, "master", "dev", "develop"]:
            url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{b}?recursive=1"
            try:
                r = requests.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT)
                if r.status_code == 200:
                    data = r.json()
                    return [
                        item["path"]
                        for item in data.get("tree", [])
                        if item.get("type") == "blob"
                    ]
            except Exception:
                continue
        return []

    def _fetch_file(self, owner: str, repo: str, path: str) -> Optional[str]:
        """Fetch raw file content. Returns None on failure or if file is too large."""
        # Check extension
        ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if ext and ext not in READABLE_EXTENSIONS:
            return None

        url = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{path}"
        try:
            r = requests.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT)
            if r.status_code != 200:
                return None
            if len(r.content) > MAX_FILE_SIZE_BYTES:
                return r.text[:MAX_FILE_SIZE_BYTES]  # truncate large files
            return r.text
        except Exception:
            return None

    # ──────────────────────────────────────────
    # Selection
    # ──────────────────────────────────────────

    def _select_priority_files(self, tree: List[str]) -> List[str]:
        """Pick the most informative files from the tree."""
        selected = []
        tree_set = set(tree)

        # Exact matches first
        for pf in PRIORITY_FILES:
            if pf in tree_set:
                selected.append(pf)

        # Then readable extensions, sorted by depth (shallower = more important)
        for path in sorted(tree, key=lambda p: (p.count("/"), p)):
            if path in selected:
                continue
            ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
            if ext in READABLE_EXTENSIONS:
                # Skip test files, examples, auto-generated
                lower = path.lower()
                if any(skip in lower for skip in ["test", "spec", "__pycache__",
                                                   "node_modules", ".git", "dist/",
                                                   "build/", "generated", "vendor/"]):
                    continue
                selected.append(path)
            if len(selected) >= MAX_FILES_TO_READ:
                break

        return selected

    # ──────────────────────────────────────────
    # Understanding builder
    # ──────────────────────────────────────────

    def _build_understanding(
        self,
        metadata: Dict,
        tree: List[str],
        files: Dict[str, str],
    ) -> Dict:
        """Synthesize all fetched data into a searchable understanding."""

        readme = files.get("README.md") or files.get("readme.md") or ""
        readme_summary = readme[:3000] if readme else ""

        # Extract dependencies
        deps = self._extract_dependencies(files)

        # Extract public functions/classes from key files
        api_surface = self._extract_api_surface(files)

        # Detect project type
        project_type = self._detect_project_type(tree, files, metadata)

        # Build content blob (what gets stored and searched)
        parts = []

        name = metadata.get("full_name") or metadata.get("name", "")
        desc = metadata.get("description", "")
        language = metadata.get("language", "")
        topics = " ".join(metadata.get("topics", []))

        parts.append(f"# {name}")
        if desc:
            parts.append(f"\n{desc}\n")
        if language:
            parts.append(f"**Language:** {language}")
        if topics:
            parts.append(f"**Topics:** {topics}")
        parts.append(f"**Stars:** {metadata.get('stars', 0)}")
        parts.append(f"**Type:** {project_type}")

        if readme_summary:
            parts.append(f"\n## README\n{readme_summary}")

        if deps:
            parts.append(f"\n## Dependencies\n" + "\n".join(f"- {d}" for d in deps[:30]))

        if api_surface:
            parts.append(f"\n## API Surface\n" + "\n".join(f"- `{s}`" for s in api_surface[:50]))

        # File tree summary (first 50 files)
        tree_summary = "\n".join(tree[:50])
        parts.append(f"\n## File Structure\n```\n{tree_summary}\n```")

        content = "\n".join(parts)

        # Extract code blocks from key source files
        code_blocks = []
        for path, src in files.items():
            if not src:
                continue
            lang = self._detect_language(path)
            # Extract top 100 lines of each file as a code block
            snippet = "\n".join(src.splitlines()[:100])
            if len(snippet) > 100:
                code_blocks.append({
                    "snippet": snippet,
                    "language": lang,
                    "context": f"file: {path}",
                    "line_number": 1,
                })

        return {
            "content": content,
            "code_blocks": code_blocks[:15],  # cap at 15 blocks
            "metadata": {
                "title": f"{name} — {desc[:80]}" if desc else name,
                "language": language,
                "domain": "github.com",
                "repo_metadata": metadata,
                "project_type": project_type,
                "dependencies": deps,
                "api_surface": api_surface[:30],
                "files_read": list(files.keys()),
                "total_files": len(tree),
            },
            "topics": [
                {"topic": t, "heading": "", "level": 1, "content": ""}
                for t in metadata.get("topics", [])
            ],
        }

    # ──────────────────────────────────────────
    # Extraction helpers
    # ──────────────────────────────────────────

    def _extract_dependencies(self, files: Dict[str, str]) -> List[str]:
        """Extract dependency names from package manifests."""
        deps = []
        # Python
        for fname in ["setup.py", "setup.cfg", "pyproject.toml", "requirements.txt"]:
            content = files.get(fname, "")
            if content:
                deps += re.findall(r"['\"]?([\w-]+)(?:[>=<!\[]|['\"])", content)
        # Node
        pkg = files.get("package.json")
        if pkg:
            try:
                data = json.loads(pkg)
                deps += list(data.get("dependencies", {}).keys())
                deps += list(data.get("devDependencies", {}).keys())
            except Exception:
                pass
        # Rust
        cargo = files.get("Cargo.toml")
        if cargo:
            deps += re.findall(r"^([\w-]+)\s*=", cargo, re.MULTILINE)
        # Go
        go_mod = files.get("go.mod")
        if go_mod:
            deps += re.findall(r"^\s+([\w./\-]+)\s+v", go_mod, re.MULTILINE)

        # Dedupe + filter garbage
        seen = set()
        clean = []
        for d in deps:
            d = d.strip().strip("\"'")
            if len(d) > 1 and d not in seen and not d.startswith("#"):
                seen.add(d)
                clean.append(d)
        return clean

    def _extract_api_surface(self, files: Dict[str, str]) -> List[str]:
        """Extract public function/class/export names from source files."""
        surface = []
        for path, content in files.items():
            if not content:
                continue
            lang = self._detect_language(path)

            if lang == "python":
                surface += re.findall(r"^(?:async\s+)?def\s+([\w]+)\s*\(", content, re.MULTILINE)
                surface += re.findall(r"^class\s+([\w]+)", content, re.MULTILINE)
            elif lang in ("javascript", "typescript"):
                surface += re.findall(r"export\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|let)\s+([\w]+)", content)
                surface += re.findall(r"^(?:export\s+)?function\s+([\w]+)", content, re.MULTILINE)
            elif lang == "go":
                surface += re.findall(r"^func\s+(?:\([^)]+\)\s+)?([\w]+)\s*\(", content, re.MULTILINE)
            elif lang == "rust":
                surface += re.findall(r"^pub\s+fn\s+([\w]+)", content, re.MULTILINE)

        # Dedupe, filter private/very-short names
        seen = set()
        clean = []
        for name in surface:
            if name.startswith("_") or name.startswith("test") or len(name) < 2:
                continue
            if name not in seen:
                seen.add(name)
                clean.append(name)
        return clean

    def _detect_project_type(
        self, tree: List[str], files: Dict[str, str], metadata: Dict
    ) -> str:
        """Classify the repo by project type."""
        tree_str = " ".join(tree).lower()
        file_names = set(p.lower().split("/")[-1] for p in tree)
        lang = (metadata.get("language") or "").lower()

        if "package.json" in file_names:
            pkg_json = files.get("package.json", "")
            if "react" in pkg_json or "next" in pkg_json:
                return "React / Next.js app"
            if "express" in pkg_json or "fastify" in pkg_json:
                return "Node.js backend"
            return "Node.js project"
        if "setup.py" in file_names or "pyproject.toml" in file_names:
            if "fastapi" in tree_str or "flask" in tree_str:
                return "Python web API"
            if "lib" in tree_str or "src" in tree_str:
                return "Python library"
            return "Python project"
        if "cargo.toml" in file_names:
            return "Rust project"
        if "go.mod" in file_names:
            return "Go project"
        if lang == "java":
            return "Java project"
        if "dockerfile" in file_names:
            return "Containerised service"
        return f"{lang.title()} project" if lang else "Unknown"

    def _detect_language(self, path: str) -> str:
        ext_map = {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".jsx": "javascript", ".tsx": "typescript",
            ".go": "go", ".rs": "rust", ".java": "java",
            ".rb": "ruby", ".php": "php", ".cpp": "cpp", ".c": "c",
            ".md": "markdown", ".yaml": "yaml", ".yml": "yaml",
            ".toml": "toml", ".json": "json",
        }
        if "." in path:
            ext = "." + path.rsplit(".", 1)[-1].lower()
            return ext_map.get(ext, "text")
        return "text"

    # ──────────────────────────────────────────
    # URL parsing
    # ──────────────────────────────────────────

    def _parse_repo_url(self, url: str) -> Tuple:
        """Extract (owner, repo) from https://github.com/owner/repo[/...]"""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if "github.com" not in parsed.netloc:
            return None, None
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 2:
            return None, None
        return parts[0], parts[1].rstrip(".git")


# Type hint fix
from typing import Tuple
