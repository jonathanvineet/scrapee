'use client';

export default function History() {
  const historyItems = [
    { id: 1, target: 'nexus.corp/data', nodes: 42, time: '2026-03-02 01:12:45', status: 'OK' },
    { id: 2, target: 'shadow.web/relay', nodes: 0, time: '2026-03-02 00:05:11', status: 'ERR_WAF_BLOCK' },
    { id: 3, target: 'sys.conglomerate', nodes: 156, time: '2026-03-01 22:45:30', status: 'OK' },
  ];

  return (
    <div className="history-container">
      <div style={{ marginBottom: '1rem', borderBottom: '1px dashed var(--fg-muted)', paddingBottom: '0.5rem' }}>
        $ tail -n 10 /var/log/scrapee.log
      </div>

      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {historyItems.map((item) => (
          <div key={item.id} className="history-item">
            <div className="history-time">{item.time}</div>
            <div style={{ color: item.status === 'OK' ? '#00cc00' : 'var(--fg-error)', width: '120px' }}>
              [{item.status}]
            </div>
            <div style={{ color: 'var(--fg)', flex: 1 }}>{item.target}</div>
            <div style={{ color: 'var(--fg-muted)', width: '150px', textAlign: 'right' }}>
              NODES_FOUND: {item.nodes}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
