'use client';

import { useState, useEffect } from 'react';

const CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@#$*&^%';

export default function LoadingSpinner({ statusText = "INITIATING OVERRIDE..." }) {
    const [matrixText, setMatrixText] = useState('');
    const [progress, setProgress] = useState(0);

    useEffect(() => {
        const interval = setInterval(() => {
            let text = '';
            for (let i = 0; i < 200; i++) {
                text += CHARS[Math.floor(Math.random() * CHARS.length)];
            }
            setMatrixText(text);
            setProgress((p) => (p >= 100 ? 100 : p + Math.floor(Math.random() * 5)));
        }, 50);

        return () => clearInterval(interval);
    }, []);

    const barWidth = 30;
    const filled = Math.floor((progress / 100) * barWidth);
    const empty = barWidth - filled;
    const bar = `[${'='.repeat(filled)}${filled > 0 && empty > 0 ? '>' : ''}${' '.repeat(empty > 0 && filled > 0 ? empty - 1 : empty)}]`;

    return (
        <div className="hacker-loader">
            <div className="system-text">{'>'} {statusText}</div>
            <div className="system-text">
                {bar} {progress > 100 ? 100 : progress}%
            </div>
            <div className="matrix-text">{matrixText}</div>
            <div className="system-text blink">_</div>
        </div>
    );
}
