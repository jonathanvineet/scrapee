import { JetBrains_Mono, Share_Tech_Mono } from 'next/font/google';
import '@/styles/globals.css';

const mono = JetBrains_Mono({ subsets: ['latin'], variable: '--font-mono', display: 'swap' });
const display = Share_Tech_Mono({ subsets: ['latin'], weight: '400', variable: '--font-display', display: 'swap' });

export const metadata = {
  title: 'SCRAPEE // gotham node',
  description:
    'Paste a URL. Scrapee crawls the whole site, indexes every page and code block, and serves it to your AI coding assistant over MCP.',
};

export const viewport = {
  themeColor: '#050505',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" className={`${mono.variable} ${display.variable}`}>
      <body>{children}</body>
    </html>
  );
}
