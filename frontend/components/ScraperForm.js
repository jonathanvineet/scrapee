'use client';

import { useState } from 'react';
import { FiPlus, FiTrash2 } from 'react-icons/fi';

export default function ScraperForm({ onSubmit, loading }) {
  const [urls, setUrls] = useState(['']);
  const [mode, setMode] = useState('fast');
  const [format, setFormat] = useState('json');
  const [errors, setErrors] = useState([]);

  const handleUrlChange = (index, value) => {
    const newUrls = [...urls];
    newUrls[index] = value;
    setUrls(newUrls);
  };

  const addUrlField = () => {
    setUrls([...urls, '']);
  };

  const removeUrlField = (index) => {
    setUrls(urls.filter((_, i) => i !== index));
  };

  const validateUrls = () => {
    const newErrors = [];
    urls.forEach((url, index) => {
      if (url.trim() === '') {
        newErrors[index] = 'URL is required';
      } else if (!url.match(/^https?:\/\/.+/)) {
        newErrors[index] = 'Invalid URL format';
      }
    });
    setErrors(newErrors);
    return newErrors.filter(e => e).length === 0;
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!validateUrls()) return;

    onSubmit({
      urls: urls.filter(u => u.trim()),
      mode,
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
                  <button
                    type="button"
                    onClick={() => removeUrlField(index)}
                    className="btn-icon"
                    disabled={loading}
                  >
                    <FiTrash2 />
                  </button>
                )}
              </div>
            ))}
          </div>
          <button
            type="button"
            onClick={addUrlField}
            className="btn btn-secondary"
            disabled={loading}
          >
            <FiPlus /> Add URL
          </button>
        </div>

        <div className="form-section">
          <h3>Scraping Mode</h3>
          <div className="radio-group">
            <label>
              <input
                type="radio"
                value="fast"
                checked={mode === 'fast'}
                onChange={(e) => setMode(e.target.value)}
                disabled={loading}
              />
              Fast (Extract links)
            </label>
            <label>
              <input
                type="radio"
                value="detailed"
                checked={mode === 'detailed'}
                onChange={(e) => setMode(e.target.value)}
                disabled={loading}
              />
              Detailed (Full content)
            </label>
          </div>
        </div>

        <div className="form-section">
          <h3>Output Format</h3>
          <select
            value={format}
            onChange={(e) => setFormat(e.target.value)}
            className="input"
            disabled={loading}
          >
            <option value="json">JSON</option>
            <option value="csv">CSV</option>
          </select>
        </div>

        <button
          type="submit"
          className="btn btn-primary"
          disabled={loading}
        >
          {loading ? 'Scraping...' : 'Start Scraping'}
        </button>
      </form>
    </div>
  );
}
