# Scrapee - Modern Web Scraper

A full-stack web scraping application with a modern Next.js frontend and Flask backend.

## Features

- 🕷️ Multiple scraping modes (fast, detailed)
- 📊 Multiple output formats (JSON, CSV)
- 🎨 Beautiful modern UI built with Next.js
- ⚡ RESTful API with Flask
- 📱 Responsive design
- 🔄 Scraping history tracking

## Project Structure

```
scrapee/
├── backend/          # Flask API server
│   ├── app.py       # Main Flask application
│   ├── requirements.txt
│   └── .env.example
├── frontend/         # Next.js web application
│   ├── app/         # Next.js App Router
│   ├── components/  # React components
│   ├── styles/      # CSS styles
│   ├── public/      # Static files
│   ├── package.json
│   └── next.config.js
└── README.md
```

## Setup

### Prerequisites
- Python 3.8+
- Node.js 18+

### Backend Setup

```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

The API will be available at `http://localhost:5000`

### Frontend Setup

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

The frontend will be available at `http://localhost:3000`

## API Endpoints

### Health Check
```
GET /api/health
```

### Scrape URLs
```
POST /api/scrape
Body: {
  "urls": ["https://example.com"],
  "mode": "fast" | "detailed",
  "output_format": "json" | "csv"
}
```

### Scraping History
```
GET /api/scrape/history
```

### Validate URLs
```
POST /api/scrape/validate-urls
Body: {
  "urls": ["https://example.com"]
}
```

## Development

### Run both backend and frontend
```bash
# Terminal 1: Backend
cd backend
python app.py

# Terminal 2: Frontend
cd frontend
npm run dev
```

## Deployment

### Docker

Build and run with Docker:
```bash
docker-compose up
```

### Vercel (Frontend)
```bash
vercel deploy
```

### Heroku (Backend)
```bash
heroku create your-app-name
git push heroku main
```

## Environment Variables

### Backend (.env)
```
FLASK_ENV=development
FLASK_DEBUG=True
FLASK_PORT=5000
```

### Frontend (.env.local)
```
NEXT_PUBLIC_API_URL=http://localhost:5000
```

## License

MIT
