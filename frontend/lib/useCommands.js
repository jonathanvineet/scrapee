'use client';

import { useRef, useState } from 'react';
import { MCP_URL, askContext, crawl, getHealth, getSourceDocs, removeSource, sendFeedback } from './api';
import { n, normaliseUrl, pathOf, plural } from './format';
import { parseContext, queryTerms } from './context';

const CONFIG = JSON.stringify({ servers: { scrapee: { type: 'http', url: MCP_URL } } }, null, 2);
const VSCODE_INSTALL = `vscode:mcp/install?${encodeURIComponent(JSON.stringify({ name: 'scrapee', type: 'http', url: MCP_URL }))}`;

const HELP = [
  ['<url>', 'crawl a docs site into the index'],
  ['<question>', 'see exactly what your AI gets back'],
  ['crawl <url> <pages>', 'crawl with a page budget (default 40, max 250)'],
  ['pages <site>', 'every page indexed for a site'],
  ['rm <site>', 'remove a site'],
  ['uplink', 'MCP config for your editor'],
  ['export', 'download the last crawl as JSON'],
  ['status', 'backend health'],
];

export function hostOf(url) {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

/**
 * The command language shared by every Scrapee surface: a URL crawls, a
 * question asks, plus a few verbs. Returns the transmission lines to render
 * and reports what happened through the callbacks so the scene can react.
 */
export function useCommands({ onIndexChanged, onCrawled, onAnswered, onBusy } = {}) {
  const [lines, setLines] = useState([]);
  const [busy, setBusyState] = useState(null);
  const idRef = useRef(0);
  const pending = useRef(null); // { type: 'rm', domain } | { type: 'rate', query, sources }
  const lastCrawl = useRef(null);

  function setBusy(value) {
    setBusyState(value);
    onBusy?.(value);
  }

  function print(batch) {
    const items = (Array.isArray(batch) ? batch : [batch]).map((l, i) => ({
      ...l,
      id: ++idRef.current,
      delay: Math.min(i, 30) * 45,
    }));
    setLines((prev) => [...prev, ...items]);
  }

  async function doCrawl(target, pages = 40) {
    const url = normaliseUrl(target || '');
    try {
      new URL(url);
    } catch {
      print({ kind: 'err', text: 'that isn’t a web address. try: crawl nextjs.org/docs' });
      return;
    }
    const host = hostOf(url);
    setBusy({ kind: 'crawl', label: `infiltrating ${host}, up to ${pages} pages`, started: Date.now() });
    const t0 = Date.now();
    try {
      const res = await crawl(url, pages);
      lastCrawl.current = { host, res };
      const all = res.data || [];
      const indexed = all.filter((p) => p.status === 'indexed');
      const skipped = all.filter((p) => p.status === 'skipped');
      const failed = all.filter((p) => p.status === 'failed' || p.status === 'error');
      const code = indexed.reduce((s, p) => s + (p.code_blocks || 0), 0);
      const secs = Math.round((Date.now() - t0) / 1000);
      if (!indexed.length) {
        print({ kind: 'err', text: `nothing new from ${host}: ${failed[0]?.error || (skipped.length ? 'every page was already indexed or too thin' : 'no content found')}` });
        return;
      }
      print([
        { kind: 'head', text: `TARGET ACQUIRED · ${host.toUpperCase()}` },
        { kind: 'ok', text: `${plural(indexed.length, 'page')}, ${plural(code, 'code block')}, ${secs}s${skipped.length ? ` · ${skipped.length} skipped` : ''}` },
        ...indexed.slice(0, 40).map((p) => ({
          kind: 'row',
          cols: 'minmax(0,1.4fr) 76px 64px',
          cells: [
            { text: p.title || pathOf(p.url), href: p.url },
            { text: `${n(p.words)} w`, cls: 'num right dim' },
            { text: p.code_blocks ? `${p.code_blocks} code` : '—', cls: 'num right dim' },
          ],
        })),
        ...(indexed.length > 40 ? [{ kind: 'sys', text: `and ${indexed.length - 40} more. type export for all of them.` }] : []),
        { kind: 'sys', text: `your AI can now answer from ${host}. ask it something.` },
      ]);
      onIndexChanged?.();
      onCrawled?.(host);
    } catch (e) {
      print({ kind: 'err', text: `crawl failed: ${e.message}` });
    } finally {
      setBusy(null);
    }
  }

  async function doAsk(query) {
    if (!query) return;
    setBusy({ kind: 'ask', label: 'intercepting transmission', started: Date.now() });
    try {
      const data = await askContext(query);
      if (data.status === 'learning') {
        print({ kind: 'warn', text: `nothing in the index answers that yet. fetching ${data.seed || 'likely docs'} now, ask again in a minute.` });
        return;
      }
      if (data.status !== 'ready') {
        print({ kind: 'warn', text: 'nothing in the index answers that. paste the docs site that covers it.' });
        return;
      }
      const terms = queryTerms(query);
      const blocks = parseContext(data.context);
      print([
        { kind: 'head', text: `INTERCEPTED · ${blocks.length} SOURCES` },
        ...blocks.flatMap((b, i) => [
          { kind: 'source', index: i + 1, title: b.title || pathOf(b.url), url: b.url },
          { kind: 'passage', text: b.passage, terms },
          ...b.code.slice(0, 1).map((c) => ({ kind: 'code', text: c.text })),
        ]),
        {
          kind: 'actions',
          items: [
            { label: 'that answered it', onClick: () => rate(true) },
            { label: 'it missed', onClick: () => rate(false) },
          ],
        },
      ]);
      pending.current = { type: 'rate', query, sources: data.sources || [] };
      onAnswered?.([...new Set((data.sources || []).map(hostOf))]);
    } catch (e) {
      print({ kind: 'err', text: `ask failed: ${e.message}` });
    } finally {
      setBusy(null);
    }
  }

  function rate(yes) {
    const p = pending.current;
    if (!p || p.type !== 'rate') return;
    pending.current = null;
    sendFeedback(p.query, p.sources, yes);
    print({ kind: 'ok', text: `noted. these sources now rank ${yes ? 'higher' : 'lower'} for questions like this.` });
  }

  async function doPages(domain) {
    const host = hostOf(normaliseUrl(domain || ''));
    try {
      const { docs } = await getSourceDocs(host);
      if (!docs.length) {
        print({ kind: 'warn', text: `nothing indexed for ${host}` });
        return;
      }
      print([
        { kind: 'head', text: `${host.toUpperCase()} · ${plural(docs.length, 'PAGE')}` },
        ...docs.map((d) => ({
          kind: 'row',
          cols: 'minmax(0,1.3fr) 64px',
          cells: [
            { text: d.title || pathOf(d.url), href: d.url },
            { text: d.code_blocks ? `${d.code_blocks} code` : '—', cls: 'num right dim' },
          ],
        })),
        { kind: 'actions', items: [{ label: `remove ${host}`, onClick: () => run(`rm ${host}`) }] },
      ]);
      onAnswered?.([host]);
    } catch (e) {
      print({ kind: 'err', text: e.message });
    }
  }

  async function confirmRm(domain) {
    try {
      const res = await removeSource(domain);
      print({ kind: 'ok', text: `${domain} erased · ${plural(res.removed, 'page')}` });
      onIndexChanged?.();
    } catch (e) {
      print({ kind: 'err', text: e.message });
    }
  }

  function doUplink() {
    print([
      { kind: 'head', text: 'UPLINK · .vscode/mcp.json' },
      { kind: 'code', text: CONFIG },
      {
        kind: 'actions',
        items: [
          { label: 'install in VS Code', href: VSCODE_INSTALL },
          {
            label: 'copy config',
            onClick: () =>
              navigator.clipboard
                .writeText(CONFIG)
                .then(() => print({ kind: 'ok', text: 'copied.' }))
                .catch(() => print({ kind: 'err', text: 'the browser blocked the clipboard' })),
          },
        ],
      },
      { kind: 'sys', text: 'or run scrapee in your project and the CLI writes this file for you.' },
    ]);
  }

  function doExport() {
    if (!lastCrawl.current) {
      print({ kind: 'warn', text: 'nothing to export yet. crawl a site first.' });
      return;
    }
    const { host, res } = lastCrawl.current;
    const blob = new Blob([JSON.stringify(res, null, 2)], { type: 'application/json' });
    const href = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = href;
    a.download = `scrapee-${host}-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(href);
    print({ kind: 'ok', text: `downloaded ${a.download}` });
  }

  async function doStatus() {
    try {
      const h = await getHealth();
      print([
        { kind: 'ok', text: `backend ${h.status} · ${n(h.doc_count)} pages · ${n(h.code_blocks)} code blocks` },
        { kind: 'sys', text: `mcp endpoint ${MCP_URL}` },
      ]);
    } catch (e) {
      print({ kind: 'err', text: e.message });
    }
  }

  async function run(raw) {
    const line = raw.trim();
    if (!line || busy) return;
    const [cmd, ...rest] = line.split(/\s+/);
    const arg = rest.join(' ');
    const lower = cmd.toLowerCase();

    const p = pending.current;
    if (p && ['y', 'yes', 'n', 'no'].includes(lower)) {
      print({ kind: 'echo', text: line });
      if (p.type === 'rm') {
        pending.current = null;
        if (lower.startsWith('y')) await confirmRm(p.domain);
        else print({ kind: 'sys', text: `kept ${p.domain}` });
      } else {
        rate(lower.startsWith('y'));
      }
      return;
    }

    // Each command starts a fresh transmission.
    pending.current = null;
    setLines([]);
    print({ kind: 'echo', text: line });

    switch (lower) {
      case 'help':
      case '?':
        print([
          { kind: 'head', text: 'HOW TO SUMMON' },
          ...HELP.map(([c, d]) => ({ kind: 'row', cols: '170px minmax(0,1fr)', cells: [{ text: c, cls: 'hot' }, { text: d, cls: 'dim' }] })),
          { kind: 'sys', text: 'move through the swarm to scatter it. drag to turn it. click a site to see its pages.' },
        ]);
        return;
      case 'crawl':
      case 'load':
      case 'scrape': {
        const [url, pages] = rest;
        await doCrawl(url, Math.max(1, Math.min(Number(pages) || 40, 250)));
        return;
      }
      case 'ask':
        await doAsk(arg);
        return;
      case 'pages':
        await doPages(arg);
        return;
      case 'rm':
      case 'remove': {
        if (!arg) {
          print({ kind: 'err', text: 'which site? rm <site>' });
          return;
        }
        const domain = hostOf(normaliseUrl(arg));
        pending.current = { type: 'rm', domain };
        print([
          { kind: 'warn', text: `erase every page from ${domain}?` },
          {
            kind: 'actions',
            items: [
              { label: `yes, erase ${domain}`, onClick: () => run('y') },
              { label: 'keep it', onClick: () => run('n') },
            ],
          },
        ]);
        return;
      }
      case 'uplink':
      case 'connect':
        doUplink();
        return;
      case 'export':
        doExport();
        return;
      case 'status':
        await doStatus();
        return;
      case 'clear':
      case 'cls':
        setLines([]);
        return;
      default:
        if (rest.length === 0 && /^(https?:\/\/)?[\w-]+(\.[\w-]+)+(\/\S*)?$/i.test(line)) await doCrawl(line);
        else await doAsk(line);
    }
  }

  return { lines, busy, run, clear: () => setLines([]) };
}
