'use client';

import { useState } from 'react';
import { FiDownload, FiExternalLink, FiChevronDown, FiChevronUp } from 'react-icons/fi';

function PageResult({ page, mode, index }) {
  const [showLinks, setShowLinks] = useState(false);
  const [showContent, setShowContent] = useState(false);

  return (
    <div className="page-result">
      <div className="page-result-header">
        <span className="page-index">#{index + 1}</span>
        <div className="page-title-group">
          <h3>{page.title || 'Untitled Page'}</h3>
          <a href={page.url} target="_blank" rel="noopener noreferrer" className="page-url">
            {page.url} <FiExternalLink size={12} />
          </a>
        </div>
        <span className="badge">{page.links_count} links</span>
      </div>

      {mode === 'detailed' && page.meta_description && (
        <p className="meta-desc">{page.meta_description}</p>
      )}

      {mode === 'detailed' && page.headings && page.headings.length > 0 && (
        <div className="section">
          <button className="toggle-btn" onClick={() => setShowContent(!showContent)}>
            {showContent ? <FiChevronUp /> : <FiChevronDown />}
            Headings &amp; Content ({page.headings.length})
          </button>
          {showContent && (
            <div className="content-list">
              {page.headings.map((h, i) => (
                <p key={i} className={`heading heading-${h.level}`}>{h.text}</p>
              ))}
              {page.paragraphs && page.paragraphs.map((p, i) => (
                <p key={`p-${i}`} className="para">{p}</p>
              ))}
            </div>
          )}
        </div>
      )}

      {page.links && page.links.length > 0 && (
        <div className="section">
          <button className="toggle-btn" onClick={() => setShowLinks(!showLinks)}>
            {showLinks ? <FiChevronUp /> : <FiChevronDown />}
            Links found ({page.links.length})
          </button>
          {showLinks && (
            <div className="links-list">
              {page.links.map((link, i) => (
                <a key={i} href={link.url} target="_blank" rel="noopener noreferrer" className="link-item">
                  <FiExternalLink size={12} />
                  <span>{link.text || link.url}</span>
                </a>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ResultsDisplay({ results }) {
  if (!results) {
    return (
      <div className="empty-state">
        <p>No results yet. Start scraping to see results here.</p>
      </div>
    );
  }

  if (results.error) {
    return (
      <div className="error-box">
        <h3>Error</h3>
        <p>{results.error}</p>
      </div>
    );
  }

  const handleDownload = () => {
    const dataStr = JSON.stringify(results, null, 2);
    const dataBlob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(dataBlob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `scrapee-results-${Date.now()}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="results-container">
      <div className="results-header">
        <h2>Scraping Results</h2>
        <button onClick={handleDownload} className="btn btn-secondary">
          <FiDownload /> Download JSON
        </button>
      </div>

      <div className="results-info">
        <div className="info-item">
          <span className="label">Status</span>
          <span className="value status-ok">{results.status}</span>
        </div>
        <div className="info-item">
          <span className="label">Mode</span>
          <span className="value">{results.mode}</span>
        </div>
        <div className="info-item">
          <span className="label">URLs Submitted</span>
          <span className="value">{results.urls_processed}</span>
        </div>
        <div className="info-item">
          <span className="label">Pages Scraped</span>
          <span className="value">{results.pages_scraped ?? results.data?.length ?? 0}</span>
        </div>
        <div className="info-item">
          <span className="label">Format</span>
          <span className="value">{results.output_format}</span>
        </div>
      </div>

      {results.data && results.data.length > 0 ? (
        <div className="pages-list">
          {results.data.map((page, i) => (
            <PageResult key={i} page={page} mode={results.mode} index={i} />
          ))}
        </div>
      ) : (
        <div className="empty-state">
          <p>No data was returned. The URL may be blocking scrapers or require authentication.</p>
        </div>
      )}
    </div>
  );
}
