'use client';

import { useEffect, useRef, useState } from 'react';
import { crawl } from '@/lib/api';
import { n, pathOf, plural, normaliseUrl } from '@/lib/format';

const PAGE_LIMITS = [20, 40, 100, 250];
const SUGGESTIONS = ['react.dev/learn', 'fastapi.tiangolo.com', 'docs.expo.dev', 'tailwindcss.com/docs'];
const SHOWN = 6;

function hostOf(url) {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

export default function CrawlPanel({ onIndexed, suggest }) {
  const [url, setUrl] = useState('');
  const [limit, setLimit] = useState(40);
  const [job, setJob] = useState(null); // { url, limit, started, result?, error? }
  const [elapsed, setElapsed] = useState(0);
  const [showAll, setShowAll] = useState(false);
  const inputRef = useRef(null);

  const running = job && !job.result && !job.error;

  useEffect(() => {
    if (!running) return undefined;
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - job.started) / 1000)), 500);
    return () => clearInterval(timer);
  }, [running, job]);

  async function start(target) {
    const value = normaliseUrl(target ?? url);
    if (!value) {
      inputRef.current?.focus();
      return;
    }
    try {
      new URL(value);
    } catch {
      setJob({ url: value, limit, started: Date.now(), error: 'That doesn’t look like a web address.' });
      return;
    }
    const next = { url: value, limit, started: Date.now() };
    setUrl(value);
    setShowAll(false);
    setElapsed(0);
    setJob(next);
    try {
      const result = await crawl(value, limit);
      const seconds = Math.round((Date.now() - next.started) / 1000);
      setJob({ ...next, result, seconds });
      onIndexed?.();
    } catch (err) {
      setJob({ ...next, error: err.message });
    }
  }

  const pages = job?.result?.data || [];
  const indexed = pages.filter((p) => p.status === 'indexed');
  const skipped = pages.filter((p) => p.status === 'skipped');
  const failed = pages.filter((p) => p.status === 'failed' || p.status === 'error');
  const codeCount = indexed.reduce((sum, p) => sum + (p.code_blocks || 0), 0);
  const visible = showAll ? indexed : indexed.slice(0, SHOWN);

  function download() {
    const blob = new Blob([JSON.stringify(job.result, null, 2)], { type: 'application/json' });
    const href = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = href;
    a.download = `scrapee-${hostOf(job.url)}-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(href);
  }

  return (
    <section className="panel crawl" aria-labelledby="crawl-title">
      <h2 id="crawl-title" className="panel-title">add_target <span className="panel-hint">// crawl a docs site</span></h2>
      <form
        className="crawl-form"
        onSubmit={(e) => {
          e.preventDefault();
          start();
        }}
      >
        <label className="sr-only" htmlFor="crawl-url">Site address</label>
        <input
          id="crawl-url"
          ref={inputRef}
          className="field crawl-url"
          type="text"
          inputMode="url"
          autoComplete="url"
          spellCheck={false}
          placeholder="Paste a docs address, like nextjs.org/docs"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          disabled={running}
        />
        <label className="sr-only" htmlFor="crawl-limit">Pages to crawl</label>
        <select
          id="crawl-limit"
          className="field crawl-limit"
          value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}
          disabled={running}
        >
          {PAGE_LIMITS.map((v) => (
            <option key={v} value={v}>
              Up to {v} pages
            </option>
          ))}
        </select>
        <button type="submit" className="btn btn-primary" disabled={running}>
          {running ? 'CRAWLING…' : 'EXECUTE ▸'}
        </button>
      </form>

      {!job && suggest && (
        <p className="crawl-suggest">
          Try{' '}
          {SUGGESTIONS.map((s, i) => (
            <span key={s}>
              <button type="button" className="link" onClick={() => start(s)}>
                {s}
              </button>
              {i < SUGGESTIONS.length - 1 ? ', ' : ''}
            </span>
          ))}
        </p>
      )}

      {running && (
        <div className="crawl-status" role="status" aria-live="polite">
          <span className="bits" aria-hidden="true">
            {Array.from({ length: 12 }, () => (Math.random() < 0.5 ? '0' : '1')).join('')}
          </span>
          <span>
            Crawling <strong>{hostOf(job.url)}</strong>, following links up to {job.limit} pages
          </span>
          <span className="num faint">{elapsed}s</span>
        </div>
      )}

      {job?.error && (
        <div className="crawl-status crawl-error" role="alert">
          <span>
            Couldn’t crawl <strong>{hostOf(job.url)}</strong>: {job.error}
          </span>
          <button type="button" className="link" onClick={() => start(job.url)}>
            Retry
          </button>
        </div>
      )}

      {job?.result && (
        <div className="crawl-result" aria-live="polite">
          <div className="crawl-result-head">
            <p>
              {indexed.length > 0 ? (
                <>
                  Indexed {plural(indexed.length, 'page')} and {plural(codeCount, 'code block')} from{' '}
                  <strong>{hostOf(job.url)}</strong> in {job.seconds}s
                </>
              ) : (
                <>
                  Nothing new from <strong>{hostOf(job.url)}</strong>
                  {failed[0]?.error ? `: ${failed[0].error}` : skipped.length ? ': every page was already indexed or too thin.' : '.'}
                </>
              )}
              {skipped.length > 0 && indexed.length > 0 && (
                <span className="faint"> · {n(skipped.length)} skipped as duplicates or too thin</span>
              )}
            </p>
            <button type="button" className="btn btn-ghost" onClick={download}>
              Download JSON
            </button>
          </div>

          {indexed.length > 0 && (
            <ul className="page-list">
              {visible.map((p) => (
                <li key={p.url}>
                  <a href={p.url} target="_blank" rel="noreferrer" className="page-title">
                    {p.title || pathOf(p.url)}
                  </a>
                  <span className="page-path mono">{pathOf(p.url)}</span>
                  <span className="num page-figure">{n(p.words)} words</span>
                  <span className="num page-figure">{p.code_blocks ? plural(p.code_blocks, 'block') : '—'}</span>
                </li>
              ))}
            </ul>
          )}
          {indexed.length > SHOWN && (
            <button type="button" className="link" onClick={() => setShowAll((v) => !v)}>
              {showAll ? 'Show fewer' : `Show all ${n(indexed.length)} pages`}
            </button>
          )}
        </div>
      )}
    </section>
  );
}
