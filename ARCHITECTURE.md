# Complete Architecture: Frontend → Backend → Vercel + Redis

## Overview

```
Frontend (Next.js)
├─ User gives URL: https://docs.expo.dev/
└─ Calls backend scrape_url
       ↓
Backend on Vercel (Serverless)
├─ SmartCrawler discovers 30 pages
├─ SmartScraper extracts code from each page
├─ Stores in /tmp SQLite (ephemeral)
└─ Pushes to Redis (persistent)
       ↓
Redis Database (Persistent)
├─ Stores full SQLite database
├─ Survives Vercel deployments
└─ Accessible to all instances
       ↓
VSCode with MCP
├─ Connects to Backend on Vercel
├─ Asks: "How to auth in Expo?"
├─ Backend searches Redis-backed database
└─ Returns 30 pages of results + all code blocks
```

## Data Flow

### Scraping Phase

```
1. Frontend: scrape_url("https://docs.expo.dev/")
   ↓
2. Backend SmartCrawler:
   - Crawl seed page
   - Extract links
   - Follow links (max_depth=2)
   - Discover ~30 pages total
   ↓
3. For each page:
   - SmartScraper extracts content
   - SmartScraper extracts code blocks (7-50 blocks per page)
   - Save to SQLite in /tmp
   ↓
4. After all pages saved:
   - Push entire SQLite DB to Redis
   - Redis persists it forever
   ↓
5. Response: "Stored 30 pages, 245 code blocks total"
```

### Search Phase (VSCode)

```
1. VSCode MCP: search_and_get("authentication setup")
   ↓
2. Backend on Vercel:
   - Check /tmp SQLite (empty on cold start)
   - Pull full DB from Redis
   - Search across all 30 pages
   ↓
3. Return to VSCode:
   - 5 docs about authentication
   - 20 code blocks related to auth
   - Full content + snippets
   ↓
4. User sees everything in VSCode!
```

## Why Redis?

### Problem with /tmp only:
- ❌ Deleted on each Vercel deployment
- ❌ Lost between requests
- ❌ Can't persist across day

### Solution with Redis:
- ✅ Persists across deployments
- ✅ Shared across all Vercel instances
- ✅ Data survives forever
- ✅ Cold starts pull from Redis (instant)

## Setup Required

### For Vercel KV (Recommended):

1. **Go to Vercel Dashboard**
   ```
   https://vercel.com/dashboard
   → Select scrapee-backend
   → Storage tab
   → Create → KV
   ```

2. **Done!** 
   - Vercel auto-adds `KV_URL` env var
   - Backend auto-detects it
   - Push to deploy

### For External Redis:

1. **Get Redis URL**
   ```
   redis://default:PASSWORD@HOST:PORT
   ```

2. **Add to Vercel**
   ```
   Settings → Environment Variables
   REDIS_URL = redis://...
   ```

3. **Deploy**
   ```bash
   git push origin main
   ```

## Files Structure

```
backend/
├── storage/
│   └── sqlite_store.py
│       ├── _default_db_path() → /tmp on Vercel
│       ├── _pull_from_redis() → Download DB on startup
│       ├── _push_to_redis() → Upload DB after changes
│       └── save_doc() → Auto-syncs to Redis
│
├── mcp.py
│   └── _tool_scrape_url()
│       ├── Creates crawler with max_depth=2
│       ├── Discovers 30 pages
│       ├── Saves each with code blocks
│       └── Returns stored_urls
│
└── smart_crawler.py
    ├── crawl() → Returns list of ScrapedDocument
    └── Each ScrapedDocument has code_blocks
```

## Example Workflow

### Session 1: Scrape Documentation

```bash
# User gives frontend a URL
> scrape_url("https://docs.expo.dev/")

# Backend:
# - Crawls 30 pages
# - Extracts 245 code blocks
# - Stores in SQLite
# - Pushes to Redis
# Result: "Stored 30 pages"
✅ Done
```

### Session 2: Ask Questions (VSCode)

```bash
# Next day, user connects VSCode to MCP
# Backend pulls all 30 pages from Redis instantly
✅ Cold start pulls from Redis (0.5s)

# User asks:
> search_and_get("How to set up OAuth?")

# Backend searches all 30 pages at once
# Returns: "5 docs + 20 code blocks about OAuth"
✅ User gets complete answer
```

## Persistence Proof

1. **After first scrape:**
   - Redis contains full SQLite DB (1-5 MB)
   - All 30 pages + 245 code blocks stored

2. **Redeploy backend:**
   - Vercel resets `/tmp`
   - Backend pulls from Redis
   - All 30 pages still available
   - Searches work immediately

3. **Add more URLs:**
   - Scrape new URL
   - Gets merged with existing 30 pages
   - Synced to Redis
   - Everything still searchable

## Monitoring

### Check if Redis is working:

```bash
# View deployment logs
vercel logs --follow scrapee-backend

# Look for these messages:
✓ Redis connected for SQLite persistence
✓ Pulled SQLite database from Redis (... bytes)
✓ Pushed SQLite database to Redis (... bytes)

# Or errors like:
⚠ Redis connection failed: ...
⚠ Failed to pull DB from Redis: ...
```

### If Redis not working:

1. Check KV exists in Vercel Storage tab
2. Check KV_URL env var is set
3. Wait 2 minutes (KV needs time to start)
4. Redeploy: `git push origin main`
5. Check logs again

## Summary

✅ Frontend scrapes URLs  
✅ Backend stores in SQLite + Redis  
✅ VSCode searches across all pages  
✅ Data persists forever on Vercel  
✅ Code blocks always available  
✅ Agent gets complete context  

**You now have a production-grade documentation search engine!** 🚀
