# -*- coding: utf-8 -*-
"""Tests for the ESPN odds adapter + orchestration service (no network).

Canned payloads mirror the real ESPN scoreboard shape observed on
2026-10-24 (DraftKings provider, American odds, moneyline/total blocks).
"""
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
from football_prediction.predictor import predict_match  # noqa: E402
from football_prediction.service import (  # noqa: E402
    PredictionService, attach_score_matrix, build_prediction_input,
)


def _fixture(kickoff: datetime) -> dict:
    return {
        "event_id": "401878768", "league": "eng.1", "league_label": "英超",
        "league_name": "English Premier League",
        "kickoff_utc": kickoff.isoformat(timespec="seconds"),
        "home": "Arsenal", "away": "Everton",
        "home_abbr": "ARS", "away_abbr": "EVE", "state": "pre",
    }


def _comp(ou_line=2.5) -> dict:
    """Real-shape ESPN competition odds (Everton @ Arsenal, DraftKings)."""
    return {"odds": [{
        "provider": {"id": "100", "name": "DraftKings"},
        "overUnder": ou_line,
        "moneyline": {"home": {"close": {"odds": "-215"}},
                      "away": {"close": {"odds": "+650"}},
                      "draw": {"close": {"odds": "+330"}}},
        "total": {"over": {"close": {"odds": "-115"}},
                  "under": {"close": {"odds": "-105"}}},
        "drawOdds": {"moneyLine": 330},
    }]}


class AmericanOddsTest(unittest.TestCase):
    def test_conversions(self):
        cases = [("-215", 1.465116), ("+400", 5.0), (330, 4.3),
                 ("-115", 1.869565), ("-105", 1.952381), ("+650", 7.5),
                 (2.5, 2.5), ("", None), (None, None), ("abc", None), (0, None)]
        for value, expected in cases:
            with self.subTest(value=value):
                got = F.american_to_decimal(value)
                if expected is None:
                    self.assertIsNone(got)
                else:
                    self.assertAlmostEqual(got, expected, places=5)

    def test_provider_codes(self):
        self.assertEqual(F.provider_to_code("DraftKings"), "DK")
        self.assertEqual(F.provider_to_code("Bet 365"), "B365")
        self.assertEqual(F.provider_to_code("Unknown Book XY"), "UNKN")


class ExtractBooksTest(unittest.TestCase):
    def test_line_2_5_full_legs(self):
        books, providers = F.extract_books(_comp(2.5))
        self.assertEqual(list(books), ["DK"])
        legs = books["DK"]
        self.assertEqual(sorted(legs), ["<2.5", ">2.5", "A", "D", "H"])
        self.assertAlmostEqual(legs["H"], 1.465116, places=5)
        self.assertAlmostEqual(legs["D"], 4.3, places=5)
        self.assertAlmostEqual(legs["A"], 7.5, places=5)
        self.assertAlmostEqual(legs[">2.5"], 1.869565, places=5)
        self.assertTrue(providers[0]["ou_used"])

    def test_line_3_5_skips_ou(self):
        books, providers = F.extract_books(_comp(3.5))
        self.assertEqual(sorted(books["DK"]), ["A", "D", "H"])
        self.assertFalse(providers[0]["ou_used"])
        self.assertIn("2.5", providers[0]["note"])

    def test_missing_moneyline_keeps_ou_only_book(self):
        comp = {"odds": [{"provider": {"name": "DraftKings"},
                          "overUnder": 2.5,
                          "total": {"over": {"close": {"odds": "-115"}},
                                    "under": {"close": {"odds": "-105"}}}}]}
        books, _ = F.extract_books(comp)
        # incomplete 1X2 book is still passed through with its OU legs; the
        # predictor itself drops it from the 1X2 method and the service
        # requires a complete 1X2 book elsewhere before predicting
        self.assertEqual(sorted(books["DK"]), ["<2.5", ">2.5"])


class ParseEventTest(unittest.TestCase):
    def test_normalizes_kickoff(self):
        ev = {
            "id": "401878768", "date": "2026-10-24T14:00Z",
            "status": {"type": {"state": "pre"}},
            "leagues": [{"name": "English Premier League"}],
            "competitions": [{
                "competitors": [
                    {"homeAway": "home", "team": {"displayName": "Arsenal",
                                                  "abbreviation": "ARS"}},
                    {"homeAway": "away", "team": {"displayName": "Everton",
                                                  "abbreviation": "EVE"}},
                ],
            }],
        }
        rec = F.parse_event(ev, "eng.1")
        self.assertEqual(rec["kickoff_utc"], "2026-10-24T14:00:00+00:00")
        self.assertEqual(rec["home"], "Arsenal")
        self.assertEqual(rec["state"], "pre")


