"""DATA-004 unit tests (unittest; the environment has no pytest)."""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lineup_capture.adapters import MockAdapter, build_mock_script
from lineup_capture.models import LineupState
from lineup_capture.pipeline import CaptureWindow
from lineup_capture.storage import SnapshotConflictError, SnapshotStore

TMP = Path("backtest_output/data_004_lineup_capture/tests_tmp")


def utc_ts(offset_s: float) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=offset_s)


def make_state(event_id="E1", source="mock", capture_at=None,
               kickoff=None, xi=None, mock=True, **kw) -> LineupState:
    return LineupState(
        event_id=event_id, match_id=f"epl-{event_id}", season="2026-27",
        kickoff_utc=kickoff or utc_ts(3600),
        home_team="TeamA", away_team="TeamB",
        home_xi=xi or ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10", "A11"],
        away_xi=xi or ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10", "B11"],
        source=source, capture_time=capture_at or utc_ts(-600), mock=mock, **kw)


class TestTimeSafety(unittest.TestCase):
    """1) timestamp boundary, 8) timezone tests."""

    def test_boundary_strict(self):
        kickoff = utc_ts(600)
        s1 = make_state(capture_at=kickoff - timedelta(seconds=1), kickoff=kickoff)
        s2 = make_state(capture_at=kickoff, kickoff=kickoff)
        s3 = make_state(capture_at=kickoff + timedelta(seconds=1), kickoff=kickoff)
        self.assertTrue(s1.time_safe)      # 1s before -> safe (STRICT <)
        self.assertFalse(s2.time_safe)     # exactly at kickoff -> NOT safe
        self.assertFalse(s3.time_safe)     # after -> NOT safe

    def test_naive_datetime_coerced_to_utc(self):
        naive = datetime(2026, 8, 15, 18, 0, 0)  # no tzinfo
        s = make_state(capture_at=naive, kickoff=naive + timedelta(minutes=90))
        self.assertIsNotNone(s.capture_time.tzinfo)
        self.assertEqual(s.capture_time.utcoffset(), timedelta(0))
        self.assertTrue(s.time_safe)

    def test_source_event_time_takes_priority(self):
        kickoff = utc_ts(600)
        s = make_state(capture_at=kickoff + timedelta(hours=2), kickoff=kickoff,
                       source_event_time=kickoff - timedelta(minutes=75))
        # native published_at before kickoff -> safe even though WE captured late
        self.assertEqual(s.information_available_time, s.source_event_time)
        self.assertTrue(s.time_safe)


class TestSnapshotStore(unittest.TestCase):
    """4) immutable snapshot, 5) duplicate snapshot tests."""

    def setUp(self):
        shutil.rmtree(TMP, ignore_errors=True)
        self.store = SnapshotStore(TMP)

    def test_immutable_no_overwrite(self):
        ts = utc_ts(-600)
        p1 = self.store.save_raw_snapshot("E1", "mock", 1, ts, {"a": 1})
        with self.assertRaises(SnapshotConflictError):
            self.store.save_raw_snapshot("E1", "mock", 1, ts, {"a": 2})
        # identical content is idempotent (same path, same bytes)
        p2 = self.store.save_raw_snapshot("E1", "mock", 1, ts, {"a": 1})
        self.assertEqual(p1, p2)

    def test_version_paths_distinct(self):
        ts = utc_ts(-600)
        p1 = self.store.save_raw_snapshot("E1", "mock", 1, ts, {"xi": "v1"})
        p2 = self.store.save_raw_snapshot("E1", "mock", 2, ts, {"xi": "v2"})
        self.assertNotEqual(p1, p2)
        self.assertTrue(p1.exists() and p2.exists())


class TestCaptureWindow(unittest.TestCase):
    """3) lineup change, 5) duplicate snapshot, 6) source error,
    7) postponement tests (loop-level, small poll intervals)."""

    def setUp(self):
        shutil.rmtree(TMP, ignore_errors=True)
        self.store = SnapshotStore(TMP)

    def _run(self, script_event, stop_s=5.0, poll=1, pre=120, post=10):
        script = build_mock_script([script_event])
        adapter = MockAdapter(script)
        event_id = script_event["event_id"]
        window = CaptureWindow(self.store, adapter, event_id,
                               pre_window_min=pre, poll_interval_s=poll,
                               post_window_min=post)
        return window.run(stop_after_s=stop_s)

    def test_lineup_change_creates_new_version(self):
        kickoff = utc_ts(3600)
        spec = {
            "event_id": "E1", "kickoff": kickoff, "home": "TeamA",
            "away": "TeamB",
            "states": [
                {"at_seconds": 0,
                 "home_xi": ["A1"] * 11, "away_xi": ["B1"] * 11},
                {"at_seconds": 1.5,
                 "home_xi": ["A1"] * 10 + ["A9"], "away_xi": ["B1"] * 11},
            ],
        }
        manifest = self._run(spec, stop_s=4.0)
        self.assertEqual(manifest.versions, 2)
        self.assertEqual(manifest.time_safe_versions, 2)
        records = self.store.load_records("E1", "mock")
        self.assertEqual([r.version for r in records], [1, 2])

    def test_duplicate_state_no_new_version(self):
        kickoff = utc_ts(3600)
        spec = {
            "event_id": "E2", "kickoff": kickoff, "home": "TeamA",
            "away": "TeamB",
            "states": [
                {"at_seconds": 0, "home_xi": ["A1"] * 11, "away_xi": ["B1"] * 11},
            ],
        }
        manifest = self._run(spec, stop_s=4.0)
        self.assertEqual(manifest.versions, 1)  # unchanged content -> 1 version

    def test_source_error_safe_degredation(self):
        kickoff = utc_ts(3600)
        spec = {
            "event_id": "E3", "kickoff": kickoff, "home": "TeamA",
            "away": "TeamB",
            "errors": [{"after_seconds": 1, "until_seconds": 2.5,
                        "message": "api down"}],
            "states": [
                {"at_seconds": 3, "home_xi": ["A1"] * 11, "away_xi": ["B1"] * 11},
            ],
        }
        manifest = self._run(spec, stop_s=6.0)
        self.assertGreaterEqual(manifest.failures, 1)   # recorded, not fatal
        self.assertGreaterEqual(manifest.versions, 1)   # recovered afterwards

    def test_postponement_extends_window_and_flags(self):
        kickoff = utc_ts(3600)
        new_kickoff = kickoff + timedelta(minutes=45)
        spec = {
            "event_id": "E4", "kickoff": kickoff, "home": "TeamA",
            "away": "TeamB",
            "kickoff_updates": [{"after_seconds": 2, "kickoff": new_kickoff}],
            "states": [
                {"at_seconds": 1, "home_xi": ["A1"] * 11, "away_xi": ["B1"] * 11},
                {"at_seconds": 5, "home_xi": ["A1"] * 10 + ["A9"],
                 "away_xi": ["B1"] * 11},
            ],
        }
        manifest = self._run(spec, stop_s=8.0)
        self.assertTrue(manifest.kickoff_updated if hasattr(manifest,
                                                            "kickoff_updated")
                        else True)  # kickoff_updated lives on records
        records = self.store.load_records("E1", "mock") if False else \
            self.store.load_records("E4", "mock")
        self.assertTrue(any(r.kickoff_updated for r in records))
        self.assertEqual(len(records), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
