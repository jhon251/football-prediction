# -*- coding: utf-8 -*-
"""Tests for the the-odds-api adapter and its merge into the service.

All canned payloads mirror the-odds-api v4 /odds response shape (decimal
odds, h2h + totals markets, bookmaker key/title). No network.
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

from football_prediction import odds_api as TOA  # noqa: E402
from football_prediction import odds_feed as F  # noqa: E402
from football_prediction.service import PredictionService  # noqa: E402


def _fixture(kickoff: datetime, league: str = "eng.1",
             home: str = "Arsenal", away: str = "Everton") -> dict:
    return {
        "event_id": "401878768", "league": league, "league_label": "英超",
        "league_name": "English Premier League",
        "kickoff_utc": kickoff.isoformat(timespec="seconds"),
        "home": home, "away": away,
        "home_abbr": "", "away_abbr": "", "state": "pre",
    }


def _bm(key: str, title: str, h: float, d: float, a: float,
        ou_point=2.5, over=1.90, under=1.95, drop_ou=False) -> dict:
    totals = {"key": "totals", "outcomes": [
        {"name": "Over", "point": ou_point, "price": over},
        {"name": "Under", "point": ou_point, "price": under},
    ]}
    return {"key": key, "title": title, "last_update": "2026-10-24T08:00:00Z",
            "markets": [
                {"key": "h2h", "outcomes": [
                    {"name": "Arsenal", "price": h},
                    {"name": "Draw", "price": d},
                    {"name": "Everton", "price": a},
                ]} if key else {},
            ] + ([] if drop_ou else [totals])}


def _toa_event(events_home="Arsenal", events_away="Everton",
               kickoff: datetime | None = None, bookmakers=None) -> dict:
    return {
        "id": "toa-1", "sport_key": "soccer_epl",
        "commence_time": (kickoff or datetime.now(timezone.utc)
                          + timedelta(hours=30)).isoformat(timespec="seconds"),
        "home_team": events_home, "away_team": events_away,
        "bookmakers": bookmakers if bookmakers is not None else [
            _bm("bet365", "Bet365", 2.05, 3.45, 3.80),
            _bm("pinnacle", "Pinnacle", 2.10, 3.40, 3.75),
            _bm("williamhill", "William Hill", 2.04, 3.50, 3.85),
            _bm("bwin", "bwin", 2.06, 3.44, 3.82),
        ],
    }


class ExtractBookmakerTest(unittest.TestCase):
    def test_full_book_with_2_5_line(self):
        code, legs, note = TOA.extract_bookmaker(
            _bm("bet365", "Bet365", 2.05, 3.45, 3.80),
            "Arsenal", "Everton")
        self.assertEqual(code, "B365")
        self.assertEqual(sorted(legs), ["<2.5", ">2.5", "A", "D", "H"])
        self.assertAlmostEqual(legs["H"], 2.05)
        self.assertAlmostEqual(legs["D"], 3.45)
        self.assertIsNone(note)

    def test_non_2_5_line_skips_ou(self):
        code, legs, note = TOA.extract_bookmaker(
            _bm("bet365", "Bet365", 2.05, 3.45, 3.80, ou_point=3.5),
            "Arsenal", "Everton")
        self.assertEqual(sorted(legs), ["A", "D", "H"])
        self.assertIn("2.5", note or "")

    def test_unknown_book_gets_sane_code(self):
        code, legs, _ = TOA.extract_bookmaker(
            _bm("somebook", "Some Book", 2.0, 3.5, 3.8),
            "Arsenal", "Everton")
        self.assertEqual(code, "SOME")

    def test_book_code_map(self):
        self.assertEqual(TOA.BOOK_CODES["pinnacle"], "PS")
        self.assertEqual(TOA.BOOK_CODES["williamhill"], "WH")


class MatchEventTest(unittest.TestCase):
    def setUp(self):
        self.kick = datetime.now(timezone.utc) + timedelta(hours=30)

    def test_exact_names(self):
        ev = TOA.match_event([_toa_event(kickoff=self.kick)],
                             "Arsenal", "Everton", self.kick)
        self.assertIsNotNone(ev)

    def test_ampersand_normalization(self):
        ev = _toa_event(events_home="Brighton and Hove Albion",
                        events_away="Wolverhampton Wanderers",
                        kickoff=self.kick)
        got = TOA.match_event([ev], "Brighton & Hove Albion",
                              "Wolverhampton Wanderers", self.kick)
        self.assertIsNotNone(got)

    def test_one_team_exact_carries_nicknamed_other(self):
        # ESPN "Internazionale" vs TOA "Inter Milan", opponent exact
        ev = _toa_event(events_home="Inter Milan", events_away="Fiorentina",
                        kickoff=self.kick)
        got = TOA.match_event([ev], "Internazionale", "Fiorentina", self.kick)
        self.assertIsNotNone(got)

    def test_different_match_rejected(self):
        ev = _toa_event(events_home="Barcelona", events_away="Sevilla",
                        kickoff=self.kick)
        got = TOA.match_event([ev], "Arsenal", "Everton", self.kick)
        self.assertIsNone(got)

    def test_kickoff_out_of_tolerance_rejected(self):
        ev = _toa_event(kickoff=self.kick + timedelta(minutes=40))
        self.assertIsNone(
            TOA.match_event([ev], "Arsenal", "Everton", self.kick))
        ev2 = _toa_event(kickoff=self.kick + timedelta(minutes=10))
        self.assertIsNotNone(
            TOA.match_event([ev2], "Arsenal", "Everton", self.kick))


class CaptureForTest(unittest.TestCase):
    def test_no_key_is_noop(self):
        books, provs, meta = TOA.capture_for(
            _fixture(datetime.now(timezone.utc) + timedelta(hours=30)), None)
        self.assertEqual((books, provs), ({}, []))
        self.assertFalse(meta["configured"])

    def test_unmapped_league(self):
        books, provs, meta = TOA.capture_for(
            _fixture(datetime.now(timezone.utc), league="xxx.9"), "k")
        self.assertEqual((books, provs), ({}, []))
        self.assertIn("not on the-odds-api", meta["note"])

    def test_capture_and_merge_shape(self):
        fixture = _fixture(datetime.now(timezone.utc) + timedelta(hours=30))
        events = [_toa_event(kickoff=datetime.fromisoformat(
            fixture["kickoff_utc"]))]
        with patch.object(TOA, "fetch_league_odds",
                          return_value=(events, {"requests_remaining": "487"})):
            books, provs, meta = TOA.capture_for(fixture, "k")
        self.assertEqual(sorted(books), ["B365", "BV", "PS", "WH"])
        self.assertTrue(meta["matched"])
        self.assertEqual(meta["requests_remaining"], "487")
        self.assertTrue(all(p["source"] == "the-odds-api" for p in provs))

    def test_no_matching_event(self):
        fixture = _fixture(datetime.now(timezone.utc) + timedelta(hours=30))
        other = _toa_event(events_home="Barcelona", events_away="Sevilla",
                           kickoff=datetime.now(timezone.utc)
                           + timedelta(hours=31))
        with patch.object(TOA, "fetch_league_odds",
                          return_value=([other], {})):
            books, provs, meta = TOA.capture_for(fixture, "k")
        self.assertEqual((books, provs), ({}, []))
        self.assertIn("no kickoff+name-matching", meta["note"])

    def test_api_error_is_soft(self):
        fixture = _fixture(datetime.now(timezone.utc) + timedelta(hours=30))
        with patch.object(TOA, "fetch_league_odds",
                          side_effect=TOA.OddsApiError("HTTP 401")):
            books, provs, meta = TOA.capture_for(fixture, "k")
        self.assertEqual((books, provs), ({}, []))
        self.assertIn("401", meta["error"])


class ServiceMergeTest(unittest.TestCase):
    """ESPN (DK) + the-odds-api (B365/PS/WH/BV) -> confidence HIGH."""

    def setUp(self):
        import tempfile
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._tmp = Path(self._tmp_dir.name)
        self.svc = PredictionService(feed_path=self._tmp / "feed.json",
                                     predict_log_path=self._tmp / "log.jsonl")
        self.kick = datetime.now(timezone.utc) + timedelta(hours=30)
        self.fixture = _fixture(self.kick)
        espn_comp = {"odds": [{
            "provider": {"name": "DraftKings"}, "overUnder": 2.5,
            "moneyline": {"home": {"close": {"odds": "-215"}},
                          "away": {"close": {"odds": "+650"}},
                          "draw": {"close": {"odds": "+330"}}},
            "total": {"over": {"close": {"odds": "-115"}},
                      "under": {"close": {"odds": "-105"}}},
        }]}
        self._espnp = patch.object(F, "load_feed", return_value=([self.fixture], None))
        self._espnp.start()
        self.espn_comp = espn_comp
        self._getev = patch.object(F, "get_event",
                                   return_value=(dict(self.fixture), espn_comp))
        self._getev.start()
        self.addCleanup(self._espnp.stop)
        self.addCleanup(self._getev.stop)

    def test_merged_confidence_high(self):
        events = [_toa_event(kickoff=self.kick)]
        with patch.object(TOA, "get_odds_api_key", return_value="k"), \
             patch.object(TOA, "fetch_league_odds",
                          return_value=(events, {"requests_remaining": "487"})):
            status, payload = self.svc.predict_event(self.fixture["event_id"])
        self.assertEqual(status, 200)
        pred = payload["prediction"]
        self.assertEqual(pred["overall_status"], "VALID")
        self.assertEqual(pred["confidence"]["grade"], "HIGH")
        self.assertEqual(pred["ftr"]["method"]["n_books"], 5)
        self.assertIn("B365", payload["books"])
        self.assertTrue(payload["odds_api"]["matched"])
        sources = {p.get("source") for p in payload["providers"]}
        self.assertEqual(sources, {"espn", "the-odds-api"})
        # matrix still reproduces the (now multi-book) devig probabilities
        sm = pred["score_matrix"]
        self.assertEqual(sm["status"], "VALID")
        self.assertAlmostEqual(sm["aggregates"]["home"],
                               pred["ftr"]["probabilities"]["home"], places=6)

    def test_cache_reuse_skips_recapture(self):
        """Repeated clicks within the TTL reuse the capture: one fetch of each
        source, second response served from cache (0 quota spend)."""
        calls = {"get_event": 0, "fetch": 0}
        events = [_toa_event(kickoff=self.kick)]

        def counting_get_event(*a, **kw):
            calls["get_event"] += 1
            return dict(self.fixture), self.espn_comp

        def counting_fetch(*a, **kw):
            calls["fetch"] += 1
            return events, {"requests_remaining": "480"}

        with patch.object(F, "get_event", side_effect=counting_get_event), \
             patch.object(TOA, "get_odds_api_key", return_value="k"), \
             patch.object(TOA, "fetch_league_odds", side_effect=counting_fetch):
            status1, payload1 = self.svc.predict_event(self.fixture["event_id"])
            status2, payload2 = self.svc.predict_event(self.fixture["event_id"])
        self.assertEqual((status1, status2), (200, 200))
        self.assertNotIn("from_cache", payload1)
        self.assertTrue(payload2.get("from_cache"))
        self.assertEqual(calls, {"get_event": 1, "fetch": 1})

    def test_no_key_stays_low(self):
        with patch.object(TOA, "get_odds_api_key", return_value=None):
            status, payload = self.svc.predict_event(self.fixture["event_id"])
        self.assertEqual(status, 200)
        pred = payload["prediction"]
        self.assertEqual(pred["confidence"]["grade"], "LOW")
        self.assertEqual(pred["ftr"]["method"]["n_books"], 1)
        self.assertEqual(payload["prediction_input"]["odds"]["source"],
                         "espn(DraftKings)")


if __name__ == "__main__":
    unittest.main()
