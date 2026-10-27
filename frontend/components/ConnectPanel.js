'use client';

import { useState } from 'react';
import { MCP_URL } from '@/lib/api';

const CONFIG = JSON.stringify({ servers: { scrapee: { type: 'http', url: MCP_URL } } }, null, 2);
const VSCODE_INSTALL = `vscode:mcp/install?${encodeURIComponent(JSON.stringify({ name: 'scrapee', type: 'http', url: MCP_URL }))}`;

export default function ConnectPanel() {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(CONFIG);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <section className="panel connect" aria-labelledby="connect-title">
      <h2 id="connect-title" className="panel-title">uplink <span className="panel-hint">// connect your editor</span></h2>
      <p className="panel-sub">
        Add this to <code>.vscode/mcp.json</code>, or run <code>scrapee</code> in your project and it writes it for you.
      </p>
      <pre className="code connect-config">
        <code>{CONFIG}</code>
      </pre>
      <div className="connect-actions">
        <a className="btn btn-secondary" href={VSCODE_INSTALL}>
          Install in VS Code
        </a>
        <button type="button" className="btn btn-ghost" onClick={copy} aria-live="polite">
          {copied ? 'Copied' : 'Copy config'}
        </button>
      </div>
    </section>
  );
}
