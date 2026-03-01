'use client';

import { useState } from 'react';

// Generates an interactive JSON-like collapsible tree view for terminal UI
function TreeViewer({ data }) {
  const renderTree = (item, keyPref = '', indent = 0) => {
    if (item === null || item === undefined) return null;

    if (Array.isArray(item)) {
      if (item.length === 0) return <span className="tree-string">[]</span>;
      return (
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          {item.map((val, idx) => (
            <div key={`${keyPref}-${idx}`} style={{ display: 'flex' }}>
               <span className="tree-indent">{'  '.repeat(indent)}</span>
               <span className="tree-key">[{idx}]: </span>
               {typeof val === 'object' ? renderTree(val, `${keyPref}-${idx}`, indent + 1) : renderValue(val)}
            </div>
          ))}
        </div>
      );
    } else if (typeof item === 'object') {
      return (
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          {Object.entries(item).map(([k, v]) => (
            <div key={`${keyPref}-${k}`}>
               <div style={{ display: 'flex' }}>
                 <span className="tree-indent">{'  '.repeat(indent)}</span>
                 <span className="tree-key">"{k}": </span>
                 {typeof v === 'object' && v !== null ? (
                   <span>{Array.isArray(v) ? '[...]' : '{...}'}</span>
                 ) : (
                   renderValue(v)
                 )}
               </div>
               {typeof v === 'object' && v !== null && (
                 renderTree(v, `${keyPref}-${k}`, indent + 1)
               )}
            </div>
          ))}
        </div>
      );
    }
  };

  const renderValue = (val) => {
    if (typeof val === 'string') {
      if (val.startsWith('http')) {
        return <a href={val} target="_blank" rel="noopener noreferrer" className="tree-link">"{val}"</a>;
      }
      return <span className="tree-string">"{val}"</span>;
    }
    if (typeof val === 'number') return <span className="tree-number">{val}</span>;
    if (typeof val === 'boolean') return <span className="tree-boolean">{val ? 'true' : 'false'}</span>;
    return <span className="tree-string">"{String(val)}"</span>;
  };

  return (
    <div style={{ padding: '10px', background: 'rgba(0,255,0,0.05)', border: '1px solid var(--fg-muted)', overflowX: 'auto' }}>
       {renderTree(data, 'root')}
    </div>
  );
}

export default function ResultsDisplay({ results }) {
  if (!results) {
    return (
      <div className="empty-state">
         $ waiting for pipe... | _
      </div>
    );
  }

  if (results.error) {
    return (
      <div className="results-container" style={{ color: 'var(--fg-error)' }}>
        <p>[CRITICAL_FAILURE] - {results.error}</p>
        <p>PROCESS ABORTED.</p>
      </div>
    );
  }

  const handleDownload = () => {
    const dataStr = JSON.stringify(results, null, 2);
    const dataBlob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(dataBlob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `payload-${Date.now()}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="results-container">
      <div style={{ marginBottom: '1rem', display: 'flex', justifyContent: 'space-between', borderBottom: '1px dashed var(--fg-muted)', paddingBottom: '0.5rem' }}>
         <span>$ cat output.json</span>
         <button onClick={handleDownload} className="btn-icon">
            [ DOWNLOAD_FILE ]
         </button>
      </div>

      <TreeViewer data={results} />
    </div>
  );
}
