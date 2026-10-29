"""CLI + API tests (stdlib server on an ephemeral port)."""

import json
import subprocess
import sys
import threading
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from football_simulation.app.server import MatchService, run_server

CLI = [sys.executable, "-m", "football_simulation.cli"]


class TestCLI(unittest.TestCase):
    def test_scenarios_command(self):
        proc = subprocess.run(
            CLI + ["scenarios", "match-demo-001", "--runs", "150", "--seed", "5"],
            capture_output=True, text=True, encoding="utf-8", timeout=300,
            env={**__import__("os").environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn("archetype", proc.stdout)
        self.assertIn("长尾", proc.stdout)

    def test_simulate_command(self):
        proc = subprocess.run(
            CLI + ["simulate", "match-demo-001", "--runs", "150", "--seed", "6"],
            capture_output=True, text=True, encoding="utf-8", timeout=300,
            env={**__import__("os").environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn("主胜", proc.stdout)

    def test_post_match_command(self):
        import os
        import shutil
        import uuid
        tmp = Path(__file__).resolve().parents[2] / "tests" / f".tmp_cli_{uuid.uuid4().hex[:8]}"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            cfg = tmp / "cfg.json"
            cfg.write_text(json.dumps({
                "simulation": {"default_runs": 200, "seed": 9},
                "learning": {"store_path": str(tmp / "learn.json")},
            }), encoding="utf-8")
            proc = subprocess.run(
                CLI + ["post-match", "match-demo-000", "--runs", "200", "--config", str(cfg)],
                capture_output=True, text=True, encoding="utf-8", timeout=300,
                env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
            )
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            self.assertIn("Post-Match Evaluation", proc.stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import socketserver
        service = MatchService()
        handler = type("H", (__import__("football_simulation.app.server", fromlist=["ApiHandler"]).ApiHandler,),
                       {"service": service})
        cls.server = __import__("football_simulation.app.server", fromlist=["ThreadingHTTPServer"]).ThreadingHTTPServer(
            ("127.0.0.1", 0), handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=600) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _post(self, path, payload):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def test_health(self):
        data = self._get("/health")
        self.assertEqual(data["status"], "ok")

    def test_analyze_endpoint(self):
        data = self._post("/matches/analyze", {"match_id": "match-demo-001", "runs": 120, "seed": 3})
        self.assertEqual(data["match"]["match_id"], "match-demo-001")
        self.assertIn("result_probability", data)
        self.assertIn("score_probability", data)
        self.assertIn("upset_risk", data)
        self.assertIn("confidence", data)
        self.assertIn("explanation", data)

    def test_get_match(self):
        self._post("/matches/analyze", {"match_id": "match-demo-001", "runs": 100, "seed": 3})
        data = self._get("/matches/match-demo-001")
        self.assertEqual(data["match"]["match_id"], "match-demo-001")

    def test_simulate_endpoint(self):
        data = self._post("/matches/match-demo-001/simulate", {"runs": 100, "seed": 4})
        self.assertIn("result_probability", data)
        self.assertIn("expected_total_goals", data)

    def test_probabilities_endpoint(self):
        self._post("/matches/analyze", {"match_id": "match-demo-001", "runs": 100, "seed": 3})
        data = self._get("/matches/match-demo-001/probabilities")
        self.assertIn("result_probability", data)
        self.assertIn("btts", data)
        self.assertIn("half_time_full_time", data)

    def test_risks_endpoint(self):
        self._post("/matches/analyze", {"match_id": "match-demo-001", "runs": 100, "seed": 3})
        data = self._get("/matches/match-demo-001/risks")
        self.assertIn("upset_risk", data)
        self.assertIn("risk", data)
        self.assertIn("confidence", data)

    def test_trace_endpoint(self):
        self._post("/matches/analyze", {"match_id": "match-demo-001", "runs": 100, "seed": 3})
        data = self._get("/matches/match-demo-001/trace")
        self.assertGreater(len(data["trace"]), 5)

    def test_scenarios_endpoint(self):
        self._post("/matches/analyze", {"match_id": "match-demo-001", "runs": 100, "seed": 3})
        data = self._get("/matches/match-demo-001/scenarios")
        self.assertGreater(len(data["scenarios"]), 3)

    def test_404(self):
        import urllib.error
        with self.assertRaises(urllib.error.HTTPError):
            self._get("/nope")


if __name__ == "__main__":
    unittest.main()
