'use client';

import { useState, useEffect } from 'react';
import ScraperForm from '@/components/ScraperForm';
import ResultsDisplay from '@/components/ResultsDisplay';
import History from '@/components/History';
import '@/styles/globals.css';

export default function Home() {
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('scraper');
  const [timestamp, setTimestamp] = useState('');

  useEffect(() => {
    setInterval(() => {
      setTimestamp(new Date().toISOString());
    }, 1000);
  }, []);

  const handleScrape = async (formData) => {
    setLoading(true);
    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/scrape`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(formData),
      });

      if (!response.ok) {
        throw new Error('SCRAPE_ERR_CONN_REFUSED');
      }

      const data = await response.json();
      setResults(data);
      setActiveTab('results');
    } catch (error) {
      setResults({
        error: error.message || 'FATAL_EXCEPTION_DURING_EXECUTION',
      });
    } finally {
      setTimeout(() => setLoading(false), 500);
    }
  };

  return (
    <div className="container">
      <header>
        <h1>root@scrapee:~#</h1>
        <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--fg-muted)' }}>
          <p>sys_ver: 2.4.0_beta</p>
          <p>SYSTIME: {timestamp}</p>
        </div>
      </header>

      <nav className="tabs">
        <button
          className={`tab ${activeTab === 'scraper' ? 'active' : ''}`}
          onClick={() => setActiveTab('scraper')}
        >
          [ EXEC ]
        </button>
        <button
          className={`tab ${activeTab === 'results' ? 'active' : ''}`}
          onClick={() => setActiveTab('results')}
        >
          [ DUMP ]
        </button>
        <button
          className={`tab ${activeTab === 'history' ? 'active' : ''}`}
          onClick={() => setActiveTab('history')}
        >
          [ LOGS ]
        </button>
      </nav>

      <main className="main" style={{ flex: 1, overflowY: 'auto' }}>
        {activeTab === 'scraper' && (
          <ScraperForm onSubmit={handleScrape} loading={loading} />
        )}
        {activeTab === 'results' && (
          <ResultsDisplay results={results} />
        )}
        {activeTab === 'history' && (
          <History />
        )}
      </main>

      <footer style={{ marginTop: 'auto', borderTop: '1px dashed var(--fg-muted)', paddingTop: '1rem', color: 'var(--fg-muted)', fontSize: '0.8rem', display: 'flex', justifyContent: 'space-between' }}>
        <span>CONNECTION: SECURE</span>
        <span>ENCRYPTION: AES-256</span>
      </footer>
    </div>
  );
}
