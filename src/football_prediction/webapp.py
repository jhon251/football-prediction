# -*- coding: utf-8 -*-
"""One-click prediction webapp (stdlib only, same style as the simulation API).

Endpoints:
    GET  /                  -> static single-page UI (static/index.html)
    GET  /api/health        -> liveness + module versions
    GET  /api/fixtures      -> upcoming pre-match fixtures (fixtures feed)
                               ?refresh=1 forces an ESPN re-fetch
    POST /api/predict       -> body {"event_id": "...", "force": false}
                               capture pre-match odds, run the frozen
                               predictor, attach the derived score matrix

Run from the repo root:  python -m football_prediction.cli serve --port 8600
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from football_prediction import injuries_feed as FD
from football_prediction import odds_api as TOA
from football_prediction.service import PredictionService

STATIC_DIR = Path(__file__).resolve().parent / "static"
_VERSION = "football_prediction webapp 0.1.0"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
}


class WebAppHandler(BaseHTTPRequestHandler):
    service: PredictionService = None  # set by run_server
    server_version = "FootballPrediction/0.1"

    # ------------------------------------------------------------------ GET
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            return self._serve_file(STATIC_DIR / "index.html")
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if path == "/api/health":
            return self._json(200, {
                "status": "ok",
                "version": _VERSION,
                "odds_api": {
                    "configured": TOA.is_configured(),
                    "last_capture": getattr(self.service, "odds_api_status", {}),
                },
                "injuries_api": {"configured": FD.is_configured()},
            })
        if path == "/api/fixtures":
            qs = parse_qs(parsed.query)
            refresh = qs.get("refresh", ["0"])[0] in ("1", "true")
            try:
                return self._json(200, self.service.list_fixtures(refresh=refresh))
            except Exception as exc:  # noqa: BLE001
                return self._json(502, {"error": {"code": "FEED_ERROR",
                                                  "message": str(exc)[:300]}})
        return self._json(404, {"error": {"code": "NOT_FOUND", "path": path}})

    # ----------------------------------------------------------------- POST
    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/predict":
            return self._json(404, {"error": {"code": "NOT_FOUND", "path": path}})
        body = self._read_body()
        event_id = body.get("event_id")
        if not event_id:
            return self._json(400, {"error": {"code": "BAD_REQUEST",
                                              "message": "event_id required"}})
        try:
            status, payload = self.service.predict_event(
                str(event_id), force=bool(body.get("force")))
        except Exception as exc:  # noqa: BLE001 - surface internals plainly
            return self._json(500, {"error": {"code": "INTERNAL",
                                              "message": f"{type(exc).__name__}: "
                                                         f"{exc}"[:500]}})
        return self._json(status, payload)

    # ------------------------------------------------------------- plumbing
    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def _serve_file(self, path: Path) -> None:
        try:
            data = path.read_bytes()
        except OSError:
            return self._json(404, {"error": {"code": "NO_UI",
                                              "message": f"{path.name} missing"}})
        ctype = _CONTENT_TYPES.get(path.suffix, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args: Any) -> None:  # quieter logs
        pass


def _warm_feed(service: PredictionService) -> None:
    """Background: make the first page load fast by pre-filling a stale feed."""
    try:
        service.list_fixtures(refresh=False)
    except Exception:  # noqa: BLE001 - warm-up is best-effort
        pass


def run_server(host: str = "127.0.0.1", port: int = 8600) -> None:
    service = PredictionService()
    threading.Thread(target=_warm_feed, args=(service,), daemon=True).start()
    handler = type("Handler", (WebAppHandler,), {"service": service})
    server = ThreadingHTTPServer((host, port), handler)
    print(f"{_VERSION} listening on http://{host}:{port}")
    print("GET / | GET /api/fixtures[?refresh=1] | POST /api/predict | "
          "GET /api/health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    run_server()
