'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import BatMark from '@/components/BatMark';
import Constellation from '@/components/Constellation';
import MatrixRain from '@/components/MatrixRain';
import Scramble from '@/components/Scramble';
import Signal from '@/components/Signal';
import { MCP_URL, getHealth, getSources } from '@/lib/api';
import { n } from '@/lib/format';

export default function Home() {
  const [health, setHealth] = useState(null); // null = checking, false = offline
  const [sources, setSources] = useState(null);
  const [ping, setPing] = useState(null);
  const signal = useRef(null);

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
  }, [refresh]);

  // The rain is lit by a spotlight that follows the pointer.
  useEffect(() => {
    const move = (e) => {
      document.documentElement.style.setProperty('--mx', `${e.clientX}px`);
      document.documentElement.style.setProperty('--my', `${e.clientY}px`);
    };
    window.addEventListener('pointermove', move);
    return () => window.removeEventListener('pointermove', move);
  }, []);

  const list = sources?.sources || [];
  const online = health === null ? null : health !== false;
  const stats = sources ? { ...sources, sites: list.length } : null;
  const pick = (domain) => signal.current?.run(`pages ${domain}`);

  return (
    <div className="sky">
      <MatrixRain />
      <div className="crt" aria-hidden="true" />

      <header className="mark">
        <span className="mark-bat">
          <BatMark size={30} />
        </span>
        <Scramble text="SCRAPEE" className="mark-name" duration={1400} />
      </header>
      <p className={`uplink ${online === false ? 'is-lost' : ''}`} title="MCP endpoint your editor connects to">
        <span className="uplink-dot" aria-hidden="true" />
        <span className="uplink-word">{online === false ? 'signal lost' : online ? 'online' : 'scanning'}</span>
        <span className="uplink-url">{MCP_URL.replace(/^https?:\/\//, '')}</span>
      </p>

      <main className="stage">
        <h1 className="sr-only">Scrapee: crawl any docs site and serve it to your AI over MCP</h1>
        <Signal ref={signal} stats={stats} online={online} onIndexChanged={refresh} onCrawled={setPing}>
          <Constellation sources={list} ping={ping} onPick={pick} />
        </Signal>

        {list.length > 0 && (
          <p className="star-list" aria-label="Indexed sites">
            {list.map((s) => (
              <button key={s.domain} type="button" className="glow-link" onClick={() => pick(s.domain)}>
                {s.domain} <span className="num">{n(s.docs)}</span>
              </button>
            ))}
          </p>
        )}
        {online === false && (
          <p className="lost">
            the backend at {MCP_URL.replace(/\/mcp$/, '')} isn’t answering. start it with npm run dev:backend
          </p>
        )}
      </main>
    </div>
  );
}
