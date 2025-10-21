from __future__ import annotations

from collections import Counter, OrderedDict
from pathlib import Path
from typing import Optional
import sqlite3
import os
from flask import Flask, redirect, render_template, request, url_for

app = Flask(__name__)

MIN_REPORTS_FOR_STATUS = 3

_default_db_dir = Path(os.environ.get("DATABASE_DIR", "/tmp/buflood"))
DB_PATH = Path(os.environ.get("DATABASE_PATH", _default_db_dir / "flood_reports.db"))

LEVEL_OPTIONS = OrderedDict(
    [
        (
            "walkable",
            {
                "label": "walkable",
                "status_message": "Flooding reported, but streets remain walkable. Avoid low spots.",
            },
        ),
        (
            "motorcycle",
            {
                "label": "Motorcycle can't pass",
                "status_message": "Flooding confirmed and deep enough to stop motorcycles. Seek alternate routes.",
            },
        ),
        (
            "car",
            {
                "label": "Car can't pass",
                "status_message": "Severe flooding reported. Roads are impassable for cars—avoid the area.",
            },
        ),
    ]
)


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                flooded INTEGER NOT NULL,
                level_category TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


init_db()


def get_reports() -> list[sqlite3.Row]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT flooded, level_category FROM reports").fetchall()


def save_report(flooded: bool, level_category: Optional[str]) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO reports (flooded, level_category) VALUES (?, ?)",
            (1 if flooded else 0, level_category),
        )
        conn.commit()


def compute_status() -> tuple[dict, int]:
    report_rows = get_reports()
    report_count = len(report_rows)

    if report_count < MIN_REPORTS_FOR_STATUS:
        return {
            "status": "Monitoring",
            "message": "Waiting for more community reports...",
            "is_flooding": False,
            "level": None,
            "level_label": None,
        }, report_count

    flooded_reports = [row for row in report_rows if bool(row["flooded"])]
    flood_ratio = len(flooded_reports) / report_count

    if flood_ratio < 0.6:
        return {
            "status": "Dry",
            "message": "Most recent reports indicate normal conditions.",
            "is_flooding": False,
            "level": None,
            "level_label": None,
        }, report_count

    level_categories = [row["level_category"] for row in flooded_reports if row["level_category"]]

    if not level_categories:
        return {
            "status": "Flooding",
            "message": "Flooding reported. Flood level data pending.",
            "is_flooding": True,
            "level": None,
            "level_label": None,
        }, report_count

    level_counts = Counter(level_categories)
    most_common_level, count = level_counts.most_common(1)[0]
    consensus_ratio = count / len(level_categories)

    if consensus_ratio < 0.6:
        return {
            "status": "Flooding",
            "message": "Flooding reported, but measurements vary. Stay alert.",
            "is_flooding": True,
            "level": None,
            "level_label": None,
        }, report_count

    option = LEVEL_OPTIONS.get(most_common_level)

    return {
        "status": "Flooding",
        "message": option["status_message"] if option else "Community verified flooding in the area.",
        "is_flooding": True,
        "level": None,
        "level_label": option["label"] if option else None,
    }, report_count


@app.route("/", methods=["GET"])
def index():
    status, report_count = compute_status()
    return render_template(
        "index.html",
        status=status,
        report_count=report_count,
        MIN_REPORTS_FOR_STATUS=MIN_REPORTS_FOR_STATUS,
        level_options=LEVEL_OPTIONS,
    )


@app.route("/report", methods=["POST"])
def report():
    flooded_value = request.form.get("flooded")
    if flooded_value not in {"yes", "no"}:
        return redirect(url_for("index", invalid="1"))

    flooded = flooded_value == "yes"

    level_category = request.form.get("level_category") or None
    if level_category and level_category not in LEVEL_OPTIONS:
        return redirect(url_for("index", invalid="1"))

    if not flooded:
        level_category = None

    save_report(flooded=flooded, level_category=level_category)
    return redirect(url_for("index", thanks="1"))


if __name__ == "__main__":
    #app.run(debug=True, host="0.0.0.0", port=5000)
    app.run()
