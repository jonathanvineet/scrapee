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
  const [mcpStatus, setMcpStatus] = useState('');

  const handleMcpConnect = () => {
    try {
      // Determine backend URL based on environment
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';
      
      // Construct MCP endpoint URL with page URL as query parameter
      const mcpEndpoint = `${apiUrl}/mcp/page?url=${encodeURIComponent(page.url)}`;
      
      // Create MCP configuration for VS Code
      const config = {
        name: `scrapee-${page.url.replace(/[^a-zA-Z0-9]/g, '-').substring(0, 30)}`,
        type: "http",
        url: mcpEndpoint
      };
      
      // Create VS Code MCP install link
      const installLink = `vscode:mcp/install?${encodeURIComponent(JSON.stringify(config))}`;
      
      // Trigger VS Code to install the MCP server
      window.location.href = installLink;
      
      // Show confirmation
      setMcpStatus('✓ Opening VS Code to install MCP server...');
      setTimeout(() => setMcpStatus(''), 3000);
    } catch (error) {
      console.error('MCP connect error:', error);
      setMcpStatus('✗ Failed to connect MCP server');
      setTimeout(() => setMcpStatus(''), 3000);
    }
  };

  return (
    <div className="page-card">
      <div className="page-card-header">
        <span className="page-card-index">#{String(index + 1).padStart(2, '0')}</span>
        <span className="page-card-title">{page.title || '(no title)'}</span>
      </div>
      <div className="page-card-url">{page.url}</div>
      
      <div style={{ marginTop: '10px', marginBottom: '10px' }}>
        <button 
          onClick={handleMcpConnect} 
          className="btn-mcp"
          title="Install this page's MCP server in VS Code"
        >
          [CONNECT MCP TO VSCODE]
        </button>
        {mcpStatus && (
          <span style={{ marginLeft: '10px', color: mcpStatus.includes('✓') ? 'var(--fg-success, #0f0)' : 'var(--fg-error, #f00)' }}>
            {mcpStatus}
          </span>
        )}
      </div>

      {page.headings?.length > 0 && (
        <Section title="HEADINGS" count={page.headings.length}>
          <ul className="result-list">
            {page.headings.map((h, i) => (
              <li key={i}>
                <span className="heading-level">[{h.level || '?'}]</span> {h.text || h}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {page.paragraphs?.length > 0 && (
        <Section title="CONTENT" count={page.paragraphs.length}>
          <ul className="result-list">
            {page.paragraphs.map((p, i) => <li key={i} className="result-paragraph">{p}</li>)}
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
            {page.images.map((img, i) => (
              <li key={i}>
                <span className="image-alt">[{img.alt || 'NO_ALT'}]</span>
                <a href={img.src} target="_blank" rel="noopener noreferrer" className="result-link-url" style={{ marginLeft: '10px' }}>
                  {img.src}
                </a>
              </li>
            ))}
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
