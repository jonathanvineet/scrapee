# 🚀 Vercel Deployment: Complete Setup Guide

## What You've Got

Your backend is **production-ready** for Vercel with persistent Redis storage. Here's what's already built:

### ✅ Already Implemented

1. **Multi-page web scraper**
   - Crawls from root URL
   - Discovers & crawls child pages
   - Extracts code blocks from each page
   - Stores everything to SQLite

2. **Redis persistence layer**
   - Automatic upload after scraping
   - Automatic download on startup
   - Survives Vercel deployments
   - Works with Vercel KV or external Redis

3. **MCP search tools**
   - `scrape_url` → Crawl & store pages
   - `search_and_get` → Search across all pages
   - `search_code` → Find code blocks
   - `get_doc` → Retrieve full document

## 3-Minute Setup for Vercel

### Step 1: Create Redis Database

**Option A: Vercel KV (Recommended)**
```
1. Go to https://vercel.com/dashboard
2. Select "scrapee-backend" project  
3. Click "Storage" tab
4. Click "Create Database" → "KV"
5. Wait for it to be created (30 seconds)
   → Vercel auto-adds KV_URL to env vars
```

**Option B: External Redis**
```
1. Get Redis URL from provider (Redis Labs, AWS, etc)
2. Go to Vercel project Settings
3. Add env var: REDIS_URL = redis://default:password@host:port
```

### Step 2: Deploy

```bash
cd /Users/jonathan/elco/scrapee

# Commit changes
git add -A
git commit -m "Add Vercel KV persistence for multi-page crawling"
git push origin main

# Vercel deploys automatically
# Check https://vercel.com/dashboard for deployment status
```

### Step 3: Verify in Logs

```bash
# Watch deployment logs
vercel logs --follow scrapee-backend

# Look for:
✓ Redis connected for SQLite persistence
✓ Pulled SQLite database from Redis
✓ Pushed SQLite database to Redis
```

## How It Works

### First Request (Scraping)

```
User: "Scrape https://docs.expo.dev/"
  ↓
Backend:
  1. SmartCrawler discovers 30 pages
  2. SmartScraper extracts code from each
  3. Saves to /tmp SQLite
  4. Pushes entire DB to Redis
  ↓
Response: "Stored 30 pages, 245 code blocks"
  ↓
Redis now has all 30 pages forever
```

### Later Request (Searching)

```
User: "How to setup authentication?"
  ↓
Backend:
  1. Pulls all 30 pages from Redis
  2. Searches across them
  3. Returns relevant docs + code blocks
  ↓
Response: "Found 5 docs + 20 code examples"
```

### After Vercel Redeploy

```
Vercel resets /tmp (ephemeral)
  ↓
Backend starts:
  1. Pulls full database from Redis
  2. All 30 pages available again
  3. Searches work immediately
  ↓
No data loss!
```

## Environment Variables

Vercel KV automatically adds `KV_URL`. Alternatively, set `REDIS_URL`:

```env
# Automatically set by Vercel KV
KV_URL=redis://default:password@hostname:port

# Or manually set for external Redis
REDIS_URL=redis://default:password@hostname:port

# Optional
FLASK_ENV=production
SCRAPEE_SQLITE_PATH=/tmp/scrapee/docs.db
```

## Testing the Complete Flow

### 1. Scrape Documentation

```
In VSCode with MCP:

Tool: scrape_url
Arguments:
  url: "https://docs.expo.dev/"
  mode: "smart"
  max_depth: 2

Expected Output:
  "stored_urls": [30 pages...]
  "pages_scraped": 30
```

### 2. Check Logs

```bash
vercel logs --follow scrapee-backend

Should see:
[DEBUG] Saving doc: 'https://docs.expo.dev/develop/authentication'
[DEBUG] Code blocks to insert: 7 (raw: 7)
✓ Pushed SQLite database to Redis (1234567 bytes)
```

### 3. Search Across All Pages

```
In VSCode with MCP:

Tool: search_and_get
Arguments:
  query: "How to setup OAuth in Expo Router"
  limit: 5

Expected Output:
  "total": 5
  "results": [
    {
      "url": "https://docs.expo.dev/develop/authentication",
      "content": "...",
      "code_blocks": [...]
    },
    ...
  ]
```

### 4. Verify Persistence

```bash
# After first scrape, redeploy backend
git push origin main

# Wait for deployment

# Check logs
vercel logs --follow scrapee-backend

# Should see:
✓ Pulled SQLite database from Redis (1234567 bytes)

# Search again - results still there!
```

## Files Reference

### Created/Updated

1. **backend/mcp.py**
   - Updated `_tool_scrape_url()` with `max_depth=2` default
   - Now crawls 30+ pages automatically
   - Preserves code_blocks from SmartCrawler
   - Syncs to Redis after each save

2. **backend/smart_crawler.py**
   - Uses SmartScraper's code extraction
   - Returns code_blocks in ScrapedDocument
   - Better language detection

3. **backend/storage/sqlite_store.py**
   - Already has Redis support
   - `_pull_from_redis()` on startup
   - `_push_to_redis()` after save
   - Uses `/tmp/scrapee/docs.db` on Vercel

### Documentation

- **VERCEL_DEPLOYMENT.md** - Detailed setup guide
- **VERCEL_SETUP.sh** - Interactive checklist
- **ARCHITECTURE.md** - Complete architecture overview

## Troubleshooting

### "Redis connection failed"

```
1. Check Redis is created in Vercel Storage tab
2. Confirm KV_URL is in env vars
3. Wait 2 minutes (KV needs time to start)
4. Redeploy: git push origin main
5. Check logs again
```

### "No data after redeploy"

```
1. First scrape may not have pushed to Redis
2. Check logs for: "Pushed SQLite database to Redis"
3. If missing, scrape again
4. Wait 10 seconds, redeploy
5. Check logs for: "Pulled SQLite database from Redis"
```

### "Searches returning 0 results"

```
1. Check if pages actually scraped
2. Look for debug logs: "Saving doc: https://..."
3. Make sure code blocks extracted:
   "Code blocks to insert: 7"
4. Search for simpler terms first
5. Check FTS5 indexed properly
```

## Success Indicators

✅ You'll know it's working when:

1. After scraping, logs show: `✓ Pushed SQLite database to Redis`
2. Search returns results across 30+ pages
3. After redeploy, logs show: `✓ Pulled SQLite database from Redis`
4. Searches still work after redeploy
5. New scrapes are merged with existing data

## Next Steps

1. **Setup KV in Vercel** (5 minutes)
2. **Deploy code** (1 minute)
3. **Test scraping** (30 seconds)
4. **Verify persistence** (1 minute)

**Total time: ~10 minutes**

After that, your backend is production-ready! 🎉

---

## Questions?

- Check **ARCHITECTURE.md** for detailed flow
- Check **VERCEL_DEPLOYMENT.md** for troubleshooting
- Review logs with `vercel logs --follow scrapee-backend`
