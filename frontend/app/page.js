'use client';

import dynamic from 'next/dynamic';
import { useCallback, useEffect, useRef, useState } from 'react';
import BatMark from '@/components/BatMark';
import Scramble from '@/components/Scramble';
import Transmission from '@/components/Transmission';
import { MCP_URL, getHealth, getSources } from '@/lib/api';
import { n } from '@/lib/format';
import { useCommands } from '@/lib/useCommands';

// WebGL only exists in the browser.
const Swarm = dynamic(() => import('@/components/Swarm'), { ssr: false });

const HINTS = ['crawl react.dev/learn', 'ask useEffect cleanup', 'uplink', 'help'];

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

export default function Home() {
  const [health, setHealth] = useState(null);
  const [sources, setSources] = useState(null);
  const [view, setView] = useState('emblem'); // 'emblem' | 'sites'
  const [ping, setPing] = useState(null);
  const [highlight, setHighlight] = useState([]);
  const [input, setInput] = useState('');
  const [history, setHistory] = useState([]);
  const [cursor, setCursor] = useState(-1);
  const [pulse, setPulse] = useState(0);
  const inputRef = useRef(null);

  const refresh = useCallback(async () => {
    try {
      setHealth(await getHealth());
    } catch {
      setHealth(false);
    }
    try {
      setSources(await getSources());
    } catch {
      setSources(null);
    }
  }, []);

  useEffect(() => {
    refresh();
    // ?view=sites opens straight onto the constellation.
    if (new URLSearchParams(window.location.search).get('view') === 'sites') setView('sites');
  }, [refresh]);

  const { lines, busy, run, clear } = useCommands({
    onIndexChanged: refresh,
    onCrawled: (host) => {
      setView('sites');
      setHighlight([host]);
      setPing(host);
    },
    onAnswered: (domains) => {
      setView('sites');
      setHighlight(domains);
    },
  });

  function submit(value) {
    const v = value.trim();
    if (!v) return;
    setHistory((h) => [v, ...h.filter((x) => x !== v)].slice(0, 50));
    setCursor(-1);
    setInput('');
    run(v);
  }

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
    } else if (e.key === 'Escape') {
      clear();
      setHighlight([]);
    }
  }

  const list = sources?.sources || [];
  const online = health === null ? null : health !== false;
  const mode = busy ? 'storm' : view;

  return (
    <div className="void">
      <Swarm
        sources={list}
        mode={mode}
        highlight={highlight}
        ping={ping}
        shift={lines.length > 0}
        pulse={pulse}
        onPickSite={(domain) => run(`pages ${domain}`)}
      />

      <h1 className="sr-only">Scrapee: crawl any docs site and serve it to your AI over MCP</h1>

      <header className="mark">
        <span className="mark-bat">
          <BatMark size={34} />
        </span>
        <Scramble text="SCRAPEE" className="mark-name" duration={1400} />
      </header>

      <div className={`uplink ${online === false ? 'is-lost' : ''}`} title="MCP endpoint your editor connects to">
        <span className="uplink-dot" aria-hidden="true" />
        <span className="uplink-word">{online === false ? 'signal lost' : online ? 'online' : 'scanning'}</span>
        <span className="uplink-url">{MCP_URL.replace(/^https?:\/\//, '')}</span>
      </div>

      <nav className="views" aria-label="View">
        <button type="button" aria-pressed={view === 'emblem'} onClick={() => setView('emblem')}>
          emblem
        </button>
        <button type="button" aria-pressed={view === 'sites'} onClick={() => setView('sites')}>
          {sources ? `${n(list.length)} sites · ${n(sources.total_docs)} pages` : 'sites'}
        </button>
      </nav>

      <Transmission
        lines={lines}
        onClose={() => {
          clear();
          setHighlight([]);
        }}
      />

      <div className={`command ${busy ? 'is-busy' : ''}`}>
        <form
          className="command-line"
          onSubmit={(e) => {
            e.preventDefault();
            submit(input);
          }}
        >
          <span className="command-prompt" aria-hidden="true">
            ›
          </span>
          <label htmlFor="command-input" className="sr-only">
            Paste a docs URL to crawl, or ask a question
          </label>
          <input
            id="command-input"
            ref={inputRef}
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              setPulse((p) => p + 1);
            }}
            onKeyDown={onKeyDown}
            autoComplete="off"
            spellCheck={false}
            autoFocus
            disabled={!!busy}
            placeholder="paste a docs url, or ask anything"
          />
        </form>
        {busy ? (
          <p className="command-busy" role="status">
            <Bits />
            <span>{busy.label}</span>
            <Elapsed since={busy.started} />
          </p>
        ) : (
          <nav className="hints" aria-label="Try">
            {HINTS.map((h) => (
              <button key={h} type="button" onClick={() => submit(h)}>
                {h}
              </button>
            ))}
          </nav>
        )}
        {online === false && (
          <p className="lost">backend unreachable at {MCP_URL.replace(/\/mcp$/, '')}. start it with npm run dev:backend</p>
        )}
      </div>
    </div>
  );
}
