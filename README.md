# BuFlood Watch

A lightweight community reporting dashboard that tracks crowd-sourced flood reports and flips the landing page status once enough residents confirm flooding with similar impact reports.

## Features
- Hero landing page with looping background video and bold weather-style typography.
- Guided report submission with a flooding toggle and three descriptive impact options (still walkable, motorcycle can't pass, car can't pass).
- Backend filter that requires:
  - Minimum of 3 total reports.
  - At least 60% of submissions indicating flooding.
  - Agreement on impact category before displaying a consensus.
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
- `app.py`: Flask application with SQLite-backed report aggregation logic.
- `templates/index.html`: Landing page template with the report form and status display.
- `static/style.css`: Styling for the hero section, forms, and layout.
- `requirements.txt`: Python dependencies.
- `data/`: SQLite database location for captured reports (created on first run).

The included SQLite database (`data/flood_reports.db`) is created automatically the first time the app runs.
