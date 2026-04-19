# GitHub Repository Scraping Guide

When you scrape a GitHub repository with Scrapee, you now get **intelligent project overview extraction** instead of just metadata tables.

## What Gets Extracted

### 1. **README.md Content**
The project description and overview from the repository's README file.

**Example:**
```
"A DevOps automation toolkit for CI/CD pipeline management and infrastructure provisioning..."
```

### 2. **Repository Structure**
Automatically identifies key directories and files:
- **Main directories**: `src/`, `lib/`, `main/`, `app/`, `code/`
- **Key entry files**: `main.py`, `app.py`, `index.js`, `setup.py`, `package.json`, `pom.xml`
- **Programming languages**: Detected from the repository metadata

**Example Structure:**
```json
{
  "directories": ["src", "lib", "tests"],
  "key_files": ["main.py", "app.py"],
  "languages": ["Python"]
}
```

### 3. **Source Code Overview**
When diving into the `src/` folder, you get:
- Function and class definitions
- Import statements
- Module descriptions
- Code snippets for key functionality

## Usage Examples

### Query 1: "What does this project do?"
```bash
POST /mcp
{
  "method": "tools/call",
  "params": {
    "name": "search_and_get",
    "arguments": {
      "query": "what does devopsct do"
    }
  }
}
```

**Response:**
```json
{
  "title": "DevOps Automation Toolkit",
  "snippet": "A DevOps automation toolkit for CI/CD pipeline management... Main directories: src, lib, tests",
  "url": "https://github.com/jonathanvineet/devopsct"
}
```

### Query 2: "Show me the main entry point"
```bash
{
  "name": "search_code",
  "arguments": {
    "query": "main function entry point"
  }
}
```

**Response:**
Returns main.py or app.py with function definitions and imports.

### Query 3: "What are the key modules?"
```bash
{
  "name": "search_docs",
  "arguments": {
    "query": "deploy provision CI/CD pipeline"
  }
}
```

**Response:**
Lists relevant modules from src/ that implement these features.

## How It Works

When you scrape a GitHub repo URL like `https://github.com/jonathanvineet/devopsct`:

1. **Detects GitHub URL** - Checks if URL is from github.com
2. **Fetches README** - Gets raw README.md content
   ```
   https://raw.githubusercontent.com/jonathanvineet/devopsct/main/README.md
   ```
3. **Parses Repository HTML** - Extracts folder structure from the GitHub repo page
4. **Identifies Key Files** - Looks for main.py, app.py, setup.py, package.json, etc.
5. **Detects Languages** - Gets programming language from GitHub metadata
6. **Creates Project Overview** - Combines all info into searchable content

## Special GitHub Features

### Automatic File Discovery
When you search for specific functions or features, it automatically:
- Looks in `src/` directory
- Searches through Python, JavaScript, Java source files
- Extracts code blocks with context
- Returns the most relevant matches

### Folder-Aware Search
Searches understand repository structure:
- Query "module X" → searches `src/X/`, `lib/X/`
- Query "test Y" → searches `tests/Y/`
- Query "config" → searches `config.py`, `settings.json`, etc.

### Multi-File Context
When showing code snippets:
- Includes imports and dependencies
- Shows related functions in the same file
- Provides function signatures and docstrings
- Links back to GitHub source

## Example: Analyzing the devopsct Project

```bash
# Step 1: Scrape the repo
POST /api/scrape
{
  "url": "https://github.com/jonathanvineet/devopsct",
  "mode": "smart"
}

# Returns:
{
  "success": true,
  "scraped_count": 1,
  "indexed_count": 1,
  "sample_docs": [{
    "title": "GitHub: devopsct",
    "url": "https://github.com/jonathanvineet/devopsct",
    "snippet": "DevOps automation toolkit... Main directories: src, lib, tests | Languages: Python"
  }]
}

# Step 2: Ask about the project
POST /mcp
{
  "name": "search_and_get",
  "arguments": {
    "query": "how to deploy applications"
  }
}

# Returns modules and functions related to deployment

# Step 3: Get code examples
POST /mcp
{
  "name": "search_code",
  "arguments": {
    "query": "deploy function",
    "language": "python"
  }
}

# Returns Python code snippets showing deployment logic
```

## Troubleshooting

### Problem: Getting table/schema data instead of README
**Solution:** The new GitHub extraction is automatic. Make sure you're using the latest version of the code.

### Problem: Source files not being indexed
**Solution:** The crawler will dive into `src/` automatically. If specific files aren't found:
1. Check they exist in the repository
2. Try scraping with `max_depth=3` to go deeper
3. Use `search_code` instead of `search_docs` for code-specific queries

### Problem: No overview found
**Solution:** README might not exist or be named differently. The system will still extract:
- Folder structure
- Key files
- Programming languages
Use these to understand the project structure.

## Implementation Details

**Files Modified:**
- `backend/smart_scraper.py` - Added `extract_from_github()`, `_extract_github_readme()`, `_extract_github_src_overview()`

**Methods:**
```python
# Get GitHub repo overview
scraper.extract_from_github(url)

# Get README content only
scraper._extract_github_readme(url)

# Get directory structure
scraper._extract_github_src_overview(url)
```

**Search Integration:**
- GitHub repos automatically use GitHub extraction method
- Results include README content, structure, and overview
- Code search works across all extracted source files

## Limitations

- Works with public GitHub repositories
- Private repos require authentication (coming soon)
- Binary files (images, PDFs) are skipped
- Very large repos (1000+ files) may take longer to index

## Next Steps

- [ ] Add GitHub API support for faster fetching
- [ ] Add private repository authentication
- [ ] Extract GitHub Issues/Discussions as documentation
- [ ] Add GitHub Actions workflow analysis
- [ ] Cache GitHub repo metadata for faster re-queries
