# -*- coding: utf-8 -*-
"""G1 regression tests for the Understat forward scheduler.

All tests run against a DISPOSABLE sandbox store with an injected fake fetch
(offline). The production forward store is only ever READ to assert it stays
untouched. No real match or timestamp is fabricated into production.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

PHASE = Path(__file__).resolve().parents[2] / "backtest_output" / "experiments" / \
    "phase5_3_p1_understat_forward"
sys.path.insert(0, str(PHASE))

from forward_pipeline import config as C          # noqa: E402
from forward_pipeline import pipeline as P        # noqa: E402
from forward_pipeline import scheduler as S       # noqa: E402

PROD_RUNS = PHASE / "data" / "scheduler_runs.jsonl"

KICKOFF = "2026-09-13 01:00:00"  # provider naive dt (treated as UTC, documented caveat)
NOW_BASE = datetime(2026, 9, 13, 4, 0, tzinfo=timezone.utc)
NOW_LATE = (datetime.strptime(KICKOFF, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            + timedelta(hours=2 + 30))          # window closed -> window_late path
NOW_IN = (datetime.strptime(KICKOFF, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
          + timedelta(hours=2 + 4))             # inside T+3..T+6h -> time_safe path


def _payload(kickoff_str, n_results=2, n_upcoming=1):
    dates = []
    for i in range(n_results):
        dates.append({"id": f"M{i}", "datetime": kickoff_str, "isResult": True,
                      "h": {"title": "Arsenal"}, "a": {"title": "Everton"},
                      "goals": {"h": 2, "a": 1}, "xG": {"h": "1.8", "a": "0.7"}})
    for i in range(n_upcoming):
        dates.append({"id": f"U{i}",
                      "datetime": (datetime.strptime(kickoff_str, "%Y-%m-%d %H:%M:%S")
                                   + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"),
                      "isResult": False,
                      "h": {"title": "Chelsea"}, "a": {"title": "Leeds"},
                      "goals": {"h": None, "a": None}, "xG": {"h": "0", "a": "0"}})
    return json.dumps({"dates": dates}).encode("utf-8")


class SchedulerTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="g1sched_"))
        self.sb = self.tmp / "sandbox"
        self.sb.mkdir()
        self.now = NOW_BASE
        self.kickoff = KICKOFF
        self.raw = _payload(self.kickoff)
        self.fetches = []
        self._orig_fetch = P.fetch
        P.fetch = lambda league, season: (self.fetches.append((league, season)) or self.raw)
        self._prod_runs_before = (PROD_RUNS.read_text(encoding="utf-8").count("\n")
                                  if PROD_RUNS.exists() else 0)

    def tearDown(self):
        P.fetch = self._orig_fetch
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.prod_runs_unchanged()

    def prod_runs_unchanged(self):
        """Append-only guard: the live daemon legitimately APPENDS entries while
        tests run; a test bug would TRUNCATE/rewrite the log (count shrinking)."""
        after = (PROD_RUNS.read_text(encoding="utf-8").count("\n")
                 if PROD_RUNS.exists() else 0)
        self.assertGreaterEqual(after, self._prod_runs_before,
                                "production scheduler_runs.jsonl shrank — append-only violated")

    def actions(self):
        out = []
        runs = self.sb / "scheduler_runs.jsonl"
        if runs.exists():
            for line in runs.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    out.append(json.loads(line))
        return out

    def league_actions(self, league="E0"):
        return [e["action"] for e in self.actions() if e.get("league") == league]

    def norm_dq(self, league="E0"):
        d = self.sb / "norm" / league / "2026"
        if not d.exists():
            return {}
        counts = {}
        for f in d.glob("*.jsonl"):
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    counts[r["dq_status"]] = counts.get(r["dq_status"], 0) + 1
        return counts

    def recheck_actions(self):
        return [e for e in self.actions()
                if str(e.get("action", "")).startswith("revision_recheck")
                and "failed" not in e["action"]]


class TestCycleBasics(SchedulerTestBase):
    def test_t1_per_store_logs_production_untouched(self):
        S.one_cycle(now=NOW_LATE, store=self.sb)
        self.assertTrue((self.sb / "scheduler_state.json").exists())
        self.assertTrue((self.sb / "scheduler_runs.jsonl").exists())
        self.assertTrue((self.sb / "registry.jsonl").exists())

    def test_t2_idempotent_rerun(self):
        S.one_cycle(now=NOW_LATE, store=self.sb)
        n_reg1 = sum(1 for l in (self.sb / "registry.jsonl").read_text().splitlines() if l.strip())
        S.one_cycle(now=NOW_LATE + timedelta(minutes=10), store=self.sb)
        n_reg2 = sum(1 for l in (self.sb / "registry.jsonl").read_text().splitlines() if l.strip())
        self.assertEqual(n_reg1, n_reg2, "second identical cycle must not capture again")
        self.assertIn("skip_dup", self.league_actions()[1:])

    def test_t3_in_window_capture_is_time_safe(self):
        S.one_cycle(now=NOW_IN, store=self.sb)
        self.assertIn("captured_in_window", self.league_actions())
        dq = self.norm_dq()
        self.assertEqual(dq.get("time_safe"), 2)
        self.assertEqual(dq.get("upcoming_fixture"), 1)

    def test_t4_window_late_never_time_safe(self):
        S.one_cycle(now=NOW_LATE, store=self.sb)
        self.assertIn("captured_late", self.league_actions())
        self.assertNotIn("captured_in_window", self.league_actions())
        dq = self.norm_dq()
        self.assertEqual(dq.get("window_late"), 2)
        self.assertNotIn("time_safe", dq)

    def test_t5_forward_namespace_rejects_retro_injection(self):
        with self.assertRaises(RuntimeError):
            P.capture("E0", "2020", self.raw, self.now, self.sb, dq_namespace="forward")

    def test_t14_raw_sha256_sidecar_registry_consistent(self):
        S.one_cycle(now=NOW_LATE, store=self.sb)
        reg = [json.loads(l) for l in (self.sb / "registry.jsonl").read_text().splitlines()
               if l.strip()]
        for e in reg:
            raw = self.sb / "raw" / e["league"] / e["season"] / f"{e['capture_id']}.json"
            side = json.loads((self.sb / "raw" / e["league"] / e["season"] /
                               f"{e['capture_id']}.sidecar.json").read_text(encoding="utf-8"))
            self.assertEqual(hashlib.sha256(raw.read_bytes()).hexdigest(), e["raw_sha256"])
            self.assertEqual(side["raw_sha256"], e["raw_sha256"])
            self.assertEqual(side["generated_at"], None)   # never inferred
            self.assertEqual(side["published_at"], None)
            self.assertEqual(side["dq_namespace"], "forward")


class TestFailureModes(SchedulerTestBase):
    def test_t8_fetch_failure_logged_not_silent(self):
        def boom(league, season):
            raise TimeoutError("provider down")
        P.fetch = boom
        S.one_cycle(now=self.now, store=self.sb)
        self.assertEqual([e["action"] for e in self.actions()].count("missing"), len(C.LEAGUES))
        ml = self.sb / "missing" / "missing_log.jsonl"
        self.assertTrue(ml.exists())
        self.assertEqual(len(ml.read_text(encoding="utf-8").splitlines()), len(C.LEAGUES))
        self.assertFalse((self.sb / "registry.jsonl").exists(), "no capture on fetch failure")

    def test_t9_schema_drift_sets_stop_flag_no_capture(self):
        P.fetch = lambda league, season: json.dumps({"dates": [{"unexpected": 1}]}).encode()
        S.one_cycle(now=self.now, store=self.sb)
        self.assertEqual([e["action"] for e in self.actions()].count("schema_drift"),
                         len(C.LEAGUES))
        st = json.loads((self.sb / "scheduler_state.json").read_text(encoding="utf-8"))
        self.assertTrue(st["stop_flags"])
        self.assertFalse((self.sb / "registry.jsonl").exists())

    def test_t10_operational_gap_detected(self):
        stale = self.now - timedelta(hours=72)
        (self.sb / "scheduler_state.json").write_text(json.dumps({
            "captured_windows": {}, "revision_rechecks": {}, "stop_flags": [],
            "last_run": stale.isoformat()}), encoding="utf-8")
        S.one_cycle(now=self.now, store=self.sb)
        gaps = [e for e in self.actions() if e["action"] == "operational_gap_detected"]
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["gap_hours"], 72.0)

    def test_t13_every_run_entry_carries_provider_convention(self):
        S.one_cycle(now=NOW_LATE, store=self.sb)
        for e in self.actions():
            self.assertEqual(e.get("provider_dt_convention"), C.PROVIDER_DATETIME_CONVENTION)

    def test_league_failure_does_not_kill_cycle(self):
        def flaky(league, season):
            if league == "La_liga":  # SP1's understat key
                raise TimeoutError("provider down for La Liga")
            return self.raw
        P.fetch = flaky
        S.one_cycle(now=NOW_LATE, store=self.sb)
        self.assertEqual([e for e in self.actions() if e.get("league") == "E0"][0]["action"],
                         "captured_late")
        self.assertEqual([e for e in self.actions() if e.get("league") == "SP1"][0]["action"],
                         "missing")
        self.assertEqual([e for e in self.actions() if e.get("league") == "I1"][0]["action"],
                         "captured_late")

    def test_r6_cycle_error_guarded_and_logged(self):
        orig = S.load_state
        def boom(store):
            raise RuntimeError("corrupted state")
        S.load_state = boom
        try:
            code = S.daemon(poll=0, max_runs=1, store=self.sb)
        finally:
            S.load_state = orig
        self.assertEqual(code, 0, "daemon must survive a cycle exception")
        self.assertEqual([e["action"] for e in self.actions()].count("cycle_error"), 1)


class TestRevisionRechecks(SchedulerTestBase):
    def _seed(self, captured_window, t24, t7d, first_retrieved):
        (self.sb / "scheduler_state.json").write_text(json.dumps({
            "captured_windows": {"E0": captured_window},
            "revision_rechecks": {"E0": {
                "first_retrieved_at": first_retrieved.isoformat(),
                "t24": t24.isoformat(), "t7d": t7d.isoformat()}},
            "stop_flags": [], "last_run": self.now.isoformat()}), encoding="utf-8")

    def test_t6_recheck_runs_once_no_runaway(self):
        # window matches the seeded capture -> skip_dup; overdue recheck executes
        self._seed(self.kickoff, self.now - timedelta(hours=48), self.now - timedelta(hours=48),
                   self.now - timedelta(days=19))
        S.one_cycle(now=self.now, store=self.sb)
        self.assertEqual(len(self.recheck_actions()), 1)
        S.one_cycle(now=self.now + timedelta(minutes=10), store=self.sb)
        self.assertEqual(len(self.recheck_actions()), 1, "checkpoint done -> no runaway repeat")

    def test_t7_overdue_points_labeled_missed(self):
        self._seed(self.kickoff, self.now - timedelta(hours=456), self.now - timedelta(days=8),
                   self.now - timedelta(days=19))
        S.one_cycle(now=self.now, store=self.sb)
        r = self.recheck_actions()[0]
        self.assertEqual(r["scheduled_points_covered"], ["t24", "t7d"])
        self.assertTrue(r["pre_registered_points_missed"]["t24"])
        self.assertTrue(r["pre_registered_points_missed"]["t7d"])
        self.assertGreater(r["t24_latency_hours"], 400)

    def test_recheck_covered_by_same_cycle_capture_no_extra_fetch(self):
        self._seed("2026-08-24 19:00:00", NOW_LATE - timedelta(hours=48),
                   NOW_LATE - timedelta(days=8), NOW_LATE - timedelta(days=19))
        S.one_cycle(now=NOW_LATE, store=self.sb)
        self.assertIn("captured_late", self.league_actions())
        self.assertIn("revision_recheck_covered_by_capture", self.league_actions())
        epl_fetches = sum(1 for lg, _ in self.fetches if lg == "EPL")
        self.assertEqual(epl_fetches, 1, "capture fetch only; recheck covered, no extra fetch")


class TestLock(SchedulerTestBase):
    def test_t11_fresh_lock_blocks_stale_taken_over(self):
        acquired, _ = S.acquire_lock(self.sb, now=self.now, mode="daemon")
        self.assertTrue(acquired)
        acquired2, cur = S.acquire_lock(self.sb, now=self.now + timedelta(minutes=5))
        self.assertFalse(acquired2)
        self.assertEqual(cur["mode"], "daemon")
        acquired3, _ = S.acquire_lock(
            self.sb, now=self.now + timedelta(minutes=C.LOCK_STALE_MINUTES + 5))
        self.assertTrue(acquired3)

    def test_daemon_refuses_when_lock_held(self):
        acquired, _ = S.acquire_lock(self.sb, mode="once")  # real now -> fresh lock
        self.assertTrue(acquired)
        code = S.daemon(poll=1, max_runs=1, store=self.sb)
        self.assertEqual(code, 3)


if __name__ == "__main__":
    unittest.main()
