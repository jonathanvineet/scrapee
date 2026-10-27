// Thin client for the Scrapee backend (backend/app.py).

export const API_BASE = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080').replace(/\/$/, '');
export const MCP_URL = `${API_BASE}/mcp`;

async function request(method, path, body) {
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Error(`Can't reach the backend at ${API_BASE}`);
  }
  let data = null;
  try {
    data = await response.json();
  } catch {
    // Non-JSON error page (proxy, crash): fall through to the status check.
  }
  if (!response.ok) {
    throw new Error((data && data.error) || `Backend answered HTTP ${response.status}`);
  }
  return data;
}

export const getHealth = () => request('GET', '/api/health');
export const getSources = () => request('GET', '/api/sources');
export const getSourceDocs = (domain) => request('GET', `/api/sources/${encodeURIComponent(domain)}`);
export const removeSource = (domain) => request('DELETE', `/api/sources/${encodeURIComponent(domain)}`);
export const askContext = (query) => request('POST', '/api/context', { query });

export const crawl = (url, maxPages) =>
  request('POST', '/api/scrape', { urls: [url], mode: 'smart', max_pages: maxPages, max_depth: 3 });

// Tells the adaptive ranker whether a get_context answer helped (best-effort).
export function sendFeedback(query, sources, success) {
  return request('POST', '/api/mcp/feedback', { query, sources, success }).catch(() => {});
}
