# Building & Distributing Scrapee CLI

## Quick Start

The CLI is ready to use directly as a Python script:

```bash
python3 cli/scrapee.py
```

Or install with pip:

```bash
pip install -e .
scrapee
```

---

## Building Standalone Binaries

For distribution, build standalone executables with PyInstaller.

### Prerequisites

```bash
pip install PyInstaller
```

### Build for your platform

```bash
# macOS or Linux
pyinstaller \
  --onefile \
  --name scrapee \
  --add-data "cli/scrapee.py:." \
  cli/scrapee.py

# Output: dist/scrapee
```

### Cross-compilation (advanced)

On macOS (requires cross-compilation toolchain):

```bash
# Intel Mac
pyinstaller --onefile cli/scrapee.py --name scrapee-darwin-x86-64

# Apple Silicon (native build on M1/M2/M3)
pyinstaller --onefile cli/scrapee.py --name scrapee-darwin-arm64
```

On Linux:

```bash
# x86-64
pyinstaller --onefile cli/scrapee.py --name scrapee-linux-x86

# ARM64
pyinstaller --onefile cli/scrapee.py --name scrapee-linux-arm64
```

On Windows (or in CI):

```bash
pyinstaller --onefile cli/scrapee.py --name scrapee-windows-x86-64.exe
```

---

## Creating GitHub Releases

1. Build all binaries
2. Create a tag and release on GitHub:

```bash
git tag v1.0.0
git push origin v1.0.0
```

3. Upload binaries to the release:
   - `scrapee-darwin-x86-64`
   - `scrapee-darwin-arm64`
   - `scrapee-linux-x86`
   - `scrapee-linux-arm64`
   - `scrapee-windows-x86-64.exe`

---

## Installation Methods

### 1. Homebrew (macOS)

Users add your tap and install:

```bash
brew tap jonathanvineet/scrapee
brew install scrapee
```

(Requires the `homebrew-scrapee` repo with the formula.)

### 2. Curl Install (macOS / Linux)

```bash
curl -fsSL https://yourdomain/install.sh | sh
```

or from GitHub:

```bash
curl -fsSL https://raw.githubusercontent.com/jonathanvineet/scrapee/main/scripts/install.sh | sh
```

### 3. PowerShell Install (Windows)

```powershell
iwr https://yourdomain/install.ps1 | iex
```

or from GitHub:

```powershell
iwr https://raw.githubusercontent.com/jonathanvineet/scrapee/main/scripts/install.ps1 | iex
```

### 4. Pip Install (Python developers)

```bash
pip install scrapee-cli
```

(Requires publishing to PyPI.)

---

## CI/CD (GitHub Actions)

Create `.github/workflows/build.yml`:

```yaml
name: Build and Release

on:
  push:
    tags: ["v*"]

jobs:
  build:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [macos-latest, ubuntu-latest, windows-latest]

    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: 3.10

      - name: Install dependencies
        run: pip install PyInstaller

      - name: Build
        run: |
          pyinstaller --onefile cli/scrapee.py --name scrapee

      - name: Upload artifacts
        uses: softprops/action-gh-release@v1
        with:
          files: dist/*
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

---

## Verification

Test your installation:

```bash
scrapee --help
scrapee scrape https://example.com
scrapee ask "your question"
```

---

## Environment Variables

- `SCRAPEE_MCP_URL` — Override MCP endpoint (default: `http://localhost:8080/mcp`)

```bash
export SCRAPEE_MCP_URL=https://api.scrapee.dev/mcp
scrapee
```

---

## Troubleshooting

### "command not found: scrapee"

- Check that `/usr/local/bin` is in your `$PATH`
- Try: `echo $PATH`
- If missing, add to your shell profile: `export PATH="/usr/local/bin:$PATH"`

### "Failed to download"

- Check internet connection
- Verify release binaries exist on GitHub
- Try manual download and `chmod +x scrapee`

### MCP connection errors

- Ensure backend is running
- Check `SCRAPEE_MCP_URL` is correct
- Try: `curl -X POST http://localhost:8080/mcp`

---

## Next Steps

1. Build binaries for all platforms
2. Create a GitHub release with all binaries
3. Set up Homebrew formula (with correct SHA256 hashes)
4. Update install scripts to point to your GitHub URLs
5. Publish to PyPI for pip installation
6. Update this guide with your actual URLs

---

Happy building! 🚀
