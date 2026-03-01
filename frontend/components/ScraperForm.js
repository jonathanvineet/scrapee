'use client';

import { useState } from 'react';
import LoadingSpinner from './LoadingSpinner';

const MODES = [
  {
    value: 'smart',
    label: 'GHOST_PROTOCOL',
    description: 'Tries lightweight HTTP requests first. If the page requires JavaScript rendering, automatically upgrades to a headless browser. Best balance of speed and compatibility.',
    tags: ['adaptive', 'js-fallback', 'recommended'],
  },
  {
    value: 'pipeline',
    label: 'SWARM_ROUTINE',
    description: 'Spawns 8 concurrent worker threads to crawl multiple pages simultaneously. Ideal for large sites where speed matters more than deep JS rendering.',
    tags: ['threaded', 'concurrent', 'fast'],
  },
  {
    value: 'fast',
    label: 'DEEP_RENDER',
    description: 'Runs every page through a full headless Chrome browser. Guarantees accurate results for heavily JavaScript-driven sites. Slower but most thorough.',
    tags: ['selenium', 'headless-chrome', 'accurate'],
  },
];

export default function ScraperForm({ onSubmit, loading }) {
  const [urls, setUrls] = useState(['']);
  const [mode, setMode] = useState('smart');
  const [maxDepth, setMaxDepth] = useState(1);
  const [format, setFormat] = useState('json');
  const [errors, setErrors] = useState([]);
  const [tooltip, setTooltip] = useState(null); // { mode, x, y }

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
      if (!url.trim()) newErrors[index] = 'ERR_EMPTY_TARGET';
      else if (!url.match(/^https?:\/\/.+/)) newErrors[index] = 'ERR_INVALID_PROTOCOL';
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

  if (loading) {
    return <LoadingSpinner statusText="ESTABLISHING DIRECT UPLINK..." />;
  }

  return (
    <div className="form-container">
      <form onSubmit={handleSubmit} className="form-section">

        <div className="form-section">
          {urls.map((url, index) => (
            <div key={index} style={{ marginBottom: '1rem' }}>
              <div className="input-row">
                <span>TARGET[{index}]:</span>
                <input
                  type="url"
                  value={url}
                  onChange={(e) => handleUrlChange(index, e.target.value)}
                  placeholder="https://ip..."
                  className="input"
                  style={{ borderBottomColor: errors[index] ? 'var(--fg-error)' : 'var(--fg-muted)' }}
                  disabled={loading}
                />
                {urls.length > 1 && (
                  <button type="button" onClick={() => removeUrlField(index)} className="btn-icon">
                    [RM]
                  </button>
                )}
              </div>
              {errors[index] && <div style={{ color: 'var(--fg-error)', fontSize: '0.8rem', marginTop: '0.2rem' }}>{errors[index]}</div>}
            </div>
          ))}
          <button type="button" onClick={addUrlField} className="btn-icon" style={{ alignSelf: 'flex-start', color: 'var(--fg)' }}>
            + APPEND_TARGET
          </button>
        </div>

        <br />

        <div className="form-section">
          <span className="label">OP_MODE:</span>
          <div className="radio-group" style={{ flexDirection: 'column' }}>
            {MODES.map((m) => (
              <div
                key={m.value}
                className="mode-option-wrapper"
                onMouseEnter={(e) => {
                  const rect = e.currentTarget.getBoundingClientRect();
                  setTooltip({ mode: m, x: rect.right + 10, y: rect.top + rect.height / 2 });
                }}
                onMouseLeave={() => setTooltip(null)}
              >
                <label className={`radio-label mode-option${mode === m.value ? ' mode-option--active' : ''}`} onClick={() => setMode(m.value)}>
                  <input
                    type="radio"
                    value={m.value}
                    checked={mode === m.value}
                    onChange={(e) => setMode(e.target.value)}
                  />
                  <span className="mode-option-label">[{m.value === mode ? '*' : ' '}] {m.label}</span>
                </label>
              </div>
            ))}
          </div>

          {tooltip && (
            <div
              className="mode-tooltip"
              style={{
                top: Math.min(tooltip.y, window.innerHeight - 140),
                left: Math.min(tooltip.x, window.innerWidth - 260),
              }}
            >
              <p className="mode-option-desc">{tooltip.mode.description}</p>
              <div className="mode-option-tags">
                {tooltip.mode.tags.map(tag => <span key={tag} className="mode-tag">{tag}</span>)}
              </div>
            </div>
          )}
        </div>

        <br />

        <div className="form-section">
          <div className="input-row">
            <span className="label">DEPTH:</span>
            <input
              type="number"
              min={0}
              max={3}
              value={maxDepth}
              onChange={(e) => setMaxDepth(Number(e.target.value))}
              className="input"
              style={{ width: '50px', textAlign: 'center' }}
            />
          </div>
        </div>

        <br />

        <div className="form-section">
          <div className="input-row">
            <span className="label">FORMAT:</span>
            <select value={format} onChange={(e) => setFormat(e.target.value)} className="input">
              <option value="json">.JSON</option>
              <option value="csv">.CSV</option>
            </select>
          </div>
        </div>

        <br />

        <button type="submit" className="btn">
          EXECUTE <span className="blink">_</span>
        </button>
      </form>
    </div>
  );
}
