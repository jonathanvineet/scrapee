export const metadata = {
  title: 'Scrapee - Web Scraper',
  description: 'Modern web scraper interface',
}

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        {children}
      </body>
    </html>
  )
}
