'use client';

import { useState } from 'react';

function Section({ title, count, children }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="result-section">
      <button className="result-section-toggle" onClick={() => setOpen(o => !o)}>
        <span>{open ? '▾' : '▸'} {title}</span>
        {count !== undefined && <span className="result-section-count">[{count}]</span>}
      </button>
      {open && <div className="result-section-body">{children}</div>}
    </div>
  );
}

function PageCard({ page, index }) {
  return (
    <div className="page-card">
      <div className="page-card-header">
        <span className="page-card-index">#{String(index + 1).padStart(2, '0')}</span>
        <span className="page-card-title">{page.title || '(no title)'}</span>
      </div>
      <div className="page-card-url">{page.url}</div>

      {page.headings?.length > 0 && (
        <Section title="HEADINGS" count={page.headings.length}>
          <ul className="result-list">
            {page.headings.map((h, i) => <li key={i}>{h}</li>)}
          </ul>
        </Section>
      )}

      {page.paragraphs?.length > 0 && (
        <Section title="CONTENT" count={page.paragraphs.length}>
          <ul className="result-list">
            {page.paragraphs.map((p, i) => <li key={i}>{p}</li>)}
          </ul>
        </Section>
      )}

      {page.links?.length > 0 && (
        <Section title="LINKS" count={page.links.length}>
          <ul className="result-list result-list--links">
            {page.links.map((l, i) => (
              <li key={i}>
                <a href={l.url || l} target="_blank" rel="noopener noreferrer" className="result-link">
                  {l.text || l.url || l}
                </a>
                {l.url && <span className="result-link-url"> — {l.url}</span>}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {page.images?.length > 0 && (
        <Section title="IMAGES" count={page.images.length}>
          <ul className="result-list">
            {page.images.map((img, i) => <li key={i}>{img}</li>)}
          </ul>
        </Section>
      )}
    </div>
  );
}

export default function ResultsDisplay({ results }) {
  if (!results) {
    return <div className="empty-state">$ waiting for pipe... | _</div>;
  }

  if (results.error) {
    return (
      <div className="results-container" style={{ color: 'var(--fg-error)' }}>
        <p>[CRITICAL_FAILURE] — {results.error}</p>
        <p>PROCESS ABORTED.</p>
      </div>
    );
  }

  const pages = results.data || [];

  const handleDownload = () => {
    const blob = new Blob([JSON.stringify(results, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `payload-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="results-container">
      <div className="results-header">
        <span>PAGES_FOUND: {pages.length}</span>
        <button onClick={handleDownload} className="btn-icon">[EXPORT]</button>
      </div>

      {pages.length === 0 ? (
        <div className="empty-state">NO DATA RETURNED — TRY A DIFFERENT MODE OR DEPTH</div>
      ) : (
        <div className="pages-list">
          {pages.map((page, i) => <PageCard key={i} page={page} index={i} />)}
        </div>
      )}
    </div>
  );
}
