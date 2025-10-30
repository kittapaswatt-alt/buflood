from __future__ import annotations

from collections import Counter, OrderedDict
from contextlib import contextmanager
import os
import socket
from typing import Optional
import threading
import time

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from flask import Flask, redirect, render_template, request, url_for
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

last_reset_time = time.time()
new_data_since_last_reset = False
_lock = threading.Lock()

MIN_REPORTS_FOR_STATUS = 3

USER = os.getenv("DB_USER", "postgres")
PASSWORD = os.getenv("DB_PASSWORD", ".Y-r+29YyHAc25*")
HOST = os.getenv("DB_HOST", "db.hmmnvgilhcmofciknllv.supabase.co")
PORT = int(os.getenv("DB_PORT", "5432"))
DBNAME = os.getenv("DB_NAME", "postgres")
DATABASE_URL = "postgresql://postgres:.Y-r+29YyHAc25*@db.hmmnvgilhcmofciknllv.supabase.co:5432/postgres"

_db_pool: Optional[ConnectionPool] = None
_db_pool_lock = threading.Lock()

LINE_CHANNEL_SECRET = "d75e574d2c33a695d809b1df16553ad3"
LINE_CHANNEL_ACCESS_TOKEN = "As4hEcmScsiZMrTmIMreUQ9EHm3MZUTVHhMYjr8jYBZwQ5AgI40J42t9c+r+JigZLmfpAILZ3KUpq0xwp8ULAtSX7MdmfmcaG0inOUBgq8cPPlekYWuUOBscDb2fbOpgj6JRgf57amWKWKngeKBmrQdB04t89/1O/w1cDnyilFU="

line_bot_api: Optional[LineBotApi]
webhook_handler: Optional[WebhookHandler]

if LINE_CHANNEL_SECRET and LINE_CHANNEL_ACCESS_TOKEN:
    line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
    webhook_handler = WebhookHandler(LINE_CHANNEL_SECRET)
else:
    line_bot_api = None
    webhook_handler = None


def _resolve_ipv4(host: str, port: int) -> Optional[str]:
    try:
        candidates = socket.getaddrinfo(
            host, port, family=socket.AF_INET, type=socket.SOCK_STREAM
        )
    except socket.gaierror:
        return None
    if not candidates:
        return None
    return candidates[0][4][0]


def _build_conninfo() -> str:
    if DATABASE_URL:
        return DATABASE_URL

    hostaddr = os.getenv("DB_HOSTADDR")
    if hostaddr is None and os.getenv("DB_FORCE_IPV4", "1") == "1":
        hostaddr = _resolve_ipv4(HOST, PORT)

    conn_params: dict[str, object] = {
        "user": USER,
        "password": PASSWORD,
        "host": HOST,
        "port": PORT,
        "dbname": DBNAME,
        "sslmode": os.getenv("DB_SSLMODE", "require"),
    }
    if hostaddr:
        conn_params["hostaddr"] = hostaddr

    return psycopg.conninfo.make_conninfo(**conn_params)


def _ensure_db_pool() -> ConnectionPool:
    global _db_pool

    if _db_pool is None:
        with _db_pool_lock:
            if _db_pool is None:
                conninfo = _build_conninfo()
                _db_pool = ConnectionPool(
                    conninfo,
                    min_size=0,
                    max_size=int(os.getenv("DB_POOL_MAX_SIZE", "5")),
                    timeout=float(os.getenv("DB_POOL_TIMEOUT", "10")),
                    kwargs={"autocommit": True},
                    open=False,
                )
    return _db_pool


