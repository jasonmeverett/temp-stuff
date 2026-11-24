import argparse
import asyncio
import fcntl
import json
import logging
import os
import signal
import sqlite3
import threading
import time
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from reader import Reading, TP920Reader

APP_DIR = Path(__file__).resolve().parent
WEB_DIR = APP_DIR / "web"
DATA_DIR = APP_DIR / "data"
PLOTLY_BUNDLE = APP_DIR.parent / "node_modules/plotly.js/dist/plotly.min.js"
INTERVAL_SECONDS = 10
HISTORY_HOURS = 24
STATIC_FILES = {
    "/": (WEB_DIR / "index.html", "text/html; charset=utf-8"),
    "/app.js": (WEB_DIR / "app.js", "text/javascript; charset=utf-8"),
    "/style.css": (WEB_DIR / "style.css", "text/css; charset=utf-8"),
    "/plotly-dark.json": (WEB_DIR / "plotly-dark.json", "application/json"),
    "/plotly.min.js": (PLOTLY_BUNDLE, "text/javascript; charset=utf-8"),
}

logger = logging.getLogger(__name__)


def now_ms() -> int:
    return time.time_ns() // 1_000_000


class SampleStore:
    def __init__(self, path: Path):
        self.path = path
        self.condition = threading.Condition()
        self.revision = 0
        self.closed = False
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("PRAGMA journal_mode = WAL")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sampled_at_ms INTEGER NOT NULL,
                    received_at_ms INTEGER,
                    probe1_c REAL,
                    probe2_c REAL,
                    state TEXT NOT NULL,
                    packet_hex TEXT
                )
                """
            )
            db.execute("CREATE INDEX IF NOT EXISTS samples_time ON samples (sampled_at_ms)")

    def append(self, state: str, reading: Reading | None):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                """
                INSERT INTO samples
                    (sampled_at_ms, received_at_ms, probe1_c, probe2_c, state, packet_hex)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    now_ms(),
                    reading.received_at_ms if reading else None,
                    reading.probe1_c if reading else None,
                    reading.probe2_c if reading else None,
                    state,
                    reading.packet_hex if reading else None,
                ),
            )
        with self.condition:
            self.revision += 1
            self.condition.notify_all()

    def recent(self, after: int = 0) -> list[dict]:
        cutoff = now_ms() - HISTORY_HOURS * 3_600_000
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                """
                SELECT * FROM samples
                WHERE sampled_at_ms >= ? AND id > ?
                ORDER BY id
                """,
                (cutoff, after),
            )
            return [dict(row) for row in rows]

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()


class DashboardServer(ThreadingHTTPServer):
    def __init__(self, port: int, store: SampleStore):
        self.store = store
        super().__init__(("127.0.0.1", port), RequestHandler)


class RequestHandler(BaseHTTPRequestHandler):
    server: DashboardServer

    def log_message(self, fmt, *args):
        logger.debug(fmt, *args)

    def send_bytes(self, body: bytes, mime: str):
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        location = urlsplit(self.path)
        try:
            if location.path == "/api/history":
                payload = {
                    "interval_seconds": INTERVAL_SECONDS,
                    "history_hours": HISTORY_HOURS,
                    "samples": self.server.store.recent(),
                }
                self.send_bytes(json.dumps(payload, separators=(",", ":")).encode(), "application/json")
            elif location.path == "/api/stream":
                query = parse_qs(location.query)
                cursor = self.headers.get("Last-Event-ID") or query.get("after", ["0"])[0]
                self.stream(cursor)
            elif location.path in STATIC_FILES:
                path, mime = STATIC_FILES[location.path]
                self.send_bytes(path.read_bytes(), mime)
            else:
                self.send_error(404)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except FileNotFoundError:
            self.send_error(404)

    def stream(self, after: str):
        try:
            cursor = int(after)
            if not 0 <= cursor <= 2**63 - 1:
                raise ValueError
        except ValueError:
            self.send_error(400, "Invalid sample cursor")
            return

        self.connection.settimeout(10)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(b"retry: 2000\n\n")
        self.wfile.flush()

        store = self.server.store
        while not store.closed:
            with store.condition:
                revision = store.revision
            for sample in store.recent(cursor):
                cursor = sample["id"]
                data = json.dumps(sample, separators=(",", ":"))
                self.wfile.write(f"id: {cursor}\nevent: sample\ndata: {data}\n\n".encode())
            self.wfile.flush()
            with store.condition:
                changed = store.condition.wait_for(
                    lambda: store.closed or store.revision != revision,
                    timeout=12,
                )
            if not changed:
                self.wfile.write(b": heartbeat\n\n")
                self.wfile.flush()


async def record_samples(store: SampleStore, reader: TP920Reader):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + INTERVAL_SECONDS
    while True:
        await asyncio.sleep(max(0, deadline - loop.time()))
        reading = reader.fresh_reading
        try:
            store.append("live" if reading else reader.state, reading)
        except sqlite3.Error:
            logger.exception("SQLite could not save a temperature sample")
        deadline += INTERVAL_SECONDS
        if deadline <= loop.time():
            deadline = loop.time() + INTERVAL_SECONDS


async def run(port: int, store: SampleStore):
    reader = TP920Reader()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)

    with DashboardServer(port, store) as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        logger.info("Dashboard at http://127.0.0.1:%d/ with %s", server.server_port, store.path)
        tasks = {
            asyncio.create_task(reader.run()),
            asyncio.create_task(record_samples(store, reader)),
            asyncio.create_task(stop.wait()),
        }
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            store.close()
            server.shutdown()


def main():
    parser = argparse.ArgumentParser(description="Record TP920 probe temperatures and serve a local dashboard.")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    DATA_DIR.mkdir(mode=0o700, exist_ok=True)
    with (DATA_DIR / "recorder.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("The TP920 recorder is already running.")
        lock.seek(0)
        lock.truncate()
        lock.write(f"{os.getpid()}\n")
        lock.flush()
        asyncio.run(run(args.port, SampleStore(DATA_DIR / "readings.sqlite3")))


if __name__ == "__main__":
    main()
