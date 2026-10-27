import { Schibsted_Grotesk, JetBrains_Mono } from 'next/font/google';
import '@/styles/globals.css';

const sans = Schibsted_Grotesk({ subsets: ['latin'], variable: '--font-sans', display: 'swap' });
const mono = JetBrains_Mono({ subsets: ['latin'], variable: '--font-mono', display: 'swap' });

export const metadata = {
  title: 'Scrapee · your docs index',
  description:
    'Paste a URL. Scrapee crawls the whole site, indexes every page and code block, and serves it to your AI coding assistant over MCP.',
};

export const viewport = {
  themeColor: '#0c0d0f',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
