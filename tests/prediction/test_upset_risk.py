# -*- coding: utf-8 -*-
"""Tests for the derived upset-risk block (thresholds aligned with System A)."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from football_prediction import odds_feed as F  # noqa: E402
from football_prediction.score_matrix import derive_score_matrix  # noqa: E402
from football_prediction.service import (  # noqa: E402
    PredictionService, attach_upset_risk)
from football_prediction.upset_risk import derive_upset_risk  # noqa: E402


class ThresholdAlignmentTest(unittest.TestCase):
    """Mirror football_simulation.agents.risk.UpsetRiskAgent levels exactly."""

    def test_extreme_favourite(self):
        # p_fav=0.92, p_dog=0.03 -> severity 1.0 -> VERY_HIGH, but p_dog<0.08
        # caps it to HIGH; p_dog not < 0.03 so it stays HIGH ("upset" type)
        out = derive_upset_risk(0.92, 0.05, 0.03)
        self.assertEqual(out["level"], "HIGH")
        self.assertEqual(out["upset_type"], "upset")
        self.assertEqual(out["favourite"], "home")
        self.assertEqual(out["direction"], "away_win")
        self.assertAlmostEqual(out["probability"], 0.03, places=6)

    def test_tiny_upset_capped_further(self):
        # p_dog=0.02: severity>=0.65 -> VERY_HIGH -> <0.08 -> HIGH -> <0.03 -> MEDIUM
        out = derive_upset_risk(0.90, 0.08, 0.02)
        self.assertEqual(out["level"], "MEDIUM")

    def test_moderate_surprise(self):
        # p_fav=0.45, p_dog=0.28 -> severity 0.272 -> MEDIUM; p_dog>=0.20
        out = derive_upset_risk(0.45, 0.27, 0.28)
        self.assertEqual(out["level"], "MEDIUM")
        self.assertEqual(out["upset_type"], "moderate_surprise")

    def test_open_game(self):
        out = derive_upset_risk(0.35, 0.30, 0.35)
        self.assertEqual(out["level"], "LOW")
        self.assertEqual(out["upset_type"], "open_game")

    def test_away_favourite_direction(self):
        out = derive_upset_risk(0.18, 0.22, 0.60)
        self.assertEqual(out["favourite"], "away")
        self.assertEqual(out["direction"], "home_win")
        self.assertAlmostEqual(out["favourite_fails_probability"], 0.40, places=6)

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            derive_upset_risk(0.5, 0.2, 0.1)   # sums to 0.8
        with self.assertRaises(ValueError):
            derive_upset_risk(0.0, 0.5, 0.5)


class MatrixExtensionTest(unittest.TestCase):
    def test_extreme_scores_from_matrix(self):
        sm = derive_score_matrix(0.65, 0.22, 0.13, 0.60)  # home favourite
        out = derive_upset_risk(0.65, 0.22, 0.13, score_matrix=sm)
        # extreme scores must all be away-win cells (a > h), sorted desc
        ex = out["extreme_scores"]
        self.assertTrue(ex)
        self.assertTrue(all(t["away_goals"] > t["home_goals"] for t in ex))
        probs = [t["probability"] for t in ex]
        self.assertEqual(probs, sorted(probs, reverse=True))
        # underdog-by-2 is a subset of the matrix away aggregate
        self.assertLessEqual(out["probability_underdog_by_2"],
                             sm["aggregates"]["away"] + 1e-9)
        # top away-win cell must match the matrix's own argmax over a>h cells
        best = max(((h, a, p) for h in range(len(sm["matrix"]))
                    for a, p in enumerate(sm["matrix"][h]) if a > h),
                   key=lambda c: c[2])
        self.assertEqual(f"{best[0]}-{best[1]}", ex[0]["score"])

    def test_drivers_market_uncertainty(self):
        out = derive_upset_risk(0.45, 0.27, 0.28,
                                ftr_entropy_bits=1.5,
                                book_dispersion=0.07, n_books=1)
        drivers = " ".join(out["drivers"])
        self.assertIn("庄家分歧大", drivers)
        self.assertIn("熵高", drivers)
        self.assertIn("单庄家", drivers)


class ServiceAttachTest(unittest.TestCase):
    def test_attach_on_full_output(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            svc = PredictionService(feed_path=Path(tmp) / "f.json",
                                    predict_log_path=Path(tmp) / "l.jsonl")
            kick = datetime.now(timezone.utc) + timedelta(hours=30)
            fixture = {"event_id": "1", "league": "eng.1",
                       "league_label": "英超", "league_name": "English Premier League",
                       "kickoff_utc": kick.isoformat(timespec="seconds"),
                       "home": "Arsenal", "away": "Everton",
                       "home_abbr": "", "away_abbr": "", "state": "pre"}
            comp = {"odds": [{
                "provider": {"name": "DraftKings"}, "overUnder": 2.5,
                "moneyline": {"home": {"close": {"odds": "-215"}},
                              "away": {"close": {"odds": "+650"}},
                              "draw": {"close": {"odds": "+330"}}},
                "total": {"over": {"close": {"odds": "-115"}},
                          "under": {"close": {"odds": "-105"}}}}]}
            with patch.object(F, "load_feed", return_value=([fixture], None)), \
                 patch.object(F, "get_event", return_value=(dict(fixture), comp)):
                status, payload = svc.predict_event("1")
        self.assertEqual(status, 200)
        ur = payload["prediction"]["upset_risk"]
        self.assertEqual(ur["status"], "VALID")
        # -215 favourite ~0.66 -> severity ~0.85 -> VERY_HIGH, p_dog ~0.12 not
        # <0.08 -> stays VERY_HIGH; consistent with the ftr probabilities
        probs = payload["prediction"]["ftr"]["probabilities"]
        self.assertEqual(ur["favourite"],
                         "home" if probs["home"] >= probs["away"] else "away")
        self.assertAlmostEqual(ur["probability"],
                               min(probs["home"], probs["away"]), places=6)
        self.assertTrue(ur["extreme_scores"])

    def test_attach_without_probs(self):
        out = {"ftr": {"probabilities": None}}
        attach_upset_risk(out)
        self.assertEqual(out["upset_risk"]["status"], "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
