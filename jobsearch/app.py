"""Minimal search web app for the normalized job listings.

Usage:
    python3 ingest.py       # build jobs.db from sample_data/ (or --data-dir real_data)
    python3 app.py          # serve on http://localhost:8000
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from db import get_connection, search_jobs, facets

STATIC_DIR = Path(__file__).parent / "static"
PORT = 8000


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, content_type):
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        if parsed.path == "/" or parsed.path == "/index.html":
            self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return

        if parsed.path == "/api/facets":
            conn = get_connection()
            self._send_json(facets(conn))
            return

        if parsed.path == "/api/jobs":
            conn = get_connection()
            limit = int(params.get("limit", 50))
            offset = int(params.get("offset", 0))
            total, items = search_jobs(
                conn,
                q=params.get("q"),
                company=params.get("company"),
                prefecture=params.get("prefecture"),
                employment_type=params.get("employment_type"),
                limit=limit,
                offset=offset,
            )
            for item in items:
                if item.get("extra"):
                    item["extra"] = json.loads(item["extra"])
            self._send_json({"total": total, "items": items})
            return

        self._send_json({"error": "not found"}, status=404)

    def log_message(self, format, *args):
        pass  # keep stdout quiet for a local prototype


def main():
    if not (Path(__file__).parent / "jobs.db").exists():
        print("jobs.db が見つかりません。先に `python3 ingest.py` を実行してください。")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"http://localhost:{PORT} で起動しました")
    server.serve_forever()


if __name__ == "__main__":
    main()
