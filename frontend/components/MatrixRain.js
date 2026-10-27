'use client';

import { useEffect, useRef } from 'react';

// Falling binary in Bat-signal yellow, drawn behind the whole app.
const GLYPHS = '0101010110';
const CELL = 18;
const FRAME_MS = 55;

export default function MatrixRain() {
  const ref = useRef(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas.getContext('2d');
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let width = 0;
    let height = 0;
    let drops = [];
    let raf = 0;
    let last = 0;

    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.font = `600 ${CELL - 4}px "JetBrains Mono", monospace`;
      const cols = Math.ceil(width / CELL);
      drops = Array.from({ length: cols }, () => Math.random() * -(height / CELL));
      ctx.fillStyle = '#050505';
      ctx.fillRect(0, 0, width, height);
    }

    function step() {
      // Translucent black over the last frame leaves each column a fading tail.
      ctx.fillStyle = 'rgba(5, 5, 5, 0.14)';
      ctx.fillRect(0, 0, width, height);
      for (let i = 0; i < drops.length; i++) {
        const y = drops[i] * CELL;
        if (y > 0) {
          const glyph = GLYPHS[(Math.random() * GLYPHS.length) | 0];
          ctx.fillStyle = '#fff4b0';
          ctx.fillText(glyph, i * CELL, y);
          ctx.fillStyle = 'rgba(255, 213, 0, 0.55)';
          ctx.fillText(GLYPHS[(Math.random() * GLYPHS.length) | 0], i * CELL, y - CELL);
        }
        drops[i] += 1;
        if (y > height && Math.random() > 0.975) drops[i] = Math.random() * -20;
      }
    }

    function loop(t) {
      raf = requestAnimationFrame(loop);
      if (t - last < FRAME_MS) return;
      last = t;
      step();
    }

    function onVisibility() {
      cancelAnimationFrame(raf);
      if (!document.hidden && !reduce) raf = requestAnimationFrame(loop);
    }

    resize();
    if (reduce) {
      // One still frame: the rain, frozen.
      for (let k = 0; k < 40; k++) step();
    } else {
      raf = requestAnimationFrame(loop);
    }
    window.addEventListener('resize', resize);
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, []);

  return <canvas ref={ref} className="matrix" aria-hidden="true" />;
}
