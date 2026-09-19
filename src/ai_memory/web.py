"""Read-only local web page for browsing the usage audit log. Binds to 127.0.0.1 only."""
import json
import sqlite3
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import parse_qs, urlparse

from . import index

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
_ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
    "connect-src 'self'; base-uri 'none'; form-action 'none'"
)


def read_audit(filters: dict[str, str]) -> dict:
    conditions, params = ["1 = 1"], []
    for field in ("tool", "llm", "project"):
        value = filters.get(field, "").strip()
        if value:
            conditions.append(f"{field} = ?")
            params.append(value)

    query = filters.get("query", "").strip()
    if query:
        conditions.append("query LIKE ? ESCAPE '\\'")
        params.append(f"%{index.like_escape(query)}%")

    status = filters.get("status", "").strip()
    if status == "success":
        conditions.append("ok = 1")
    elif status == "failed":
        conditions.append("ok = 0")

    try:
        limit = max(1, min(int(filters.get("limit", "100")), 500))
    except ValueError:
        limit = 100

    where = " AND ".join(conditions)
    conn = index.connect()
    try:
        conn.execute("PRAGMA query_only = ON")
        totals = conn.execute(
            "SELECT COUNT(*) AS total, COUNT(DISTINCT NULLIF(query, '')) AS unique_queries, "
            "COUNT(DISTINCT NULLIF(llm, '')) AS callers, COUNT(DISTINCT NULLIF(project, '')) AS projects "
            f"FROM usage_audit WHERE {where}",
            params,
        ).fetchone()
        rows = conn.execute(
            "SELECT ts, tool, llm, project, query, result_count, ok, error "
            f"FROM usage_audit WHERE {where} ORDER BY id DESC LIMIT ?",
            [*params, limit],
        ).fetchall()
    finally:
        conn.close()

    return {
        "stats": {key: totals[key] for key in ("total", "unique_queries", "callers", "projects")},
        "rows": [{**dict(row), "ok": bool(row["ok"])} for row in rows],
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "ai-memory"

    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", _CSP)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, status: int = 200) -> None:
        self._send(json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

    def do_GET(self) -> None:
        # A hostile web page can point its own domain at 127.0.0.1 (DNS rebinding) and read this
        # server as "same origin". Requiring a loopback Host header defeats that.
        if self.headers.get("Host", "").rsplit(":", 1)[0] not in _ALLOWED_HOSTS:
            self._send(b"Forbidden", "text/plain; charset=utf-8", 403)
            return

        parsed = urlparse(self.path)
        if parsed.path == "/api/audit":
            filters = {key: values[-1] for key, values in parse_qs(parsed.query).items() if values}
            try:
                self._json(read_audit(filters))
            except (sqlite3.Error, OSError) as exc:
                self._json({"error": f"cannot read audit data: {exc}"}, 500)
        elif parsed.path in ("/", "/audit.html"):
            html = resources.files("ai_memory").joinpath("web/audit.html").read_bytes()
            self._send(html, "text/html; charset=utf-8")
        else:
            self._send(b"Not found", "text/plain; charset=utf-8", 404)

    def log_message(self, format: str, *args) -> None:
        return


def create_server(port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((HOST, port), Handler)


def serve(port: int = DEFAULT_PORT, open_browser: bool = True) -> int:
    try:
        server = create_server(port)
    except OSError as exc:
        print(f"error: cannot listen on {HOST}:{port} ({exc}). Try --port.", file=sys.stderr)
        return 1
    url = f"http://{HOST}:{server.server_address[1]}"
    print(f"ai-memory audit page: {url}  (read only, Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open_new_tab(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0
