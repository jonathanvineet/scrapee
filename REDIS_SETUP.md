# Scrapee MCP Server - Redis Setup Guide

## 🎯 Why Redis?

Your MCP server runs on **Vercel serverless functions**, which are:
- **Stateless**: Each request may run on a different instance
- **Ephemeral**: Memory is cleared between cold starts
- **Short-lived**: Functions shut down after idle time

**Redis solves this** by providing persistent storage that survives across all requests and deployments.

---

## 🚀 Quick Setup (5 minutes)

### Step 1: Create Free Upstash Redis

1. Go to [console.upstash.com](https://console.upstash.com/)
2. Sign up (free tier includes 10,000 requests/day)
3. Click **"Create Database"**
4. Choose:
   - **Name**: scrapee-mcp
   - **Type**: Regional
   - **Region**: Choose closest to your Vercel region (e.g., `us-east-1`)
5. Click **Create**

### Step 2: Get Redis URL

On the database dashboard, copy the **"REST URL"** or **"Redis URL"**:

```
redis://default:AbCdEf123...@us1-example-12345.upstash.io:6379
```

### Step 3: Add to Environment

**Local Development:**
```bash
cp .env.example .env
```

Then edit `.env` and add:
```env
REDIS_URL=redis://default:your-password@your-endpoint.upstash.io:6379
```

**Vercel Deployment:**
1. Go to your project → Settings → Environment Variables
2. Add:
   - **Key**: `REDIS_URL`
   - **Value**: `redis://default:...`
3. Click Save
4. Redeploy your app

### Step 4: Test It

```bash
# Local test
python backend/app.py

# Should see in console:
# Preloading default documentation...
# ✓ Already loaded: https://docs.hedera.com/...
```

---

## 🧪 Verify It Works

### Test MCP tools with Redis:

```bash
# Scrape a page
curl -X POST https://scrapee-backend.vercel.app/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "scrape_url",
      "arguments": {"url": "https://docs.hedera.com/hedera/getting-started"}
    }
  }'

# List all docs
curl -X POST https://scrapee-backend.vercel.app/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {"name": "list_docs", "arguments": {}}
  }'

# Search docs
curl -X POST https://scrapee-backend.vercel.app/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "search_docs",
      "arguments": {"query": "create fungible token Hedera"}
    }
  }'
```

---

## 📊 What Gets Stored in Redis

| Key Pattern | Value | Purpose |
|-------------|-------|---------|
| `page:<url>` | Text content | Full page content |
| `meta:<url>` | JSON metadata | Title, headings, links |
| `doc_index` | Set of URLs | All indexed pages |

**Example Redis keys:**
```
page:https://docs.hedera.com/hedera/getting-started
meta:https://docs.hedera.com/hedera/getting-started
doc_index
```

---

## 🔄 Fallback Behavior

The MCP server gracefully degrades:

1. **Redis available** → Persistent storage ✅
2. **Redis unavailable** → In-memory storage (loses data on cold start) ⚠️

Check Redis status in health endpoint:
```bash
curl https://scrapee-backend.vercel.app/api/health
```

---

## 💰 Pricing (Upstash Redis)

| Tier | Price | Requests/Day | Storage |
|------|-------|--------------|---------|
| Free | $0 | 10,000 | 256 MB |
| Pay-as-you-go | ~$0.20/day | Unlimited | Unlimited |

For a typical MCP server: **Free tier is enough** (stores ~500 documentation pages).

---

## 🛠️ Troubleshooting

### Error: "Connection timeout"
- Check your `REDIS_URL` is correct
- Verify your IP isn't blocked (Upstash allows all IPs by default)
- Try the REST API endpoint instead

### Error: "Authentication failed"
- Password is wrong in your `REDIS_URL`
- Regenerate password in Upstash console

### Data not persisting
- Check environment variable is set: `echo $REDIS_URL`
- Restart server after adding Redis
- Verify in Upstash console → CLI:
  ```
  KEYS *
  GET page:https://docs.hedera.com/hedera/getting-started
  ```

---

## 🎯 Next Steps

Your MCP server is now production-ready with:
- ✅ Persistent storage (Redis)
- ✅ URL normalization
- ✅ Auto-scraping tool
- ✅ Pre-loaded docs
- ✅ Memory fallback

**Try it in VS Code:**
1. Refresh MCP tools
2. Ask: "How do I create a Hedera token?"
3. The agent will now use `search_docs` and `get_doc` automatically!

---

## 📚 Architecture

```
User Question
     ↓
VS Code / Cursor
     ↓
MCP Client (scrapee)
     ↓
[scrape_url] → SmartCrawler → Parse HTML → save_page()
     ↓
Redis (Upstash)
     ↓
[search_docs] → TF-IDF Search → get_page()
     ↓
Answer with Context
```

---

Need help? Check [Upstash docs](https://docs.upstash.com/redis) or open an issue.
