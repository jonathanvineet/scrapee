/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  env: {
    // Local dev: http://localhost:5000
    // Vercel production: https://scrapee-backend.vercel.app
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080',
  },
}

module.exports = nextConfig
