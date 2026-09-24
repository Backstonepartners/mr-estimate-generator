# M&R Estimate Generator

Professional PDF estimate generator for M&R Outdoor Living Solutions.

## Features

- 6 service types (turf, pavers, kitchen, pergola, lighting, general)
- Service-specific pricing and inclusions
- Project image upload
- Automatic PDF generation with M&R branding
- Form validation and error handling
- Mobile responsive design

## Local Development

```bash
pip install -r requirements.txt
python app.py
```

Visit `http://localhost:5000`

## Deployment

### Option 1: Railway (Recommended)

1. Push code to GitHub
2. Connect GitHub to Railway: https://railway.app
3. Railway auto-detects Procfile and deploys
4. Point Cloudflare DNS to Railway domain

### Option 2: Docker

```bash
docker build -t mr-estimate .
docker run -p 5000:5000 mr-estimate
```

### Option 3: Manual VPS

```bash
pip install -r requirements.txt
gunicorn app:app --bind 0.0.0.0:8000
```

Use nginx as reverse proxy with SSL.

## Environment Variables

- `PORT` — Server port (default: 5000)
- `FLASK_ENV` — Set to 'development' for debug mode

## File Structure

- `app.py` — Flask application
- `templates/form.html` — Estimate form UI
- `requirements.txt` — Python dependencies
- `Procfile` — Deployment config
- `runtime.txt` — Python version

## Support

For issues or improvements, contact the development team.
