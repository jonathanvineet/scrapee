'use client';

import { forwardRef, Fragment, useEffect, useImperativeHandle, useRef, useState } from 'react';
import BatMark from './BatMark';
import Scramble from './Scramble';
import { MCP_URL, askContext, crawl, getHealth, getSourceDocs, removeSource, sendFeedback } from '@/lib/api';
import { n, normaliseUrl, pathOf, plural } from '@/lib/format';
import { parseContext, queryTerms } from '@/lib/context';

const CONFIG = JSON.stringify({ servers: { scrapee: { type: 'http', url: MCP_URL } } }, null, 2);
const VSCODE_INSTALL = `vscode:mcp/install?${encodeURIComponent(JSON.stringify({ name: 'scrapee', type: 'http', url: MCP_URL }))}`;
const HINTS = ['crawl react.dev/learn', 'ask useEffect cleanup', 'uplink', 'help'];

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

function hostOf(url) {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

function Highlight({ text, terms }) {
  if (!terms.length) return text;
  const re = new RegExp(`(${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'gi');
  return text.split(re).map((part, i) => (i % 2 ? <mark key={i}>{part}</mark> : <Fragment key={i}>{part}</Fragment>));
}

function Bits() {
  const [bits, setBits] = useState('0101101001011010');
  useEffect(() => {
    const t = setInterval(() => setBits(Array.from({ length: 16 }, () => (Math.random() < 0.5 ? '0' : '1')).join('')), 80);
    return () => clearInterval(t);
  }, []);
  return <span className="bits">{bits}</span>;
}

function Elapsed({ since }) {
  const [s, setS] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setS(Math.floor((Date.now() - since) / 1000)), 250);
    return () => clearInterval(t);
  }, [since]);
  return <span className="num">{s}s</span>;
}

function Line({ line }) {
  const style = { animationDelay: `${line.delay || 0}ms` };
  switch (line.kind) {
    case 'echo':
      return <div className="tx tx-echo" style={style}>› {line.text}</div>;
    case 'head':
      return (
        <h2 className="tx tx-head" style={style}>
          <Scramble text={line.text} duration={650} />
        </h2>
      );
    case 'ok':
      return <div className="tx tx-ok" style={style}>{line.text}</div>;
    case 'err':
      return <div className="tx tx-err" style={style}>{line.text}</div>;
    case 'warn':
      return <div className="tx tx-warn" style={style}>{line.text}</div>;
    case 'sys':
      return <div className="tx tx-sys" style={style}>{line.text}</div>;
    case 'row':
      return (
        <div className="tx tx-row" style={{ ...style, gridTemplateColumns: line.cols }}>
          {line.cells.map((cell, i) => (
            <span key={i} className={cell.cls}>
              {cell.href ? (
                <a href={cell.href} target="_blank" rel="noreferrer">
                  {cell.text}
                </a>
              ) : (
                cell.text
              )}
            </span>
          ))}
        </div>
      );
    case 'source':
      return (
        <div className="tx tx-source" style={style}>
          <span className="src-n">{String(line.index).padStart(2, '0')}</span>
          <a href={line.url} target="_blank" rel="noreferrer">
            {line.title}
          </a>
          <span className="src-url">{line.url.replace(/^https?:\/\//, '')}</span>
        </div>
      );
    case 'passage':
      return (
        <p className="tx tx-passage" style={style}>
          <Highlight text={line.text} terms={line.terms} />
        </p>
      );
    case 'code':
      return (
        <pre className="tx tx-code" style={style}>
          <code>{line.text}</code>
        </pre>
      );
    case 'actions':
      return (
        <div className="tx tx-actions" style={style}>
          {line.items.map((a) =>
            a.href ? (
              <a key={a.label} className="glow-link" href={a.href}>
                {a.label}
              </a>
            ) : (
              <button key={a.label} type="button" className="glow-link" onClick={a.onClick}>
                {a.label}
              </button>
            )
          )}
        </div>
      );
    default:
      return <div className="tx" style={style}>{line.text}</div>;
  }
}

const Signal = forwardRef(function Signal({ stats, online, onIndexChanged, onCrawled, children }, ref) {
  const [lines, setLines] = useState([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(null);
  const [history, setHistory] = useState([]);
  const [cursor, setCursor] = useState(-1);
  const idRef = useRef(0);
  const inputRef = useRef(null);
  const txRef = useRef(null);
  const pending = useRef(null); // { type: 'rm', domain } | { type: 'rate', query, sources }
  const lastCrawl = useRef(null);

  function print(batch) {
    const items = (Array.isArray(batch) ? batch : [batch]).map((l, i) => ({
      ...l,
      id: ++idRef.current,
      delay: Math.min(i, 30) * 45,
    }));
    setLines((prev) => [...prev, ...items]);
  }

  // Bring a fresh transmission into view under the signal.
  useEffect(() => {
    if (lines.length && txRef.current) {
      txRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, [lines.length > 0 && lines[0]?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function doCrawl(target, pages = 40) {
    const url = normaliseUrl(target || '');
    try {
      new URL(url);
    } catch {
      print({ kind: 'err', text: 'that isn’t a web address. try: crawl nextjs.org/docs' });
      return;
    }
    const host = hostOf(url);
    setBusy({ label: `infiltrating ${host}, up to ${pages} pages`, started: Date.now() });
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
          cols: 'minmax(0,1.4fr) minmax(0,1fr) 84px 72px',
          cells: [
            { text: p.title || pathOf(p.url), href: p.url },
            { text: pathOf(p.url), cls: 'dim' },
            { text: `${n(p.words)} w`, cls: 'num right' },
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
    setBusy({ label: 'intercepting transmission', started: Date.now() });
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
          cols: 'minmax(0,1.3fr) minmax(0,1fr) 72px',
          cells: [
            { text: d.title || pathOf(d.url), href: d.url },
            { text: pathOf(d.url), cls: 'dim' },
            { text: d.code_blocks ? `${d.code_blocks} code` : '—', cls: 'num right dim' },
          ],
        })),
        {
          kind: 'actions',
          items: [
            { label: `ask ${host} something`, onClick: () => inputRef.current?.focus() },
            { label: `remove ${host}`, onClick: () => run(`rm ${host}`) },
          ],
        },
      ]);
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
    setHistory((h) => [line, ...h.filter((x) => x !== line)].slice(0, 50));
    setCursor(-1);

    const [cmd, ...rest] = line.split(/\s+/);
    const arg = rest.join(' ');
    const lower = cmd.toLowerCase();

    const p = pending.current;
    if (p?.type === 'rm' && ['y', 'yes', 'n', 'no'].includes(lower)) {
      pending.current = null;
      print({ kind: 'echo', text: line });
      if (lower.startsWith('y')) await confirmRm(p.domain);
      else print({ kind: 'sys', text: `kept ${p.domain}` });
      return;
    }
    if (p?.type === 'rate' && ['y', 'yes', 'n', 'no'].includes(lower)) {
      print({ kind: 'echo', text: line });
      rate(lower.startsWith('y'));
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
          ...HELP.map(([c, d]) => ({ kind: 'row', cols: '200px minmax(0,1fr)', cells: [{ text: c, cls: 'hot' }, { text: d, cls: 'dim' }] })),
          { kind: 'sys', text: 'click a star to see its pages. ↑ and ↓ recall what you typed.' },
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
        const domain = hostOf(normaliseUrl(arg || ''));
        if (!arg) {
          print({ kind: 'err', text: 'which site? rm <site>' });
          return;
        }
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

  useImperativeHandle(ref, () => ({ run }));

  function onKeyDown(e) {
    if (e.key === 'ArrowUp' && history.length) {
      e.preventDefault();
      const next = Math.min(cursor + 1, history.length - 1);
      setCursor(next);
      setInput(history[next]);
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      const next = cursor - 1;
      setCursor(next);
      setInput(next >= 0 ? history[next] : '');
    }
  }

  // Live stats sit upright on two fixed arcs; only the binary ring turns.
  const topArc = [online === false ? 'SIGNAL LOST' : 'SIGNAL ONLINE', stats && `${n(stats.total_docs)} PAGES`, stats && `${n(stats.sites)} SITES`]
    .filter(Boolean)
    .join('  ·  ');
  const bottomArc = stats ? `${n(stats.total_code_blocks)} CODE BLOCKS  ·  SERVED OVER MCP` : 'SERVED OVER MCP';

  return (
    <>
      <div className="projector" aria-hidden="true" />
      <div className={`signal ${busy ? 'is-busy' : ''} ${online === false ? 'is-lost' : ''}`}>
        {children}
        <svg className="ring" viewBox="0 0 200 200" aria-hidden="true">
          <defs>
            <path id="arc-top" d="M 9,100 A 91,91 0 0,1 191,100" />
            <path id="arc-bottom" d="M 3,100 A 97,97 0 0,0 197,100" />
            <path id="ring-bits-path" d="M100,100 m-84,0 a84,84 0 1,1 168,0 a84,84 0 1,1 -168,0" />
          </defs>
          <circle className="ring-ticks" cx="100" cy="100" r="88" />
          <g className="ring-spin">
            <text className="ring-bits">
              <textPath href="#ring-bits-path" textLength="526" lengthAdjust="spacing">
                {'01010011 01000011 01010010 01000001 01010000 01000101 01000101 00100000 01001101 01000011 01010000 '}
              </textPath>
            </text>
          </g>
          <text className="ring-text">
            <textPath href="#arc-top" startOffset="50%" textAnchor="middle">
              {topArc}
            </textPath>
          </text>
          <text className="ring-text">
            <textPath href="#arc-bottom" startOffset="50%" textAnchor="middle">
              {bottomArc}
            </textPath>
          </text>
        </svg>

        <div className="disc">
          <span className="disc-bat">
            <BatMark size={260} />
          </span>
          <form
            className="summon"
            onSubmit={(e) => {
              e.preventDefault();
              const v = input;
              setInput('');
              run(v);
            }}
          >
            <label htmlFor="summon-input" className="sr-only">
              Paste a docs URL to crawl, or ask a question
            </label>
            <input
              id="summon-input"
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              autoComplete="off"
              spellCheck={false}
              autoFocus
              disabled={!!busy}
              placeholder={busy ? '' : 'paste a url or ask anything'}
            />
          </form>
          {busy ? (
            <p className="disc-busy" role="status">
              <Bits />
              <span>{busy.label}</span>
              <Elapsed since={busy.started} />
            </p>
          ) : (
            <nav className="hints" aria-label="Try">
              {HINTS.map((h) => (
                <button key={h} type="button" onClick={() => run(h)}>
                  {h}
                </button>
              ))}
            </nav>
          )}
        </div>
      </div>

      <section className="transmission" ref={txRef} role="log" aria-live="polite" aria-label="Transmission">
        {lines.map((l) => (
          <Line key={l.id} line={l} />
        ))}
      </section>
    </>
  );
});

export default Signal;
