'use client';

import { n } from '@/lib/format';

const MAX_STARS = 16;

// Which way a star's label points: always away from the signal, so names never
// cross the ring, the threads or each other.
function side(angleDeg) {
  const rad = (angleDeg * Math.PI) / 180;
  const c = Math.cos(rad);
  if (c > 0.42) return 'east';
  if (c < -0.42) return 'west';
  return Math.sin(rad) < 0 ? 'north' : 'south';
}

// Indexed sites as stars around the signal, each tied to it by a thread of light.
export default function Constellation({ sources, ping, onPick }) {
  const stars = (sources || []).slice(0, MAX_STARS);
  if (!stars.length) return null;
  const most = Math.max(...stars.map((s) => s.docs));

  return (
    <div className="constellation" aria-label="Indexed sites">
      {stars.map((s, i) => {
        const angle = (i / stars.length) * 360 - 90 + 360 / stars.length / 2;
        const far = stars.length > 8 && i % 2 === 1;
        const weight = Math.sqrt(s.docs / most);
        const vars = {
          '--a': `${angle}deg`,
          '--orx': far ? 'var(--rx-far)' : 'var(--rx)',
          '--ory': far ? 'var(--ry-far)' : 'var(--ry)',
          '--s': `${5 + weight * 11}px`,
          '--fs': `${12 + weight * 6}px`,
          '--tw': `${(i * 0.83) % 4}s`,
        };
        return (
          <div key={s.domain} className={`star star-${side(angle)} ${ping === s.domain ? 'is-new' : ''}`} style={vars}>
            <span className="thread" aria-hidden="true" />
            <div className="star-pos">
              <button
                type="button"
                className="star-btn"
                onClick={() => onPick(s.domain)}
                title={`${s.domain}: ${n(s.docs)} pages, ${n(s.code_blocks)} code blocks`}
              >
                <span className="star-dot" aria-hidden="true" />
                <span className="star-label">
                  <span className="star-name">{s.domain.replace(/^www\./, '')}</span>
                  <span className="star-n num">{plural(s.docs)}</span>
                </span>
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function plural(count) {
  return `${n(count)} ${count === 1 ? 'page' : 'pages'}`;
}
