'use client';

import { Fragment, useEffect, useRef, useState } from 'react';
import { askContext, sendFeedback } from '@/lib/api';
import { pathOf } from '@/lib/format';

const STOP = new Set(['a', 'an', 'and', 'are', 'how', 'i', 'in', 'is', 'it', 'of', 'on', 'or', 'the', 'to', 'use', 'what', 'with', 'do', 'does', 'my', 'for']);
const RETRY_MS = 15000;
const MAX_RETRIES = 4;

// get_context returns blocks of "## title\n[SOURCE: url]\n\npassage\n\n```lang\ncode\n```".
function parseContext(context) {
  if (!context || context === 'No context available') return [];
  return context.split('\n\n---\n\n').map((block) => {
    const title = (block.match(/^## (.*)$/m) || [])[1] || '';
    const url = (block.match(/^\[SOURCE: (.*)\]$/m) || [])[1] || '';
    const code = [...block.matchAll(/```(\w*)\n([\s\S]*?)\n```/g)].map((m) => ({ lang: m[1], text: m[2] }));
    const passage = block
      .replace(/^## .*$/m, '')
      .replace(/^\[SOURCE: .*\]$/m, '')
      .replace(/```\w*\n[\s\S]*?\n```/g, '')
      .trim();
    return { title, url, passage, code };
  });
}

function Highlight({ text, terms }) {
  if (!terms.length) return text;
  const re = new RegExp(`(${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'gi');
  return text.split(re).map((part, i) =>
    i % 2 ? <mark key={i}>{part}</mark> : <Fragment key={i}>{part}</Fragment>
  );
}

export default function AskPanel({ disabled }) {
  const [query, setQuery] = useState('');
  const [state, setState] = useState(null); // { query, loading?, data?, error?, retries }
  const [voted, setVoted] = useState(null);
  const timer = useRef(null);

  useEffect(() => () => clearTimeout(timer.current), []);

  async function ask(q, retries = 0) {
    const text = q.trim();
    if (!text) return;
    clearTimeout(timer.current);
    setVoted(null);
    setState((prev) => ({ query: text, loading: true, retries, data: retries ? prev?.data : undefined }));
    try {
      const data = await askContext(text);
      setState({ query: text, data, retries });
      // While Scrapee fetches docs in the background, check back by itself.
      if (data.status === 'learning' && retries < MAX_RETRIES) {
        timer.current = setTimeout(() => ask(text, retries + 1), RETRY_MS);
      }
    } catch (e) {
      setState({ query: text, error: e.message, retries });
    }
  }

  const data = state?.data;
  const blocks = data?.status === 'ready' ? parseContext(data.context) : [];
  const terms = (state?.query || '')
    .toLowerCase()
    .split(/[^a-z0-9_]+/)
    .filter((t) => t.length > 1 && !STOP.has(t));

  function vote(success) {
    setVoted(success ? 'yes' : 'no');
    sendFeedback(state.query, data.sources || [], success);
  }

  return (
    <section className="panel ask" aria-labelledby="ask-title">
      <h2 id="ask-title" className="panel-title">What your AI gets</h2>
      <p className="panel-sub">
        Ask the way your editor would. This is the exact <code>get_context</code> answer an MCP client receives.
      </p>
      <form
        className="ask-form"
        onSubmit={(e) => {
          e.preventDefault();
          ask(query);
        }}
      >
        <label className="sr-only" htmlFor="ask-q">Question</label>
        <input
          id="ask-q"
          className="field"
          type="text"
          placeholder="e.g. useEffect cleanup"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          disabled={disabled}
        />
        <button type="submit" className="btn btn-secondary" disabled={disabled || state?.loading}>
          Ask
        </button>
      </form>

      {state?.loading && !data && (
        <div className="answer" aria-busy="true">
          <span className="skeleton" style={{ width: '70%' }} />
          <span className="skeleton" style={{ width: '90%' }} />
          <span className="skeleton" style={{ width: '55%' }} />
        </div>
      )}

      {state?.error && (
        <p className="answer-note" role="alert">
          Couldn’t ask: {state.error}{' '}
          <button type="button" className="link" onClick={() => ask(state.query)}>
            Retry
          </button>
        </p>
      )}

      {data?.status === 'learning' && (
        <p className="answer-note" role="status">
          Nothing indexed answers that yet, so Scrapee is fetching{' '}
          <span className="mono">{(data.seed || 'likely docs').replace(/^https?:\/\//, '')}</span> in the background.{' '}
          {state.retries < MAX_RETRIES
            ? 'Checking again shortly.'
            : 'Still nothing, so crawl the right docs site above.'}
        </p>
      )}

      {data?.status === 'not_found' && (
        <p className="answer-note" role="status">
          Nothing indexed answers that. Crawl the docs site that covers it above, then ask again.
        </p>
      )}

      {data?.status === 'ready' && (
        <div className="answer">
          <ol className="answer-sources">
            {blocks.map((b, i) => (
              <li key={b.url || i}>
                <a href={b.url} target="_blank" rel="noreferrer">
                  <span className="answer-title">{b.title || pathOf(b.url)}</span>
                  <span className="answer-url mono">{b.url.replace(/^https?:\/\//, '')}</span>
                </a>
                <p className="answer-passage">
                  <Highlight text={b.passage} terms={terms} />
                </p>
                {b.code.map((c, j) => (
                  <pre key={j} className="code">
                    <code>{c.text}</code>
                  </pre>
                ))}
              </li>
            ))}
          </ol>
          <div className="answer-foot">
            {voted ? (
              <span className="faint">Noted. These sources now rank {voted === 'yes' ? 'higher' : 'lower'} for similar questions.</span>
            ) : (
              <>
                <span className="faint">Did this answer it?</span>
                <button type="button" className="link" onClick={() => vote(true)}>
                  Yes
                </button>
                <button type="button" className="link" onClick={() => vote(false)}>
                  No
                </button>
              </>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