@contextmanager
def db_cursor():
    pool = _ensure_db_pool()
    timeout = float(os.getenv("DB_CONNECTION_TIMEOUT", "10"))
    with pool.connection(timeout=timeout) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            yield cur

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
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS reports (
                    id SERIAL PRIMARY KEY,
                    flooded BOOLEAN NOT NULL,
                    level_category TEXT,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        app.logger.info("Success: Supabase database synced")
    except psycopg.OperationalError as exc:
        app.logger.error("Database setup failed: %s", exc)
    except Exception:
        app.logger.exception("Unexpected error while initialising the database")


init_db()

def _reset_db_keep_last_5() -> None:
    """
    Delete everything except the 5 most recent rows by created_at.
    """
    with db_cursor() as cur:
        cur.execute(
            """
            DELETE FROM reports
            WHERE id NOT IN (
                SELECT id FROM reports
                ORDER BY created_at DESC, id DESC
                LIMIT 5
            )
            """
        )

def get_reports() -> list[dict[str, Optional[str]]]:
    try:
        with _lock:
            with db_cursor() as cur:
                cur.execute("SELECT flooded, level_category FROM reports")
                rows = cur.fetchall()
    except psycopg.OperationalError as exc:
        app.logger.error("Unable to load reports: %s", exc)
        return []

    return [
        {"flooded": row["flooded"], "level_category": row["level_category"]}
        for row in rows
    ]


def save_report(flooded: bool, level_category: Optional[str]) -> None:
    global new_data_since_last_reset, last_reset_time

    now = time.time()

    with _lock:
        try:
            with db_cursor() as cur:
                cur.execute(
                    "INSERT INTO reports (flooded, level_category) VALUES (%s, %s)",
                    (flooded, level_category),
                )
        except psycopg.OperationalError as exc:
            app.logger.error("Unable to save incoming report: %s", exc)
            return

        new_data_since_last_reset = True

        if (now - last_reset_time) >= 600 and new_data_since_last_reset:
            try:
                _reset_db_keep_last_5()
            except psycopg.OperationalError as exc:
                app.logger.error("Failed to prune historic reports: %s", exc)
            else:
                last_reset_time = now
                new_data_since_last_reset = False


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


def on_line_message(message_text: str, event: MessageEvent) -> Optional[str]:
    """
    Hook that is invoked whenever a LINE user sends a text message.
    Return a string to reply with a text message, or None to skip replying.
    """
    app.logger.info("Received LINE message: %s", message_text)

    if message_text == "สถานะปัจจุบัน":
        # Query Flood Status If Flood >= 3 return "Flood" else return "Not Flood"
        reports = get_reports()
        flooded_count = sum(1 for row in reports if row.get("flooded"))
        level_categories = [
            row.get("level_category")
            for row in reports
            if row.get("flooded") and row.get("level_category")
        ]
        level_translation = None
        if level_categories:
            most_common_level, _ = Counter(level_categories).most_common(1)[0]
            thai_level_map = {
                "walkable": "ยังสามารถเดินผ่านได้",
                "motorcycle": "รถจักรยานยนต์ผ่านไม่ได้",
                "car": "รถยนต์ผ่านไม่ได้",
            }
            level_translation = thai_level_map.get(most_common_level, "ไม่มีข้อมูลระดับนํ้า")
        if flooded_count >= 3:
            if level_translation:
                return "นํ้าท่วม 🌊 " + level_translation
            return "นํ้าท่วม 🌊 ไม่มีข้อมูลระดับนํ้า"
        return "น้ำไม่ท่วม"

    return None


if webhook_handler is not None and line_bot_api is not None:

    @webhook_handler.add(MessageEvent, message=TextMessage)
    def handle_text_message(event: MessageEvent) -> None:
        response_text = on_line_message(event.message.text, event)
        if response_text:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=response_text),
            )


@app.route("/line/webhook", methods=["POST"])
def line_webhook():
    if webhook_handler is None:
        app.logger.warning("LINE webhook invoked but credentials are not configured.")
        return "LINE webhook not configured", 503

    signature = request.headers.get("X-Line-Signature")
    if signature is None:
        return "Missing signature", 400

    body = request.get_data(as_text=True)
    app.logger.debug("LINE webhook body: %s", body)

    try:
        webhook_handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.warning("Received invalid LINE signature.")
        return "Invalid signature", 400

    return "OK", 200


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
