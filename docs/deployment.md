# Deployment (Vercel)

The backend deploys to Vercel as a single Python serverless function.
`backend/app.py` is the entrypoint; every route (REST + `/mcp`) is served from
it.

## The two vercel.json files

Both point at `backend/app.py` with the `@vercel/python` runtime and a 15 MB
lambda cap.

**`vercel.json`** (repo root) — used when the whole repo is the Vercel project:

```json
{
  "version": 2,
  "builds": [
    { "src": "backend/app.py", "use": "@vercel/python", "config": { "maxLambdaSize": "15mb" } }
  ],
  "routes": [ { "src": "/(.*)", "dest": "backend/app.py" } ],
  "env": { "FLASK_ENV": "production", "PYTHONUNBUFFERED": "1", "REDIS_URL": "@redis-url" }
}
```

**`backend/vercel.json`** — used when `backend/` is set as the Vercel project
root directory. Same build, plus `buildCommand: pip install -r requirements.txt`
and an explicit `/api/(.*)` route.

The root `requirements.txt` re-exports `backend/requirements.txt` (plus
PyInstaller for CLI builds) because the Vercel Python runtime resolves
dependencies from the project root.

## Persistence: Vercel KV / Redis

Serverless `/tmp` is wiped between deployments and not shared across instances, so
the SQLite file is mirrored to Redis. `backend/storage/sqlite_store.py` pulls the
DB from Redis on cold start and pushes it after writes.

`VERCEL_SETUP.sh` is the checklist:

1. Vercel dashboard → project → **Storage** → **Create** → **KV**. Vercel adds
   `KV_URL` automatically.
2. Or set `REDIS_URL` (e.g. `redis://default:PASSWORD@HOST:PORT`) under
   **Settings → Environment Variables**. The root `vercel.json` references it as
   the `@redis-url` secret.
3. Deploy (`git push origin main`, or `vercel deploy --prod`).
4. `vercel logs --follow` and look for:
   - `Redis connected for SQLite persistence`
   - `Pulled SQLite database from Redis (... bytes)`
   - `Pushed SQLite database to Redis (... bytes)`
5. Verify: scrape a URL via MCP, redeploy, search again — results should survive.

Without KV/Redis the backend still runs; indexed data just does not persist past
a cold start.

## Environment variables

| Var | Purpose |
|-----|---------|
| `FLASK_ENV=production` | set in both `vercel.json` files |
| `PYTHONUNBUFFERED=1` | stream logs |
| `KV_URL` / `REDIS_URL` | DB persistence (see above) |
| `SCRAPEE_SQLITE_PATH` | override DB path (defaults to `/tmp/scrapee/docs.db` on Vercel) |
| `GITHUB_TOKEN` | raise GitHub API rate limits for repo scraping |

## Pointing clients at the deployment

- MCP over HTTP: `https://<deployment>/mcp` (see `.vscode/mcp.json`, server
  `scrapee`).
- CLI: `export SCRAPEE_BASE_URL="https://<deployment>"`.
- Frontend: `NEXT_PUBLIC_API_URL="https://<deployment>"`.
