'use client';

import { useState, useEffect } from 'react';
import { FiRefreshCw } from 'react-icons/fi';

export default function History() {
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchHistory = async () => {
    setLoading(true);
    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/scrape/history`);
      const data = await response.json();
      setHistory(data.data || []);
    } catch (error) {
      console.error('Failed to fetch history:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchHistory();
  }, []);

  return (
    <div className="history-container">
      <div className="history-header">
        <h2>Scraping History</h2>
        <button onClick={fetchHistory} className="btn btn-secondary" disabled={loading}>
          <FiRefreshCw /> Refresh
        </button>
      </div>

      {loading ? (
        <p>Loading history...</p>
      ) : history.length === 0 ? (
        <div className="empty-state">
          <p>No history yet. Start scraping to see history here.</p>
        </div>
      ) : (
        <div className="history-list">
          {history.map((item, index) => (
            <div key={index} className="history-item">
              <h4>{item.title || 'Scraping Job'}</h4>
              <p>{item.description}</p>
              <small>{new Date(item.timestamp).toLocaleString()}</small>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
