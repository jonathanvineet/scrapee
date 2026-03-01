'use client';

import { useState } from 'react';
import ScraperForm from '@/components/ScraperForm';
import ResultsDisplay from '@/components/ResultsDisplay';
import History from '@/components/History';
import '@/styles/globals.css';

export default function Home() {
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('scraper');

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
        throw new Error('Scraping failed');
      }

      const data = await response.json();
      setResults(data);
      setActiveTab('results');
    } catch (error) {
      setResults({
        error: error.message || 'An error occurred',
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="container">
      <header className="header">
        <h1>🕷️ Scrapee</h1>
        <p>Modern Web Scraper Interface</p>
      </header>

      <nav className="tabs">
        <button
          className={`tab ${activeTab === 'scraper' ? 'active' : ''}`}
          onClick={() => setActiveTab('scraper')}
        >
          Scraper
        </button>
        <button
          className={`tab ${activeTab === 'results' ? 'active' : ''}`}
          onClick={() => setActiveTab('results')}
        >
          Results
        </button>
        <button
          className={`tab ${activeTab === 'history' ? 'active' : ''}`}
          onClick={() => setActiveTab('history')}
        >
          History
        </button>
      </nav>

      <main className="main">
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
    </div>
  );
}
