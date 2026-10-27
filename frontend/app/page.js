'use client';

import { useCallback, useEffect, useState } from 'react';
import BatMark from '@/components/BatMark';
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
      <header className="topbar">
        <div className="brand">
          <BatMark size={30} />
          <span className="brand-name">Scrapee</span>
        </div>
        <div className="endpoint" title="MCP endpoint your editor connects to">
          <span className={`dot ${offline ? 'dot-off' : health ? 'dot-on' : ''}`} aria-hidden="true" />
          <span className="sr-only">{offline ? 'Backend offline' : health ? 'Backend online' : 'Checking backend'}</span>
          <span className="mono endpoint-url">{MCP_URL}</span>
        </div>
      </header>

      <main className="canvas">
        <div className="title-row">
          <h1>Your docs index</h1>
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
