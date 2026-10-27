'use client';

import { Fragment } from 'react';
import Scramble from './Scramble';

function Highlight({ text, terms }) {
  if (!terms.length) return text;
  const re = new RegExp(`(${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'gi');
  return text.split(re).map((part, i) => (i % 2 ? <mark key={i}>{part}</mark> : <Fragment key={i}>{part}</Fragment>));
}

function Line({ line }) {
  const style = { animationDelay: `${line.delay || 0}ms` };
  switch (line.kind) {
    case 'echo':
      return <div className="tx tx-echo" style={style}>› {line.text}</div>;
    case 'head':
      return (
        <h2 className="tx tx-head" style={style}>
          <Scramble text={line.text} duration={650} />
        </h2>
      );
    case 'ok':
    case 'err':
    case 'warn':
    case 'sys':
      return <div className={`tx tx-${line.kind}`} style={style}>{line.text}</div>;
    case 'row':
      return (
        <div className="tx tx-row" style={{ ...style, gridTemplateColumns: line.cols }}>
          {line.cells.map((cell, i) => (
            <span key={i} className={cell.cls}>
              {cell.href ? (
                <a href={cell.href} target="_blank" rel="noreferrer">
                  {cell.text}
                </a>
              ) : (
                cell.text
              )}
            </span>
          ))}
        </div>
      );
    case 'source':
      return (
        <div className="tx tx-source" style={style}>
          <span className="src-n">{String(line.index).padStart(2, '0')}</span>
          <a href={line.url} target="_blank" rel="noreferrer">
            {line.title}
          </a>
          <span className="src-url">{line.url.replace(/^https?:\/\//, '')}</span>
        </div>
      );
    case 'passage':
      return (
        <p className="tx tx-passage" style={style}>
          <Highlight text={line.text} terms={line.terms} />
        </p>
      );
    case 'code':
      return (
        <pre className="tx tx-code" style={style}>
          <code>{line.text}</code>
        </pre>
      );
    case 'actions':
      return (
        <div className="tx tx-actions" style={style}>
          {line.items.map((a) =>
            a.href ? (
              <a key={a.label} className="glow-link" href={a.href}>
                {a.label}
              </a>
            ) : (
              <button key={a.label} type="button" className="glow-link" onClick={a.onClick}>
                {a.label}
              </button>
            )
          )}
        </div>
      );
    default:
      return <div className="tx" style={style}>{line.text}</div>;
  }
}

export default function Transmission({ lines, onClose }) {
  if (!lines.length) return null;
  return (
    <section className="transmission" role="log" aria-live="polite" aria-label="Transmission">
      <button type="button" className="tx-close" onClick={onClose} aria-label="Close transmission">
        ×
      </button>
      {lines.map((l) => (
        <Line key={l.id} line={l} />
      ))}
    </section>
  );
}
