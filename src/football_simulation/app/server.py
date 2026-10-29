"""HTTP API (stdlib only - no framework dependency).

Endpoints (spec section 72):
    POST /matches/analyze
    GET  /matches/{match_id}
    POST /matches/{match_id}/simulate
    GET  /matches/{match_id}/scenarios
    GET  /matches/{match_id}/probabilities
    GET  /matches/{match_id}/risks
    GET  /matches/{match_id}/trace
    GET  /health
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from football_simulation.agents.director import DirectorAgent, DirectorConfig
from football_simulation.config import load_config
from football_simulation.data import MockDataProvider


class MatchService:
    """Shared service state: provider, director, cached reports."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_config()
        self.provider = MockDataProvider()
        self.reports: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def director(self, **overrides: Any) -> DirectorAgent:
        from football_simulation.config import director_config

        dconfig = director_config(self.config)
        for key, value in overrides.items():
            if value is not None:
                setattr(dconfig, key, value)
        return DirectorAgent(self.provider, dconfig)

    def analyze(self, match_id: str, runs: Optional[int] = None, seed: Optional[int] = None):
        director = self.director(simulation_runs=runs, seed=seed)
        report = director.analyze(match_id)
        with self._lock:
            self.reports[match_id] = report
        return report

    def get(self, match_id: str):
        with self._lock:
            report = self.reports.get(match_id)
        if report is None:
            report = self.analyze(match_id)
        return report


class ApiHandler(BaseHTTPRequestHandler):
    service: MatchService = None  # set by run_server
    server_version = "FootballSim/1.0"

    # ------------------------------------------------------------------
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        match = re.fullmatch(r"/matches/([^/]+)/simulate", path)
        if path == "/health":
            return self._json(200, {"status": "ok", "version": "1.0.0"})
        m = re.fullmatch(r"/matches/([^/]+)/scenarios", path)
        if m:
            return self._scenarios(m.group(1))
        m = re.fullmatch(r"/matches/([^/]+)/probabilities", path)
        if m:
            return self._probabilities(m.group(1))
        m = re.fullmatch(r"/matches/([^/]+)/risks", path)
        if m:
            return self._risks(m.group(1))
        m = re.fullmatch(r"/matches/([^/]+)/trace", path)
        if m:
            return self._trace(m.group(1))
        m = re.fullmatch(r"/matches/([^/]+)", path)
        if m:
            return self._report(m.group(1))
        return self._json(404, {"error": "not found", "path": path})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        body = self._read_body()
        if path == "/matches/analyze":
            match_id = body.get("match_id")
            if not match_id:
                return self._json(400, {"error": "match_id required"})
            try:
                report = self.service.analyze(
                    match_id,
                    runs=body.get("runs"),
                    seed=body.get("seed"),
                )
                return self._json(200, report.model_dump(mode="json"))
            except KeyError as exc:
                return self._json(404, {"error": str(exc)})
            except Exception as exc:  # pragma: no cover - defensive
                return self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
        m = re.fullmatch(r"/matches/([^/]+)/simulate", path)
        if m:
            try:
                from football_simulation.config import director_config

                director = self.service.director(
                    simulation_runs=body.get("runs"),
                    seed=body.get("seed"),
                )
                report = director.analyze(m.group(1))
                return self._json(200, {
                    "match_id": m.group(1),
                    "runs": report.simulation_runs,
                    "result_probability": report.result_probability.model_dump(),
                    "expected_total_goals": report.goals_probability.expected_total_goals,
                })
            except Exception as exc:
                return self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
        return self._json(404, {"error": "not found", "path": path})

    # ------------------------------------------------------------------
    def _report(self, match_id: str) -> None:
        try:
            report = self.service.get(match_id)
            return self._json(200, report.model_dump(mode="json"))
        except Exception as exc:
            return self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def _scenarios(self, match_id: str) -> None:
        report = self.service.get(match_id)
        return self._json(200, {
            "match_id": match_id,
            "scenarios": [s.model_dump(mode="json") for s in report.scenarios],
            "long_tail": report.scenario_ranking,
        })

    def _probabilities(self, match_id: str) -> None:
        report = self.service.get(match_id)
        return self._json(200, {
            "match_id": match_id,
            "result_probability": report.result_probability.model_dump(),
            "score_probability": report.score_probability.model_dump(),
            "goals_probability": report.goals_probability.model_dump(),
            "btts": report.btts.model_dump(),
            "half_time_full_time": report.half_time_full_time.model_dump(),
        })

    def _risks(self, match_id: str) -> None:
        report = self.service.get(match_id)
        return self._json(200, {
            "match_id": match_id,
            "upset_risk": report.upset_risk.model_dump(),
            "risk": report.risk.model_dump(),
            "confidence": report.confidence.model_dump(),
            "failure_conditions": [f.model_dump() for f in report.failure_conditions],
        })

    def _trace(self, match_id: str) -> None:
        report = self.service.get(match_id)
        return self._json(200, {"match_id": match_id, "trace": report.trace})

    # ------------------------------------------------------------------
    def _read_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args: Any) -> None:  # quieter logs
        pass


def run_server(host: str = "127.0.0.1", port: int = 8000, config: Optional[Dict[str, Any]] = None) -> None:
    service = MatchService(config or load_config())
    handler = type("Handler", (ApiHandler,), {"service": service})
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Football Simulation API listening on http://{host}:{port}")
    print("POST /matches/analyze | GET /matches/{id} | POST /matches/{id}/simulate |")
    print("GET /matches/{id}/{scenarios|probabilities|risks|trace} | GET /health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    run_server()
