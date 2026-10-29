# -*- coding: utf-8 -*-
"""A3/A4 regression tests: URLError alerting (consecutive missing), fetch retry,
matchday retention metrics + projection. Sandbox-only, offline."""
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

PHASE = Path(__file__).resolve().parents[2] / "backtest_output" / "experiments" / \
    "phase5_3_p1_understat_forward"
sys.path.insert(0, str(PHASE))

from forward_pipeline import config as C        # noqa: E402
from forward_pipeline import monitor as MON     # noqa: E402
from forward_pipeline import pipeline as P      # noqa: E402
from forward_pipeline import scheduler as S     # noqa: E402

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
KICKOFF = "2026-09-29 09:00:00"
NOW_IN = (datetime.strptime(KICKOFF, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
          + timedelta(hours=2 + 4))


def _mk_run(ts, league, action):
    return {"ts": ts, "league": league, "action": action}


def _payload(kickoff_str, n_results=2):
    dates = []
    for i in range(n_results):
        dates.append({"id": f"M{i}", "datetime": kickoff_str, "isResult": True,
                      "h": {"title": "Arsenal"}, "a": {"title": "Everton"},
                      "goals": {"h": 2, "a": 1}, "xG": {"h": "1.8", "a": "0.7"}})
    dates.append({"id": "U0", "datetime": kickoff_str, "isResult": False,
                  "h": {"title": "Chelsea"}, "a": {"title": "Leeds"},
                  "goals": {"h": None, "a": None}, "xG": {"h": "0", "a": "0"}})
    return json.dumps({"dates": dates}).encode("utf-8")


class TestConsecutiveMissing(unittest.TestCase):
    def test_counts_trailing_missing_per_league(self):
        runs = [_mk_run("t1", "E0", "skip_dup"),
                _mk_run("t2", "E0", "missing"), _mk_run("t3", "E0", "missing"),
                _mk_run("t4", "E0", "missing"),
                _mk_run("t2", "SP1", "missing"), _mk_run("t3", "SP1", "missing")]
        c = MON.consecutive_missing_by_league(runs)
        self.assertEqual(c["E0"], 3)
        self.assertEqual(c["SP1"], 2)
        self.assertEqual(c["D1"], 0)

    def test_non_missing_resets_count(self):
        runs = [_mk_run("t1", "E0", "missing"), _mk_run("t2", "E0", "missing"),
                _mk_run("t3", "E0", "skip_dup"), _mk_run("t4", "E0", "missing")]
        self.assertEqual(MON.consecutive_missing_by_league(runs)["E0"], 1)

    def test_monitor_warns_on_3_consecutive(self):
        runs = [_mk_run(f"t{i}", "E0", "missing") for i in range(3)]
        runs += [_mk_run(f"t{i}", "SP1", "skip_dup") for i in range(3)]
        c = MON.consecutive_missing_by_league(runs)
        self.assertGreaterEqual(c["E0"], C.MISSING_WARN_CONSECUTIVE)
        self.assertLess(c["SP1"], C.MISSING_WARN_CONSECUTIVE)

    def test_monitor_stops_only_when_all_leagues_ge_6(self):
        runs = [_mk_run(f"t{i}", lg, "missing")
                for lg in C.LEAGUES for i in range(C.MISSING_STOP_CONSECUTIVE)]
        c = MON.consecutive_missing_by_league(runs)
        self.assertTrue(all(n >= C.MISSING_STOP_CONSECUTIVE for n in c.values()))
        # one league breaking the streak disables the all-league STOP condition
        runs2 = runs + [_mk_run("t_ok", "E0", "skip_dup")]
        c2 = MON.consecutive_missing_by_league(runs2)
        self.assertFalse(all(n >= C.MISSING_STOP_CONSECUTIVE for n in c2.values()))


class TestFetchRetry(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def test_retries_then_succeeds(self):
        flaky = lambda lk, se: (self.calls.append(1) or
                                (json.loads('x') if len(self.calls) < 3 else b"ok"))
        orig = P.fetch
        P.fetch = flaky
        try:
            with unittest.mock.patch.object(S.time, "sleep", lambda s: None):
                self.assertEqual(S.fetch_with_retry("EPL"), b"ok")
        finally:
            P.fetch = orig
        self.assertEqual(len(self.calls), 3)

    def test_exhausts_and_raises(self):
        def boom(lk, se):
            raise TimeoutError("down")
        orig = P.fetch
        P.fetch = boom
        try:
            with unittest.mock.patch.object(S.time, "sleep", lambda s: None):
                with self.assertRaises(TimeoutError):
                    S.fetch_with_retry("EPL")
        finally:
            P.fetch = orig

    def test_missing_reason_records_attempts(self):
        """After exhausted retries the missing-log reason notes the attempt count."""
        def boom(lk, se):
            raise TimeoutError("down")
        orig = P.fetch
        P.fetch = boom
        tmp = Path(tempfile.mkdtemp())
        try:
            with unittest.mock.patch.object(S.time, "sleep", lambda s: None):
                S.one_cycle(now=NOW, store=tmp)
            runs = [json.loads(l) for l in (tmp / "scheduler_runs.jsonl")
                    .read_text(encoding="utf-8").splitlines() if l.strip()]
            missing = [e for e in runs if e.get("action") == "missing"]
            self.assertEqual(len(missing), len(C.LEAGUES))
            mlog = [json.loads(l) for l in (tmp / "missing" / "missing_log.jsonl")
                    .read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual(len(mlog), len(C.LEAGUES))
            for e in mlog:
                self.assertIn(f"after {C.FETCH_RETRIES} attempts", e["reason"])
        finally:
            P.fetch = orig
            shutil.rmtree(tmp, ignore_errors=True)


import unittest.mock  # noqa: E402


class TestRetention(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.sb = self.tmp / "sandbox"
        (self.sb / "raw").mkdir(parents=True)
        (self.sb / "norm").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_capture(self, cid, retrieved, window_status, kickoff, n=2):
        raw = _payload(kickoff, n_results=n)
        d = self.sb / "raw" / "E0" / "2026"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{cid}.json").write_bytes(raw)
        side = {"capture_id": cid, "league": "E0", "season": "2026",
                "retrieved_at": retrieved, "source_url": "u",
                "parser_version": "v1", "raw_sha256": P.sha256_bytes(raw),
                "window_status": window_status, "dq_namespace": "forward",
                "generated_at": None, "published_at": None}
        (d / f"{cid}.sidecar.json").write_text(json.dumps(side), encoding="utf-8")
        nd = self.sb / "norm" / "E0" / "2026"
        nd.mkdir(parents=True, exist_ok=True)
        lines = []
        for i in range(n):
            lines.append(json.dumps({
                "match_id": f"M{i}", "datetime_utc": kickoff, "is_result": True,
                "home_team_understat": "A", "away_team_understat": "B",
                "home_goals": 1, "away_goals": 0, "home_xg": "1.0", "away_xg": "0.5",
                "capture_id": cid, "league": "E0", "season": "2026",
                "season_label": "2026-27", "retrieved_at": retrieved,
                "generated_at": None, "published_at": None,
                "window_status": window_status, "dq_namespace": "forward",
                "dq_status": "time_safe" if window_status == "in_window" else window_status,
                "kickoff_join_status": "no_frozen_season",
                "kickoff_utc": None, "kickoff_provider_datetime": kickoff}))
        (nd / f"{cid}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return raw

    def test_retention_counts_in_window_matchdays(self):
        # matchday 09-29: in_window capture -> retained
        self._write_capture("CAP_IN", NOW_IN.isoformat(), "in_window", KICKOFF)
        # matchday 09-22: only window_late capture -> NOT retained
        self._write_capture("CAP_LATE", (NOW_IN - timedelta(days=7)).isoformat(),
                            "window_late", "2026-09-22 09:00:00")
        (self.sb / "registry.jsonl").write_text("\n".join(json.dumps({
            "capture_id": cid, "prev_capture_id": None, "league": "E0", "season": "2026",
            "retrieved_at": retrieved, "window_status": ws, "dq_namespace": "forward",
            "raw_sha256": P.sha256_bytes(_payload(ko)), "parser_version": "v1",
            "n_matches": 3, "n_results": 2, "n_revision_events": 0})
            for cid, retrieved, ws, ko in [
                ("CAP_IN", NOW_IN.isoformat(), "in_window", KICKOFF),
                ("CAP_LATE", (NOW_IN - timedelta(days=7)).isoformat(), "window_late",
                 "2026-09-22 09:00:00")]) + "\n", encoding="utf-8")
        (self.sb / "scheduler_state.json").write_text(json.dumps({
            "captured_windows": {}, "revision_rechecks": {}, "stop_flags": [],
            "last_run": NOW.isoformat()}), encoding="utf-8")
        rep = MON.scan(self.sb, now=NOW)
        r = rep["retention"]["E0"]
        self.assertEqual(r["matchdays_total"], 2)
        self.assertEqual(r["matchdays_retained"], 1)
        self.assertEqual(r["retention_all_time"], 0.5)
        self.assertEqual(r["retention_last_30d"], 0.5)
        self.assertIsNotNone(r["projected_season_end_time_safe"])
        self.assertIn("not a promise", r["projection_basis"])

    def test_late_capture_inside_window_is_retained(self):
        """A capture whose window_status is in_window but retrieved slightly late
        in the window still counts; retrieved outside the window does not."""
        self._write_capture("CAP_IN", NOW_IN.isoformat(), "in_window", KICKOFF)
        (self.sb / "registry.jsonl").write_text(json.dumps({
            "capture_id": "CAP_IN", "prev_capture_id": None, "league": "E0",
            "season": "2026", "retrieved_at": NOW_IN.isoformat(),
            "window_status": "in_window", "dq_namespace": "forward",
            "raw_sha256": P.sha256_bytes(_payload(KICKOFF)), "parser_version": "v1",
            "n_matches": 3, "n_results": 2, "n_revision_events": 0}) + "\n",
            encoding="utf-8")
        (self.sb / "scheduler_state.json").write_text(json.dumps({
            "captured_windows": {}, "revision_rechecks": {}, "stop_flags": [],
            "last_run": NOW.isoformat()}), encoding="utf-8")
        rep = MON.scan(self.sb, now=NOW)
        self.assertEqual(rep["retention"]["E0"]["matchdays_retained"], 1)


if __name__ == "__main__":
    unittest.main()
