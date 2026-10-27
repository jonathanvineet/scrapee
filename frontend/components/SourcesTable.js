'use client';

import { Fragment, useEffect, useState } from 'react';
import { getSourceDocs, removeSource } from '@/lib/api';
import { n, pathOf, plural, since } from '@/lib/format';

const CAP = 8;

function SourcePages({ domain }) {
  const [state, setState] = useState({});

  useEffect(() => {
    let live = true;
    getSourceDocs(domain)
      .then((d) => live && setState({ docs: d.docs }))
      .catch((e) => live && setState({ error: e.message }));
    return () => {
      live = false;
    };
  }, [domain]);

  if (state.error) return <p className="faint source-pages-note">Couldn’t load pages: {state.error}</p>;
  if (!state.docs) {
    return (
      <ul className="page-list" aria-busy="true">
        {[0, 1, 2].map((i) => (
          <li key={i}>
            <span className="skeleton" style={{ width: `${40 + i * 12}%` }} />
          </li>
        ))}
      </ul>
    );
  }
  return (
    <ul className="page-list">
      {state.docs.map((d) => (
        <li key={d.url}>
          <a href={d.url} target="_blank" rel="noreferrer" className="page-title">
            {d.title || pathOf(d.url)}
          </a>
          <span className="page-path mono">{pathOf(d.url)}</span>
          <span className="num page-figure">{n(Math.round((d.chars || 0) / 6))} words</span>
          <span className="num page-figure">{d.code_blocks ? plural(d.code_blocks, 'block') : '—'}</span>
        </li>
      ))}
    </ul>
  );
}

export default function SourcesTable({ data, error, onRetry, onChanged }) {
  const [open, setOpen] = useState(null);
  const [confirming, setConfirming] = useState(null);
  const [busy, setBusy] = useState(null);
  const [notice, setNotice] = useState('');

  const [showAll, setShowAll] = useState(false);

  const sources = data?.sources || [];
  const most = Math.max(1, ...sources.map((s) => s.docs));
  const shown = showAll ? sources : sources.slice(0, CAP);

  async function remove(domain) {
    setBusy(domain);
    try {
      const res = await removeSource(domain);
      setNotice(`Removed ${plural(res.removed, 'page')} from ${domain}.`);
      if (open === domain) setOpen(null);
      onChanged?.();
    } catch (e) {
      setNotice(`Couldn’t remove ${domain}: ${e.message}`);
    } finally {
      setBusy(null);
      setConfirming(null);
    }
  }

  return (
    <section className="panel sources" aria-labelledby="sources-title">
      <div className="panel-head">
        <h2 id="sources-title" className="panel-title">Indexed sites</h2>
        {data && (
          <span className="faint">
            {plural(sources.length, 'site')} · {plural(data.total_docs, 'page')} · {plural(data.total_code_blocks, 'code block')}
          </span>
        )}
      </div>

      {notice && (
        <p className="notice" role="status">
          {notice}{' '}
          <button type="button" className="link" onClick={() => setNotice('')}>
            Dismiss
          </button>
        </p>
      )}

      {error ? (
        <div className="empty">
          <p>Couldn’t load the index: {error}</p>
          <button type="button" className="link" onClick={onRetry}>
            Retry
          </button>
        </div>
      ) : !data ? (
        <table className="table" aria-busy="true">
          <tbody>
            {[0, 1, 2, 3].map((i) => (
              <tr key={i}>
                <td>
                  <span className="skeleton" style={{ width: `${50 + i * 8}%` }} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : sources.length === 0 ? (
        <div className="empty">
          <p>Nothing indexed yet. Crawl a docs site above and your AI client can answer from it.</p>
        </div>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Site</th>
              <th scope="col" className="col-bar">Pages</th>
              <th scope="col" className="num">Code blocks</th>
              <th scope="col" className="num col-when">Crawled</th>
              <th scope="col" className="col-actions">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {shown.map((s) => {
              const isOpen = open === s.domain;
              return (
                <Fragment key={s.domain}>
                  <tr className={isOpen ? 'is-open' : undefined}>
                    <td>
                      <div className="site-cell">
                        <button
                          type="button"
                          className="site-toggle"
                          aria-expanded={isOpen}
                          onClick={() => setOpen(isOpen ? null : s.domain)}
                        >
                          <span className="chev" aria-hidden="true">{isOpen ? '▾' : '▸'}</span>
                          {s.domain}
                        </button>
                        <span className="cell-sub faint">
                          {plural(s.docs, 'page')} · {n(s.code_blocks)} code · {since(s.last_scraped)}
                        </span>
                      </div>
                    </td>
                    <td className="col-bar">
                      <span className="bar-cell">
                        <span className="num bar-n">{n(s.docs)}</span>
                        <span className="bar-track">
                          <span className="bar" style={{ width: `${(s.docs / most) * 100}%` }} />
                        </span>
                      </span>
                    </td>
                    <td className="num">{n(s.code_blocks)}</td>
                    <td className="num col-when faint">{since(s.last_scraped)}</td>
                    <td className="col-actions">
                      {confirming === s.domain ? (
                        <span className="confirm">
                          <button
                            type="button"
                            className="link danger"
                            disabled={busy === s.domain}
                            onClick={() => remove(s.domain)}
                          >
                            {busy === s.domain ? 'Removing…' : `Remove ${plural(s.docs, 'page')}`}
                          </button>
                          <button type="button" className="link" onClick={() => setConfirming(null)}>
                            Keep
                          </button>
                        </span>
                      ) : (
                        <button
                          type="button"
                          className="link quiet"
                          aria-label={`Remove ${s.domain} from the index`}
                          onClick={() => setConfirming(s.domain)}
                        >
                          Remove
                        </button>
                      )}
                    </td>
                  </tr>
                  {isOpen && (
                    <tr className="source-pages">
                      <td colSpan={5}>
                        <SourcePages domain={s.domain} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      )}
      {sources.length > CAP && (
        <div className="panel-foot">
          <button type="button" className="link" onClick={() => setShowAll((v) => !v)}>
            {showAll ? `Show the ${CAP} most recent` : `Show all ${n(sources.length)} sites`}
          </button>
        </div>
      )}
    </section>
  );
}
