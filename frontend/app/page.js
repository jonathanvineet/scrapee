'use client';

import { useCallback, useEffect, useState } from 'react';
import BatMark from '@/components/BatMark';
import MatrixRain from '@/components/MatrixRain';
import CrawlPanel from '@/components/CrawlPanel';
import SourcesTable from '@/components/SourcesTable';
import AskPanel from '@/components/AskPanel';
import ConnectPanel from '@/components/ConnectPanel';
import { API_BASE, MCP_URL, getHealth, getSources } from '@/lib/api';
import { plural } from '@/lib/format';

export default function Home() {
  const [health, setHealth] = useState(null); // null = checking, false = offline
  const [sources, setSources] = useState(null);
  const [sourcesError, setSourcesError] = useState('');

  const refresh = useCallback(async () => {
    setSourcesError('');
    try {
      setHealth(await getHealth());
    } catch {
      setHealth(false);
    }
    try {
      setSources(await getSources());
    } catch {
      // A backend that is still starting (or busy crawling) gets one more try.
      await new Promise((r) => setTimeout(r, 1500));
      try {
        setSources(await getSources());
      } catch (e) {
        setSources(null);
        setSourcesError(e.message);
      }
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const offline = health === false;
  const total = sources?.total_docs ?? 0;
  const sites = sources?.sources?.length ?? 0;

  return (
    <div className="shell">
      <MatrixRain />
      <div className="crt" aria-hidden="true" />

      <header className="topbar">
        <div className="brand">
          <BatMark size={34} />
          <span className="brand-name">SCRAPEE</span>
          <span className="brand-node">// gotham node</span>
        </div>
        <div className="endpoint" title="MCP endpoint your editor connects to">
          <span className={`dot ${offline ? 'dot-off' : health ? 'dot-on' : ''}`} aria-hidden="true" />
          <span className="status-word">{offline ? '[OFFLINE]' : health ? '[ONLINE]' : '[....]'}</span>
          <span className="endpoint-url">{MCP_URL}</span>
        </div>
      </header>

      <main className="canvas">
        <div className="hero">
          <div className="signal" aria-hidden="true">
            <BatMark size={220} />
          </div>
          <p className="prompt">
            root@gotham:~$ <span className="typed">scrapee --index</span>
            <span className="cursor" aria-hidden="true">█</span>
          </p>
          <h1 className="glitch" data-text="SCRAPEE">
            SCRAPEE
          </h1>
          <p className="tagline">Any website, served to your AI over MCP.</p>
          <p className="subline">
            {offline ? (
              <>
                The backend at <span className="mono">{API_BASE}</span> isn’t answering. Start it with{' '}
                <code>npm run dev:backend</code>, then{' '}
                <button type="button" className="link" onClick={refresh}>
                  check again
                </button>
                .
              </>
            ) : sources ? (
              total > 0 ? (
                `${plural(total, 'page')} from ${plural(sites, 'site')}, served to your AI client over MCP.`
              ) : (
                'Crawl a docs site and your AI client answers from its real, current pages.'
              )
            ) : (
              'Checking the index…'
            )}
          </p>
        </div>

        <CrawlPanel onIndexed={refresh} suggest={sources && total === 0} />

        <div className="work">
          <SourcesTable data={sources} error={sourcesError} onRetry={refresh} onChanged={refresh} />
          <div className="rail">
            <AskPanel disabled={offline || total === 0} />
            <ConnectPanel />
          </div>
        </div>
      </main>
    </div>
  );
}