class EndToEndPredictionTest(unittest.TestCase):
    """Canned ESPN data -> prediction_input.v1 -> frozen predictor -> matrix."""

    def test_future_kickoff_prediction(self):
        fixture = _fixture(datetime.now(timezone.utc) + timedelta(hours=26))
        books, providers = F.extract_books(_comp(2.5))
        raw = build_prediction_input(fixture, books, providers)
        self.assertEqual(raw["odds"]["context"], "preclosing")

        out = predict_match(raw)
        self.assertIn(out["overall_status"], ("VALID", "CONDITIONAL"))
        self.assertIsNotNone(out["ftr"]["probabilities"])
        probs = out["ftr"]["probabilities"]
        self.assertAlmostEqual(sum(probs.values()), 1.0, places=9)
        self.assertGreater(probs["home"], probs["away"])  # -215 favourite
        self.assertIsNotNone(out["ou25"]["probabilities"])

        attach_score_matrix(out)
        sm = out["score_matrix"]
        self.assertEqual(sm["status"], "VALID")
        self.assertAlmostEqual(sm["aggregates"]["home"], probs["home"], places=6)
        self.assertAlmostEqual(sm["aggregates"]["draw"], probs["draw"], places=6)
        self.assertAlmostEqual(sm["aggregates"]["away"], probs["away"], places=6)
        self.assertAlmostEqual(sm["aggregates"]["over25"],
                               out["ou25"]["probabilities"]["over"], places=6)

    def test_past_kickoff_rejected_by_time_safety(self):
        fixture = _fixture(datetime.now(timezone.utc) - timedelta(hours=1))
        books, providers = F.extract_books(_comp(2.5))
        raw = build_prediction_input(fixture, books, providers)
        out = predict_match(raw)
        self.assertEqual(out["overall_status"], "REJECTED")
        self.assertTrue(any("time-safety" in r for r in out["rejection_reasons"]))


class ServiceFlowTest(unittest.TestCase):
    def _service(self, fixture: dict | None = None):
        # isolated feed + audit-log paths so tests never touch real files
        svc = PredictionService(feed_path=self._tmp / "feed.json",
                                predict_log_path=self._tmp / "log.jsonl")
        fixture = fixture or _fixture(
            datetime.now(timezone.utc) + timedelta(hours=26))
        return svc, fixture

    def setUp(self):
        import tempfile
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._tmp = Path(self._tmp_dir.name)

    def tearDown(self):
        self._tmp_dir.cleanup()

    def test_happy_path(self):
        svc, fixture = self._service()
        fresh = dict(fixture)
        with patch.object(F, "load_feed", return_value=([fixture], None)), \
             patch.object(F, "get_event", return_value=(fresh, _comp(2.5))):
            status, payload = svc.predict_event(fixture["event_id"])
        self.assertEqual(status, 200)
        pred = payload["prediction"]
        self.assertIn(pred["overall_status"], ("VALID", "CONDITIONAL"))
        self.assertEqual(pred["score_matrix"]["status"], "VALID")

    def test_match_started_blocked(self):
        svc, fixture = self._service()
        started = dict(fixture, state="in")
        with patch.object(F, "load_feed", return_value=([fixture], None)), \
             patch.object(F, "get_event", return_value=(started, _comp(2.5))):
            status, payload = svc.predict_event(fixture["event_id"])
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "MATCH_NOT_PRE")

    def test_no_odds_blocked(self):
        svc, fixture = self._service()
        with patch.object(F, "load_feed", return_value=([fixture], None)), \
             patch.object(F, "get_event", return_value=(dict(fixture), {"odds": []})):
            status, payload = svc.predict_event(fixture["event_id"])
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "NO_ODDS")

    def test_unknown_event_404(self):
        svc, _ = self._service()
        with patch.object(F, "load_feed", return_value=([], None)), \
             patch.object(F, "fetch_fixtures", return_value=[]):
            status, payload = svc.predict_event("999")
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "EVENT_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
