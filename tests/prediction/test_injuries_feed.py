# -*- coding: utf-8 -*-
"""Tests for the API-Football injuries adapter and its P3-compliant wiring
into the service (signals gated, probabilities untouched)."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from football_prediction import injuries_feed as FD  # noqa: E402
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


def _af_fixture(kickoff: datetime, fid: int = 1035000,
                home: str = "Arsenal", away: str = "Everton") -> dict:
    return {"fixture": {"id": fid, "date": kickoff.isoformat(timespec="seconds"),
                        "status": {"short": "NS"}},
            "teams": {"home": {"id": 42, "name": home},
                      "away": {"id": 45, "name": away}}}


def _injury_item(player: str, team: str, reason: str, fid: int = 1035000) -> dict:
    return {"player": {"id": 9, "name": player},
            "team": {"id": 3, "name": team},
            "fixture": {"id": fid},
            "type": "Missing Fixture", "reason": reason}


class MatchFixtureTest(unittest.TestCase):
    def setUp(self):
        self.kick = datetime.now(timezone.utc) + timedelta(hours=30)

    def test_exact_and_tolerance(self):
        fx = _af_fixture(self.kick)
        self.assertIsNotNone(
            FD.match_fixture([fx], "Arsenal", "Everton", self.kick))
        self.assertIsNone(FD.match_fixture(
            [_af_fixture(self.kick + timedelta(minutes=40))],
            "Arsenal", "Everton", self.kick))

    def test_fc_suffix_and_nickname_matched(self):
        fx = _af_fixture(self.kick, home="Liverpool", away="Brighton")
        self.assertIsNotNone(
            FD.match_fixture([fx], "Liverpool FC", "Brighton & Hove Albion",
                             self.kick))
        fx2 = _af_fixture(self.kick, home="Inter Milan", away="Fiorentina")
        self.assertIsNotNone(
            FD.match_fixture([fx2], "Internazionale", "Fiorentina", self.kick))

    def test_wrong_match_rejected(self):
        fx = _af_fixture(self.kick, home="Barcelona", away="Sevilla")
        self.assertIsNone(FD.match_fixture([fx], "Arsenal", "Everton", self.kick))


class CaptureTest(unittest.TestCase):
    def setUp(self):
        self.kick = datetime.now(timezone.utc) + timedelta(hours=30)
        self.fixture = _fixture(self.kick)
        self.fx = _af_fixture(self.kick)
        self.fixtures_resp = {"results": 1, "errors": [], "response": [self.fx]}

    def test_no_key_noop(self):
        signals, intel = FD.capture_injuries(self.fixture, None)
        self.assertEqual(signals, [])
        self.assertFalse(intel["configured"])

    def test_unmapped_league(self):
        signals, intel = FD.capture_injuries(
            _fixture(self.kick, league="xxx.9"), "k")
        self.assertEqual(signals, [])
        self.assertIn("not mapped", intel["note"])

    def test_capture_with_injuries(self):
        inj_resp = {"results": 2, "errors": [], "response": [
            _injury_item("Gabriel Magalhaes", "Arsenal", "Knee Injury"),
            _injury_item("Dominic Calvert-Lewin", "Everton", "Suspension"),
        ]}
        seen = []

        def fake_fetch(path, key, params=None, timeout=20):
            seen.append((path, dict(params or {})))
            if path == "/fixtures":
                # date-only query (free-plan safe): league filter is
                # client-side, so the response mixes leagues
                return {"results": 2, "errors": [], "response": [
                    {**_af_fixture(self.kick),
                     "league": {"id": 39, "name": "Premier League"}},
                    {**_af_fixture(self.kick, home="Santos", away="Bahia"),
                     "league": {"id": 71, "name": "Serie A BR"}},
                ]}
            if path == "/injuries":
                assert params.get("fixture") == 1035000
                return inj_resp
            raise AssertionError(f"unexpected path {path}")

        with patch.object(FD, "_fetch", side_effect=fake_fetch):
            signals, intel = FD.capture_injuries(self.fixture, "k")
        self.assertEqual(intel["count"], 2)
        self.assertEqual(intel["league_id"], 39)
        self.assertEqual(intel["fixture_id"], 1035000)
        self.assertEqual([x["player"] for x in intel["home"]], ["Gabriel Magalhaes"])
        self.assertEqual([x["player"] for x in intel["away"]],
                         ["Dominic Calvert-Lewin"])
        # date-only fixture query, no season/league params (free plan)
        self.assertEqual(seen[0], ("/fixtures",
                                   {"date": self.kick.date().isoformat()}))
        sig = signals[0]
        self.assertEqual(sig["source"], FD.SIGNAL_SOURCE)
        self.assertEqual(sig["namespace"], "forward")
        self.assertEqual(sig["dq_status"], "time_safe")
        self.assertTrue(sig["retrieved_at"])

    def test_capture_dedupes_and_backfills_labels(self):
        inj_resp = {"results": 4, "errors": [], "response": [
            {**_injury_item("Gabriel Magalhaes", "Arsenal", None),
             "type": None},
            {**_injury_item("Gabriel Magalhaes", "Arsenal", None),
             "type": None},                                    # API duplicate
            _injury_item("Dominic Calvert-Lewin", "Everton", "Suspension"),
            {**_injury_item("Mystery Player", "Everton", None),
             "type": None},
        ]}
        def fake_fetch(path, key, params=None, timeout=20):
            if path == "/fixtures":
                return {**self.fixtures_resp,
                        "response": [{**self.fx,
                                      "league": {"id": 39,
                                                 "name": "Premier League"}}]}
            return inj_resp
        with patch.object(FD, "_fetch", side_effect=fake_fetch):
            signals, intel = FD.capture_injuries(self.fixture, "k")
        # duplicate Gabriel collapsed; null type/reason rendered plainly
        self.assertEqual(intel["count"], 3)
        g = intel["home"][0]
        self.assertEqual(g["player"], "Gabriel Magalhaes")
        self.assertEqual(g["type"], "缺阵")
        self.assertEqual(g["reason"], "原因未披露")
        dcl = intel["away"][0]
        self.assertEqual(dcl["type"], "Missing Fixture")  # real value kept
        self.assertEqual(dcl["reason"], "Suspension")

    def test_no_absences_is_quiet_noop(self):
        def fake_fetch(path, key, params=None, timeout=20):
            if path == "/fixtures":
                return {**self.fixtures_resp,
                        "response": [{**self.fx,
                                      "league": {"id": 39,
                                                 "name": "Premier League"}}]}
            return {"results": 0, "errors": [], "response": []}
        with patch.object(FD, "_fetch", side_effect=fake_fetch):
            signals, intel = FD.capture_injuries(self.fixture, "k")
        self.assertEqual(signals, [])
        self.assertIn("no recorded absences", intel["note"])

    def test_no_matching_fixture(self):
        empty = {"results": 1, "errors": [],
                 "response": [{**_af_fixture(self.kick, home="Barcelona",
                                             away="Sevilla"),
                               "league": {"id": 140, "name": "La Liga"}}]}
        with patch.object(FD, "_fetch", return_value=empty):
            signals, intel = FD.capture_injuries(self.fixture, "k")
        self.assertEqual(signals, [])
        self.assertIn("no kickoff+name-matching", intel["note"])

    def test_api_errors_surfaced(self):
        with patch.object(FD, "_fetch",
                          side_effect=FD.InjuriesApiError(
                              "api-football errors: {'token': 'invalid'}")):
            with self.assertRaises(FD.InjuriesApiError):
                FD.capture_injuries(self.fixture, "k")


class ServiceP3Test(unittest.TestCase):
    """Injuries flow in as external signals; probabilities are untouched."""

    def setUp(self):
        import tempfile
        self._tmp_dir = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp_dir.name)
        self.svc = PredictionService(feed_path=tmp / "f.json",
                                     predict_log_path=tmp / "l.jsonl")
        self.kick = datetime.now(timezone.utc) + timedelta(hours=30)
        self.fixture = _fixture(self.kick)
        comp = {"odds": [{
            "provider": {"name": "DraftKings"}, "overUnder": 2.5,
            "moneyline": {"home": {"close": {"odds": "-215"}},
                          "away": {"close": {"odds": "+650"}},
                          "draw": {"close": {"odds": "+330"}}},
            "total": {"over": {"close": {"odds": "-115"}},
                      "under": {"close": {"odds": "-105"}}}}]}
        self.patches = [
            patch.object(F, "load_feed", return_value=([self.fixture], None)),
            patch.object(F, "get_event", return_value=(dict(self.fixture), comp)),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self._tmp_dir.cleanup()

    def _predict(self, injuries_on: bool):
        af_key = "k" if injuries_on else None
        responses = [
            {"results": 1, "errors": [], "response": [
                {**_af_fixture(self.kick),
                 "league": {"id": 39, "name": "Premier League"}}]},  # /fixtures
            {"results": 1, "errors": [],
             "response": [_injury_item("Gabriel", "Arsenal", "Knee Injury")]},
        ]
        with patch.object(FD, "get_key", return_value=af_key), \
             patch.object(FD, "_fetch",
                          side_effect=lambda *a, **kw: responses.pop(0)):
            # force: same-event calls within the cache TTL must not shadow
            # each other when comparing with/without the signal
            return self.svc.predict_event(self.fixture["event_id"], force=True)

    def test_signal_gated_and_probabilities_identical(self):
        status_off, payload_off = self._predict(injuries_on=False)
        status_on, payload_on = self._predict(injuries_on=True)
        self.assertEqual((status_off, status_on), (200, 200))

        probs_off = payload_off["prediction"]["ftr"]["probabilities"]
        probs_on = payload_on["prediction"]["ftr"]["probabilities"]
        self.assertEqual(probs_off, probs_on)  # P3: signal never moves numbers

        signals = payload_on["prediction"]["external_signals"]
        self.assertEqual(signals["overall_status"], "AVAILABLE_NOT_VALIDATED")
        self.assertFalse(signals["signals_used_in_prediction"])
        rec = signals["signals"][0]
        self.assertEqual(rec["status"], "candidate")

        inj = payload_on["injuries"]
        self.assertEqual(inj["count"], 1)
        self.assertEqual(inj["home"][0]["player"], "Gabriel")
        self.assertEqual(len(payload_on["prediction_input"]["external_signals"]), 1)

    def test_api_error_is_soft(self):
        with patch.object(FD, "get_key", return_value="k"), \
             patch.object(FD, "_fetch",
                          side_effect=FD.InjuriesApiError(
                              "api-football errors: {'plan': 'limit exceeded'}")):
            status, payload = self.svc.predict_event(self.fixture["event_id"])
        self.assertEqual(status, 200)
        self.assertIn("limit exceeded", payload["injuries"]["error"])
        self.assertEqual(payload["prediction"]["external_signals"]["overall_status"],
                         "NOT_AVAILABLE")


if __name__ == "__main__":
    unittest.main()
