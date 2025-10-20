# BuFlood Watch

A lightweight community reporting dashboard that tracks crowd-sourced flood reports and flips the landing page status once enough residents confirm flooding with consistent measurements.

## Features
- Hero landing page with looping background video and bold weather-style typography.
- Simple two-button report submission (flooded / not flooded) with optional flood depth entry.
- Backend filter that requires:
  - Minimum of 3 total reports.
  - At least 60% of submissions indicating flooding.
  - Consistent flood depth readings (within 0.3 m) before publishing an average flood level.
- Automatic status messaging that transitions between monitoring, dry, and flooding states.

## Getting started

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app run --debug
```

Open http://127.0.0.1:5000 to view the dashboard.

## Project structure
- `app.py`: Flask application with in-memory report aggregation logic.
- `templates/index.html`: Landing page template with the report form and status display.
- `static/style.css`: Styling for the hero section, forms, and layout.
- `requirements.txt`: Python dependencies.

> **Note**: This prototype stores reports in memory for simplicity. Deployments should replace this with persistent storage.
