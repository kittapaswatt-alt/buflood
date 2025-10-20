from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import List, Optional

from flask import Flask, redirect, render_template, request, url_for

app = Flask(__name__)


@dataclass
class Report:
    flooded: bool
    level: Optional[float]


reports: List[Report] = []

MIN_REPORTS_FOR_STATUS = 3
LEVEL_SIMILARITY_THRESHOLD = 0.3  # meters


def compute_status() -> dict:
    if len(reports) < MIN_REPORTS_FOR_STATUS:
        return {
            "status": "Monitoring",
            "message": "Waiting for more community reports...",
            "is_flooding": False,
            "level": None,
        }

    flooded_reports = [report for report in reports if report.flooded]
    flood_ratio = len(flooded_reports) / len(reports)

    if flood_ratio < 0.6:
        return {
            "status": "Dry",
            "message": "Most recent reports indicate normal conditions.",
            "is_flooding": False,
            "level": None,
        }

    levels = [report.level for report in flooded_reports if report.level is not None]

    if not levels:
        return {
            "status": "Flooding",
            "message": "Flooding reported. Flood level data pending.",
            "is_flooding": True,
            "level": None,
        }

    avg_level = mean(levels)
    max_deviation = max(abs(level - avg_level) for level in levels)

    if max_deviation > LEVEL_SIMILARITY_THRESHOLD:
        return {
            "status": "Flooding",
            "message": "Flooding reported, but measurements vary. Stay alert.",
            "is_flooding": True,
            "level": None,
        }

    return {
        "status": "Flooding",
        "message": "Community verified flooding in the area.",
        "is_flooding": True,
        "level": round(avg_level, 2),
    }


@app.route("/", methods=["GET"])
def index():
    status = compute_status()
    return render_template(
        "index.html",
        status=status,
        report_count=len(reports),
        MIN_REPORTS_FOR_STATUS=MIN_REPORTS_FOR_STATUS,
    )


@app.route("/report", methods=["POST"])
def report():
    flooded = request.form.get("flooded") == "yes"
    level_raw = request.form.get("level", "").strip()
    level = None

    if level_raw:
        try:
            level = float(level_raw)
            if level < 0:
                raise ValueError("Level must be non-negative")
        except ValueError:
            return redirect(url_for("index", invalid="1"))

    reports.append(Report(flooded=flooded, level=level))
    return redirect(url_for("index", thanks="1"))


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
