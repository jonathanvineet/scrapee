'use client';

import { FiDownload } from 'react-icons/fi';
import JSON5 from 'json5';

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
  };

  return (
    <div className="results-container">
      <div className="results-header">
        <h2>Scraping Results</h2>
        <button onClick={handleDownload} className="btn btn-secondary">
          <FiDownload /> Download
        </button>
      </div>

      <div className="results-info">
        <div className="info-item">
          <span className="label">Status:</span>
          <span className="value">{results.status}</span>
        </div>
        <div className="info-item">
          <span className="label">Mode:</span>
          <span className="value">{results.mode}</span>
        </div>
        <div className="info-item">
          <span className="label">URLs Processed:</span>
          <span className="value">{results.urls_processed}</span>
        </div>
        <div className="info-item">
          <span className="label">Format:</span>
          <span className="value">{results.output_format}</span>
        </div>
      </div>

      {results.data && results.data.length > 0 && (
        <div className="results-data">
          <h3>Extracted Data</h3>
          <pre className="code-block">
            {JSON.stringify(results.data, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
