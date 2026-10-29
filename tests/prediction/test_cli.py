# -*- coding: utf-8 -*-
"""CLI end-to-end tests — spec §7 acceptance (one VALID, one INSUFFICIENT_DATA)."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from football_prediction.cli import main

KICKOFF = "2026-09-20T14:00:00+00:00"
RETRIEVED = "2026-09-19T10:00:00+00:00"


def _write(tmp: dict) -> str:
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(tmp, f, ensure_ascii=False)
    f.close()
    return f.name


VALID_INPUT = {
    "schema_version": "prediction_input.v1",
    "match": {"home_team": "Arsenal", "away_team": "Chelsea", "league": "E0",
              "kickoff_utc": KICKOFF},
    "odds": {"context": "preclosing", "source": "test-feed", "retrieved_at": RETRIEVED,
             "books": {"B365": {"H": 2.10, "D": 3.50, "A": 3.60, ">2.5": 1.90, "<2.5": 1.95},
                       "VC": {"H": 2.05, "D": 3.40, "A": 3.55, ">2.5": 1.88, "<2.5": 1.97},
                       "WH": {"H": 2.15, "D": 3.45, "A": 3.65, ">2.5": 1.92, "<2.5": 1.93},
                       "PS": {"H": 2.08, "D": 3.42, "A": 3.58, ">2.5": 1.89, "<2.5": 1.96}}},
    "external_signals": [],
}
NO_ODDS_INPUT = {
    "schema_version": "prediction_input.v1",
    "match": {"home_team": "Bayern", "away_team": "Dortmund", "league": "D1",
              "kickoff_utc": KICKOFF},
    "odds": {"context": "preclosing", "source": "test-feed", "retrieved_at": RETRIEVED,
             "books": {}},
    "external_signals": [],
}


class TestCli(unittest.TestCase):
    def _run(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(argv)
        return code, buf.getvalue()

    def test_valid_prediction_exit_0(self):
        path = _write(VALID_INPUT)
        try:
            code, out = self._run(["predict", "--input", path, "--pretty"])
        finally:
            Path(path).unlink()
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertEqual(parsed["overall_status"], "VALID")
        self.assertEqual(parsed["ftr"]["method"]["method_id"], "M4")

    def test_insufficient_data_exit_1(self):
        path = _write(NO_ODDS_INPUT)
        try:
            code, out = self._run(["predict", "--input", path])
        finally:
            Path(path).unlink()
        self.assertEqual(code, 1)
        parsed = json.loads(out)
        self.assertEqual(parsed["overall_status"], "INSUFFICIENT_DATA")
        self.assertIsNone(parsed["ftr"]["probabilities"])

    def test_rejected_exit_2(self):
        bad = json.loads(json.dumps(VALID_INPUT))
        bad["odds"]["context"] = "closing"
        path = _write(bad)
        try:
            code, out = self._run(["predict", "--input", path])
        finally:
            Path(path).unlink()
        self.assertEqual(code, 2)

    def test_self_check(self):
        code, out = self._run(["self-check"])
        parsed = json.loads(out)
        self.assertIn(parsed["verified"], (True, False))  # depends on repo state, never raises
        self.assertIn("referenced_sha256", parsed)


if __name__ == "__main__":
    unittest.main()
