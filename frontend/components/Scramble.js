'use client';

import { useEffect, useState } from 'react';

const NOISE = '01010101#$%&@*<>/\\|';

// Text that decodes out of binary noise, left to right.
export default function Scramble({ text, duration = 700, as: Tag = 'span', className }) {
  const [out, setOut] = useState(text);

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setOut(text);
      return undefined;
    }
    let frame;
    const start = performance.now();
    const tick = (now) => {
      const p = Math.min(1, (now - start) / duration);
      const fixed = Math.floor(p * text.length);
      setOut(
        text.slice(0, fixed) +
          [...text.slice(fixed)].map((c) => (c === ' ' ? ' ' : NOISE[(Math.random() * NOISE.length) | 0])).join('')
      );
      if (p < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [text, duration]);

  return (
    <Tag className={className} aria-label={text}>
      <span aria-hidden="true">{out}</span>
    </Tag>
  );
}
