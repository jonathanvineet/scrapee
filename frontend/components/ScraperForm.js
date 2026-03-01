'use client';

import { useState } from 'react';
import { FiPlus, FiTrash2 } from 'react-icons/fi';

const MODES = [
  {
    value: 'smart',
    label: 'Smart Crawler',
    description: 'Tries HTTP requests first, upgrades to Selenium for JS-heavy pages.',
  },
  {
    value: 'pipeline',
    label: 'Pipeline Crawler',
    description: 'Threaded concurrent crawl (8 workers). Fastest for large sites.',
  },
  {
    value: 'fast',
    label: 'Selenium Crawler',
    description: 'Full headless browser render on every page. Most accurate, requires Selenium.',
  },
];

export default function ScraperForm({ onSubmit, loading }) {
  const [urls, setUrls] = useState(['']);
  const [mode, setMode] = useState('smart');
  const [maxDepth, setMaxDepth] = useState(1);
  const [format, setFormat] = useState('json');
  const [errors, setErrors] = useState([]);

  const handleUrlChange = (index, value) => {
    const newUrls = [...urls];
    newUrls[index] = value;
    setUrls(newUrls);
  };

  const addUrlField = () => setUrls([...urls, '']);

  const removeUrlField = (index) => setUrls(urls.filter((_, i) => i !== index));

  const validateUrls = () => {
    const newErrors = [];
    urls.forEach((url, index) => {
      if (!url.trim()) newErrors[index] = 'URL is required';
      else if (!url.match(/^https?:\/\/.+/)) newErrors[index] = 'Must start with http:// or https://';
    });
    setErrors(newErrors);
    return newErrors.filter(Boolean).length === 0;
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!validateUrls()) return;
    onSubmit({
      urls: urls.filter(u => u.trim()),
      mode,
      max_depth: maxDepth,
      output_format: format,
    });
  };

  return (
    <div className="form-container">
      <form onSubmit={handleSubmit} className="form">

        <div className="form-section">
          <h2>URLs to Scrape</h2>
          <div className="urls-list">
            {urls.map((url, index) => (
              <div key={index} className="url-input-group">
                <input
                  type="url"
                  value={url}
                  onChange={(e) => handleUrlChange(index, e.target.value)}
                  placeholder="https://example.com"
                  className={`input ${errors[index] ? 'error' : ''}`}
                  disabled={loading}
                />
                {urls.length > 1 && (
                  <button type="button" onClick={() => removeUrlField(index)} className="btn-icon" disabled={loading}>
                    <FiTrash2 />
                  </button>
                )}
              </div>
            ))}
          </div>
          <button type="button" onClick={addUrlField} className="btn btn-secondary" disabled={loading}>
            <FiPlus /> Add URL
          </button>
        </div>

        <div className="form-section">
          <h3>Crawler Mode</h3>
          <div className="mode-cards">
            {MODES.map((m) => (
              <label key={m.value} className={`mode-card ${mode === m.value ? 'active' : ''}`}>
                <input
                  type="radio"
                  value={m.value}
                  checked={mode === m.value}
                  onChange={(e) => setMode(e.target.value)}
                  disabled={loading}
                />
                <div>
                  <strong>{m.label}</strong>
                  <p>{m.description}</p>
                </div>
              </label>
            ))}
          </div>
        </div>

        <div className="form-section">
          <h3>Crawl Depth: <span className="depth-value">{maxDepth}</span></h3>
          <input
            type="range"
            min={0}
            max={3}
            value={maxDepth}
            onChange={(e) => setMaxDepth(Number(e.target.value))}
            className="depth-slider"
            disabled={loading}
          />
          <div className="depth-labels">
            <span>0 (single page)</span>
            <span>1 (+ linked pages)</span>
            <span>2</span>
            <span>3 (deep)</span>
          </div>
        </div>

        <div className="form-section">
          <h3>Output Format</h3>
          <select value={format} onChange={(e) => setFormat(e.target.value)} className="input" disabled={loading}>
            <option value="json">JSON</option>
            <option value="csv">CSV</option>
          </select>
        </div>

        <button type="submit" className="btn btn-primary" disabled={loading}>
          {loading ? '⏳ Scraping…' : '🕷️ Start Scraping'}
        </button>
      </form>
    </div>
  );
}
