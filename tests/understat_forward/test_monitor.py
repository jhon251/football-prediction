# -*- coding: utf-8 -*-
"""G1/P2 regression tests for the read-only forward monitor.

Builds miniature synthetic stores (never touching the production store) and
asserts the monitor's DQ counting, provenance checks, and STOP conditions.
"""
import hashlib
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

NOW = datetime(2026, 9, 13, 6, 0, tzinfo=timezone.utc)


def _rec(mid, kickoff, retrieved, is_result=True, dq="time_safe", xg="1.8",
         namespace="forward", **over):
    r = {
        "match_id": mid, "datetime_utc": kickoff, "is_result": is_result,
        "home_team_understat": "Arsenal", "away_team_understat": "Everton",
        "home_goals": 2 if is_result else None, "away_goals": 1 if is_result else None,
        "home_xg": xg if is_result else None, "away_xg": "0.9" if is_result else None,
        "capture_id": "CAP", "league": "E0", "season": "2026", "season_label": "2026-27",
        "retrieved_at": retrieved, "generated_at": None, "published_at": None,
        "window_status": "in_window" if dq == "time_safe" else "window_late",
        "dq_namespace": namespace, "dq_status": dq,
        "kickoff_join_status": "no_frozen_season",
        "kickoff_utc": None, "kickoff_provider_datetime": kickoff,
    }
    r.update(over)
    return r


class MonitorTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="p2mon_"))
        self.sb = self.tmp / "sandbox"
        self.retrieved = "2026-09-13T04:00:00+00:00"
        self.kickoff = "2026-09-12 19:00:00"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build_store(self, captures, frozen_tmp=None):
        """captures: list of dicts {capture_id, retrieved_at, records:[rec...], raw_bytes}."""
        (self.sb / "raw").mkdir(parents=True, exist_ok=True)
        (self.sb / "norm").mkdir(parents=True, exist_ok=True)
        reg_lines = []
        for c in captures:
            cid = c["capture_id"]
            raw = c.get("raw_bytes") or json.dumps({"dates": []}).encode()
            raw_dir = self.sb / "raw" / "E0" / "2026"
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / f"{cid}.json").write_bytes(raw)
            side = {"capture_id": cid, "league": "E0", "season": "2026",
                    "retrieved_at": c["retrieved_at"], "source_url": "u",
                    "parser_version": "forward_pipeline.py:v1",
                    "raw_sha256": hashlib.sha256(raw).hexdigest(),
                    "window_status": "in_window", "dq_namespace": "forward",
                    "generated_at": c.get("generated_at"), "published_at": None}
            (raw_dir / f"{cid}.sidecar.json").write_text(json.dumps(side), encoding="utf-8")
            norm_dir = self.sb / "norm" / "E0" / "2026"
            norm_dir.mkdir(parents=True, exist_ok=True)
            lines = []
            for r in c["records"]:
                r = dict(r)
                r["capture_id"] = cid
                r["retrieved_at"] = c["retrieved_at"]
                lines.append(json.dumps(r, ensure_ascii=False))
            (norm_dir / f"{cid}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
            reg_lines.append({"capture_id": cid, "prev_capture_id": None, "league": "E0",
                              "season": "2026", "retrieved_at": c["retrieved_at"],
                              "window_status": "in_window", "dq_namespace": "forward",
                              "raw_sha256": hashlib.sha256(raw).hexdigest(),
                              "parser_version": "forward_pipeline.py:v1",
                              "n_matches": len(c["records"]), "n_results":
                                  sum(1 for r in c["records"] if r.get("is_result")),
                              "n_revision_events": 0})
        (self.sb / "registry.jsonl").write_text("\n".join(json.dumps(x) for x in reg_lines) + "\n",
                                                encoding="utf-8")
        (self.sb / "scheduler_state.json").write_text(json.dumps({
            "captured_windows": {}, "revision_rechecks": {}, "stop_flags": [],
            "last_run": NOW.isoformat()}), encoding="utf-8")

    def scan(self):
        return MON.scan(self.sb, now=NOW)


class TestMonitor(MonitorTestBase):
    def test_clean_store_ok_and_time_safe_counted(self):
        self.build_store([{
            "capture_id": "CAP", "retrieved_at": self.retrieved,
            "records": [_rec("M1", self.kickoff, self.retrieved),
                        _rec("U1", "2026-09-20 19:00:00", self.retrieved, is_result=False,
                             dq="upcoming_fixture")]}])
        rep = self.scan()
        self.assertEqual(rep["overall_status"], "OK")
        lg = rep["leagues"]["E0|2026"]
        self.assertEqual(lg["time_safe_distinct"], 1)
        self.assertEqual(lg["upcoming_distinct"], 1)
        self.assertEqual(lg["result_matches_seen"], 1)
        self.assertEqual(lg["gap_to_300_time_safe"], 299)  # 1 time_safe already present
        # strict rule: retrieved_at < next upcoming kickoff -> admissible
        self.assertEqual(lg["valid_forward_sample_vs_next_kickoff"], 1)

    def test_stop_genpub_inferred(self):
        self.build_store([{"capture_id": "CAP", "retrieved_at": self.retrieved,
                           "generated_at": "2026-09-12T21:00:00+00:00",
                           "records": [_rec("M1", self.kickoff, self.retrieved)]}])
        rep = self.scan()
        self.assertIn("GENPUB_INFERRED", [a["code"] for a in rep["anomalies"]["STOP"]])
        self.assertEqual(rep["overall_status"], "STOP")

    def test_stop_retro_in_store(self):
        self.build_store([{"capture_id": "CAP", "retrieved_at": self.retrieved,
                           "records": [_rec("M1", self.kickoff, self.retrieved,
                                            dq="historical_retro")]}])
        rep = self.scan()
        self.assertIn("RETRO_IN_STORE", [a["code"] for a in rep["anomalies"]["STOP"]])

    def test_stop_namespace_contamination(self):
        self.build_store([{"capture_id": "CAP", "retrieved_at": self.retrieved,
                           "records": [_rec("M1", self.kickoff, self.retrieved,
                                            namespace="dq_validation")]}])
        rep = self.scan()
        self.assertIn("NAMESPACE_CONTAMINATION", [a["code"] for a in rep["anomalies"]["STOP"]])

    def test_stop_upcoming_with_result_fields(self):
        self.build_store([{"capture_id": "CAP", "retrieved_at": self.retrieved,
                           "records": [_rec("U1", "2026-09-20 19:00:00", self.retrieved,
                                            is_result=False, dq="upcoming_fixture",
                                            home_xg="1.5")]}])
        rep = self.scan()
        self.assertIn("UPCOMING_WITH_RESULT_FIELDS", [a["code"] for a in rep["anomalies"]["STOP"]])

    def test_stop_time_safe_pre_kickoff_impossible_data(self):
        # a result record retrieved BEFORE its own kickoff = fabricated clock anomaly
        self.build_store([{"capture_id": "CAP", "retrieved_at": "2026-09-12T10:00:00+00:00",
                           "records": [_rec("M1", self.kickoff,
                                            "2026-09-12T10:00:00+00:00")]}])
        rep = self.scan()
        self.assertIn("TIME_SAFE_PRE_KICKOFF", [a["code"] for a in rep["anomalies"]["STOP"]])

    def test_stop_provenance_loss(self):
        self.build_store([{"capture_id": "CAP", "retrieved_at": self.retrieved,
                           "records": [_rec("M1", self.kickoff, self.retrieved)]}])
        # tamper raw bytes AFTER the store is built
        raw = self.sb / "raw" / "E0" / "2026" / "CAP.json"
        raw.write_bytes(b"tampered")
        rep = self.scan()
        self.assertIn("PROVENANCE_LOSS", [a["code"] for a in rep["anomalies"]["STOP"]])

    def test_stop_frozen_drift(self):
        fake = self.tmp / "fake_frozen.jsonl"
        fake.write_text("tampered\n", encoding="utf-8")
        orig_ds, orig_sha = C.FROZEN_DS, C.FROZEN_DS_SHA
        C.FROZEN_DS, C.FROZEN_DS_SHA = fake, "0" * 64
        try:
            self.build_store([{"capture_id": "CAP", "retrieved_at": self.retrieved,
                               "records": [_rec("M1", self.kickoff, self.retrieved)]}])
            rep = self.scan()
        finally:
            C.FROZEN_DS, C.FROZEN_DS_SHA = orig_ds, orig_sha
        self.assertIn("FROZEN_DRIFT", [a["code"] for a in rep["anomalies"]["STOP"]])

    def test_window_late_excluded_from_valid_sample(self):
        self.build_store([{
            "capture_id": "CAP", "retrieved_at": self.retrieved,
            "records": [_rec("M1", self.kickoff, self.retrieved, dq="window_late")]}])
        rep = self.scan()
        lg = rep["leagues"]["E0|2026"]
        self.assertEqual(lg["time_safe_distinct"], 0)
        self.assertEqual(lg["window_late_distinct"], 1)
        self.assertEqual(lg["valid_forward_sample_vs_next_kickoff"], 0)

    def test_admissibility_boundary_respects_retrieved_at(self):
        # retrieved AFTER the next upcoming kickoff -> NOT admissible for that target
        self.build_store([{
            "capture_id": "CAP",
            "retrieved_at": "2026-09-25T10:00:00+00:00",  # after U1 kickoff 09-20
            "records": [_rec("M1", "2026-09-12 19:00:00", "2026-09-25T10:00:00+00:00"),
                        _rec("U1", "2026-09-20 19:00:00", "2026-09-25T10:00:00+00:00",
                             is_result=False, dq="upcoming_fixture")]}])
        rep = self.scan()
        lg = rep["leagues"]["E0|2026"]
        # next upcoming kickoff is 09-20; the 09-25 retrieval is too late for it
        self.assertEqual(lg["valid_forward_sample_vs_next_kickoff"], 0)

    def test_missing_provenance_field(self):
        self.build_store([{"capture_id": "CAP", "retrieved_at": self.retrieved,
                           "records": [_rec("M1", self.kickoff, self.retrieved)]}])
        p = self.sb / "norm" / "E0" / "2026" / "CAP.jsonl"
        r = json.loads(p.read_text(encoding="utf-8").splitlines()[0])
        del r["window_status"]
        p.write_text(json.dumps(r) + "\n", encoding="utf-8")
        rep = self.scan()
        self.assertIn("MISSING_PROVENANCE", [a["code"] for a in rep["anomalies"]["STOP"]])

    def test_scheduler_stalled_is_stop(self):
        self.build_store([{"capture_id": "CAP", "retrieved_at": self.retrieved,
                           "records": [_rec("M1", self.kickoff, self.retrieved)]}])
        (self.sb / "scheduler_state.json").write_text(json.dumps({
            "captured_windows": {}, "revision_rechecks": {}, "stop_flags": [],
            "last_run": (NOW - timedelta(hours=72)).isoformat()}), encoding="utf-8")
        rep = self.scan()
        self.assertIn("SCHEDULER_STALLED", [a["code"] for a in rep["anomalies"]["STOP"]])


if __name__ == "__main__":
    unittest.main()
