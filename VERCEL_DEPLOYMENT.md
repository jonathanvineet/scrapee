# Vercel Deployment with Persistent Database

## What's Currently Set Up

Your backend already has **dual storage**:
- **Local**: SQLite in `/tmp/scrapee/docs.db` (ephemeral on Vercel)
- **Remote**: Redis with automatic sync (persistent)

## How It Works

```
Frontend scrapes URL
    ↓
Backend stores in /tmp SQLite
    ↓
Data automatically pushed to Redis
    ↓
On next request, data pulled from Redis
    ↓
Searches work across ALL previously scraped pages
```

## Setup Steps for Vercel

### Option 1: Use Vercel KV (Recommended - Built in)

1. **Go to Vercel Dashboard**
   - Select your project `scrapee-backend`
   - Go to **Storage** tab
   - Click **Create Database**
   - Select **KV** (Redis)
   - Follow prompts

2. **Vercel auto-adds environment variables**
   - `KV_URL` will be automatically set
   - Backend detects it automatically

3. **Deploy**
   ```bash
   git push origin main
   ```

### Option 2: External Redis (e.g., Redis Labs)

1. **Get your Redis URL**
   - From Redis Labs, AWS, or other provider
   - Format: `redis://default:password@host:port`

2. **Add to Vercel**
   - Go to **Settings** → **Environment Variables**
   - Add: `REDIS_URL` = your redis URL
   - Redeploy

3. **Deploy**
   ```bash
   git push origin main
   ```

## Verification

After deployment, check the logs:

```bash
vercel logs --follow
```

Look for:
```
✓ Redis connected for SQLite persistence
✓ Pulled SQLite database from Redis
✓ Pushed SQLite database to Redis
```

## How Persistence Works

1. **User scrapes `https://docs.expo.dev/`**
   - 30 pages discovered & crawled
   - Stored in `/tmp/scrapee/docs.db`
   - **Automatically pushed to Redis**

2. **User connects VSCode next time**
   - Database pulled from Redis
   - All 30 pages still available
   - Searches work across them

3. **Adding more URLs**
   - New pages scraped
   - Added to SQLite
   - Synced to Redis
   - Persist forever

## Data Flow

```
Vercel Serverless
├─ /tmp/scrapee/docs.db (ephemeral, resets)
│   ├─ Receives all queries
│   ├─ Stores new data
│   └─ Syncs to Redis
│
Redis (Persistent)
└─ Stores full database
   ├─ Survives deployments
   ├─ Persists across requests
   └─ Accessible to all instances
```

## Environment Variables Needed

```env
# For Vercel KV (auto-added)
KV_URL=redis://...

# Or for external Redis
REDIS_URL=redis://default:password@host:port

# Optional
SCRAPEE_SQLITE_PATH=/tmp/scrapee/docs.db
FLASK_ENV=production
```

## Testing

After deployment, test via VSCode:

1. Call `scrape_url` with `https://docs.expo.dev/`
2. Wait for all pages to be stored
3. Redeploy or wait a few seconds
4. Call `search_and_get` with query
5. Should return results from all stored pages

✅ This means your scraped data persists forever on Vercel!
