"""DATA-006 supervisor unit tests (no network, no real spawning)."""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lineup_capture.supervisor import CaptureJob, Supervisor  # noqa: E402

TMP = Path("backtest_output/data_006_supervisor_tests_tmp")


def utc(offset_h: float) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=offset_h)


class FakeProc:
    """Stand-in for a Popen handle: poll()/terminate()/pid, identity-safe."""

    def __init__(self, pid: int, alive: bool = True):
        self.pid = pid
        self._alive = alive
        self.terminated = False

    def poll(self):
        return None if self._alive else 1

    def terminate(self):
        self.terminated = True
        self._alive = False


class FakeRunner:
    """Test hook: records spawns; optionally the Nth spawn dies immediately."""

    def __init__(self, die_after=None):
        self.spawns = []      # event ids, in spawn order
        self.procs = []       # FakeProc objects, in spawn order
        self.die_after = die_after

    def factory(self, job):
        self.spawns.append(job.event_id)
        alive = not (self.die_after is not None
                     and len(self.spawns) > self.die_after)
        proc = FakeProc(pid=10000 + len(self.spawns), alive=alive)
        self.procs.append(proc)
        return proc


class TestSupervisor(unittest.TestCase):

    def setUp(self):
        shutil.rmtree(TMP, ignore_errors=True)
        (TMP / "store").mkdir(parents=True)

    def _sup(self, runner=None, pre_h=2, post_h=1, max_restarts=3):
        return Supervisor(store_root=TMP / "store", op_dir=TMP / "op",
                          poll_s=1, pre_window_min=int(pre_h * 60),
                          post_window_min=int(post_h * 60),
                          max_restarts=max_restarts,
                          runner_factory=runner.factory if runner else None)

    def _feed(self, fixtures):
        (TMP / "feed.json").parent.mkdir(parents=True, exist_ok=True)
        # supervisor reads the fixed feed path; patch via plan_jobs directly
        return fixtures

    def test_window_math(self):
        """Job outside its window is not spawned; inside is."""
        runner = FakeRunner()
        sup = self._sup(runner)
        kickoff = utc(4)  # window opens in ~2h
        job = CaptureJob("E1", "esp.1", kickoff)
        sup.jobs["E1"] = job
        sup.tick()  # now < kickoff-2h -> waiting
        self.assertEqual(job.status, "pending")
        self.assertEqual(runner.spawns, [])
        # simulate inside window: shift kickoff into the past slightly
        job.kickoff_utc = utc(0.5)  # window open (pre 2h, post 1h)
        sup.tick()
        self.assertEqual(job.status, "running")
        self.assertEqual(runner.spawns, ["E1"])

    def test_missed_when_down(self):
        """Kickoff passed while supervisor down -> window_missed, no capture."""
        runner = FakeRunner()
        sup = self._sup(runner)
        job = CaptureJob("E2", "esp.1", utc(-3))  # kickoff 3h ago
        sup.jobs["E2"] = job
        sup.tick()
        self.assertEqual(job.status, "window_missed")
        self.assertEqual(runner.spawns, [])  # never spawned -> no capture

    def test_restart_limit(self):
        """Runner dying pre-kickoff restarts up to max, then failed/missed."""
        runner = FakeRunner(die_after=0)  # every spawn dies immediately
        sup = self._sup(runner, max_restarts=2)
        job = CaptureJob("E3", "esp.1", utc(1))  # inside window (pre 2h)
        sup.jobs["E3"] = job
        for _ in range(5):
            sup.tick()
        self.assertEqual(job.restarts, 2)  # capped at max_restarts
        self.assertEqual(job.status, "failed")  # pre-kickoff, restarts spent

    def test_complete_after_window(self):
        """After kickoff+post, job completes only if store has records."""
        runner = FakeRunner()
        sup = self._sup(runner)
        kickoff = utc(-2)  # window over (post 1h)
        job = CaptureJob("E4", "esp.1", kickoff)
        # simulate a capture happened: store a record
        from lineup_capture.models import LineupState
        from lineup_capture.models import CaptureRecord
        st = LineupState(event_id="E4", match_id="m", season="2026-27",
                         kickoff_utc=kickoff, home_team="A", away_team="B",
                         home_xi=["p"] * 11, away_xi=["q"] * 11,
                         source="espn", capture_time=utc(-3), mock=False)
        rec = CaptureRecord(event_id="E4", match_id="m", season="2026-27",
                            source="espn", version=1, state=st,
                            raw_snapshot_path="x", raw_snapshot_sha256="y")
        sup.store.append_record(rec)
        sup.jobs["E4"] = job
        sup.tick()
        self.assertEqual(job.status, "complete")

    def test_heartbeat_and_audit_written(self):
        runner = FakeRunner()
        sup = self._sup(runner)
        sup.jobs["E5"] = CaptureJob("E5", "esp.1", utc(-3))
        sup.tick()
        self.assertTrue(sup.heartbeat_path().exists())
        self.assertTrue(sup.audit_path().exists())
        hb = json.loads(sup.heartbeat_path().read_text(encoding="utf-8"))
        self.assertIn("timestamp", hb)
        self.assertIn("E5", hb["jobs"])
        audit = sup.audit_path().read_text(encoding="utf-8")
        self.assertIn("window_missed".upper(), audit)

    def test_state_resume(self):
        """State file lets a restarted supervisor resume jobs."""
        runner = FakeRunner()
        sup = self._sup(runner)
        sup.jobs["E6"] = CaptureJob("E6", "esp.1", utc(2))
        sup.tick()
        sup2 = self._sup(runner)  # new instance reloads state
        self.assertIn("E6", sup2.jobs)

    def test_stop_file_graceful_stop(self):
        """supervisor.stop -> SUPERVISOR_STOP audit + tracked runner terminated."""
        runner = FakeRunner()
        sup = self._sup(runner)
        sup.jobs["E7"] = CaptureJob("E7", "esp.1", utc(1))
        sup._spawn(sup.jobs["E7"])  # runner now tracked in sup.procs
        (sup.op_dir / "supervisor.stop").write_text("stop", encoding="utf-8")
        sup.run_forever()  # no max_runtime: stop file breaks the loop
        audit = sup.audit_path().read_text(encoding="utf-8")
        self.assertIn("SUPERVISOR_STOP", audit)
        self.assertIn("stop file requested", audit)
        self.assertIn("RUNNER_TERMINATED", audit)
        self.assertTrue(runner.procs[0].terminated)

    def test_keyboardinterrupt_writes_stop_audit(self):
        """Ctrl+C during run_forever -> clean SUPERVISOR_STOP audit."""
        class RaisingSup(Supervisor):
            def tick(self):
                raise KeyboardInterrupt

        (TMP / "store2").mkdir(parents=True, exist_ok=True)
        sup = RaisingSup(store_root=TMP / "store2", op_dir=TMP / "op2",
                         poll_s=1, feed_loader=lambda: [])
        sup.run_forever()
        audit = sup.audit_path().read_text(encoding="utf-8")
        self.assertIn("SUPERVISOR_START", audit)
        self.assertIn("SUPERVISOR_STOP", audit)
        self.assertIn("KeyboardInterrupt", audit)

    def test_runner_alive_uses_poll_identity(self):
        """Liveness comes from the retained Popen handle (poll), not the pid."""
        runner = FakeRunner()
        sup = self._sup(runner)
        job = CaptureJob("E8", "esp.1", utc(1))
        sup.jobs["E8"] = job
        sup._spawn(job)
        self.assertTrue(sup._runner_alive(job))
        runner.procs[0]._alive = False  # proc died but pid unchanged
        self.assertFalse(sup._runner_alive(job))

    # ------------------------------------------------------------------
    # P1-1: runner identity tokens + CIM pid/CreationDate adoption
    # ------------------------------------------------------------------
    def _write_running_state(self, op, event_id, pid, started_at, uuid,
                             kickoff=None):
        """Plant a state file + token for a 'running' job (as after a crash)."""
        ko = kickoff if kickoff is not None else utc(1)
        op.mkdir(parents=True, exist_ok=True)
        (op / "supervisor_state.json").write_text(json.dumps({
            "saved_at": utc(0).isoformat(),
            "jobs": {event_id: {
                "event_id": event_id, "league": "esp.1",
                "kickoff_utc": ko.isoformat(),
                "status": "running", "restarts": 0,
                "runner_pid": pid, "runner_uuid": uuid,
                "started_at": started_at.isoformat(),
                "ended_at": None, "last_error": ""}}}),
            encoding="utf-8")
        tok_dir = op / "runner_tokens"
        tok_dir.mkdir(parents=True, exist_ok=True)
        (tok_dir / f"{event_id}.json").write_text(json.dumps({
            "event_id": event_id, "pid": pid,
            "started_at": started_at.isoformat(), "uuid": uuid}),
            encoding="utf-8")

    class CimSup(Supervisor):
        """Supervisor whose CIM probe returns a scripted creation time."""

        def __init__(self, probe_time, **kw):
            self.probe_time = probe_time
            super().__init__(**kw)

        def _cim_creation_time(self, pid):
            return self.probe_time

    def test_token_written_and_deleted(self):
        """Spawn writes a token; window finalize deletes it."""
        runner = FakeRunner()
        sup = self._sup(runner)
        job = CaptureJob("T1", "esp.1", utc(1))
        sup.jobs["T1"] = job
        sup._spawn(job)
        tok = json.loads(sup._token_path("T1").read_text(encoding="utf-8"))
        self.assertEqual(tok["pid"], job.runner_pid)
        self.assertEqual(tok["uuid"], job.runner_uuid)
        self.assertEqual(tok["started_at"], job.started_at)
        job.kickoff_utc = utc(-3)  # window over -> finalize
        sup.tick()
        self.assertFalse(sup._token_path("T1").exists())

    def test_adoption_identity_matched(self):
        """Running job with matching token AND CIM creation time is adopted."""
        t = utc(-0.05)
        (TMP / "store_adopt").mkdir(parents=True, exist_ok=True)
        op = TMP / "op_adopt"
        self._write_running_state(op, "A1", 4242, t, "u1")
        sup = self.CimSup(t, store_root=TMP / "store_adopt", op_dir=op,
                          poll_s=1)
        job = sup.jobs["A1"]
        self.assertEqual(job.status, "running")
        self.assertEqual(job.runner_uuid, "u1")
        runner = FakeRunner()
        sup.runner_factory = runner.factory
        sup.tick()  # adopted runner alive via CIM -> NO respawn
        self.assertEqual(runner.spawns, [])
        self.assertIn("ADOPT", sup.audit_path().read_text(encoding="utf-8"))

    def test_adoption_pid_reuse_rejected(self):
        """Same pid but different creation time = reused pid -> rejected."""
        t = utc(-0.05)
        (TMP / "store_reuse").mkdir(parents=True, exist_ok=True)
        op = TMP / "op_reuse"
        self._write_running_state(op, "A2", 4242, t, "u1")
        sup = self.CimSup(t + timedelta(hours=1), store_root=TMP / "store_reuse",
                          op_dir=op, poll_s=1)
        job = sup.jobs["A2"]
        self.assertEqual(job.status, "pending")  # NOT adopted
        self.assertIsNone(job.runner_pid)
        audit = sup.audit_path().read_text(encoding="utf-8")
        self.assertIn("ADOPT_REJECT", audit)
        self.assertIn("pid reused", audit)
        runner = FakeRunner()
        sup.runner_factory = runner.factory
        sup.tick()  # fresh spawn inside the window
        self.assertEqual(runner.spawns, ["A2"])
        tok = json.loads(sup._token_path("A2").read_text(encoding="utf-8"))
        self.assertNotEqual(tok["uuid"], "u1")  # brand-new identity

    def test_adoption_runner_gone_rejected(self):
        """CIM says the process is gone -> no adoption, respawn path."""
        t = utc(-0.05)
        (TMP / "store_gone").mkdir(parents=True, exist_ok=True)
        op = TMP / "op_gone"
        self._write_running_state(op, "A3", 4242, t, "u1")
        sup = self.CimSup(None, store_root=TMP / "store_gone", op_dir=op,
                          poll_s=1)
        self.assertEqual(sup.jobs["A3"].status, "pending")
        audit = sup.audit_path().read_text(encoding="utf-8")
        self.assertIn("runner process gone", audit)

    def test_adopted_runner_alive_via_cim(self):
        """Adopted job (no Popen handle) liveness = CIM creation-time match."""
        t = utc(-0.05)
        (TMP / "store_alive").mkdir(parents=True, exist_ok=True)
        op = TMP / "op_alive"
        self._write_running_state(op, "A4", 4242, t, "u1")
        sup = self.CimSup(t, store_root=TMP / "store_alive", op_dir=op,
                          poll_s=1)
        job = sup.jobs["A4"]
        self.assertTrue(sup._runner_alive(job))
        sup.probe_time = t + timedelta(hours=1)  # pid now belongs to another
        self.assertFalse(sup._runner_alive(job))

    def test_adoption_reject_post_kickoff_no_respawn(self):
        """Post-kickoff adoption failure -> window_missed, NEVER a respawn."""
        t = utc(-0.4)
        (TMP / "store_pko").mkdir(parents=True, exist_ok=True)
        op = TMP / "op_pko"
        self._write_running_state(op, "A5", 4242, t, "u1",
                                  kickoff=utc(-0.2))  # kickoff already passed
        sup = self.CimSup(None, store_root=TMP / "store_pko", op_dir=op,
                          poll_s=1)
        self.assertEqual(sup.jobs["A5"].status, "running")
        runner = FakeRunner()
        sup.runner_factory = runner.factory
        sup.tick()
        self.assertEqual(runner.spawns, [])  # never restart after kickoff
        self.assertEqual(sup.jobs["A5"].status, "window_missed")
        audit = sup.audit_path().read_text(encoding="utf-8")
        self.assertIn("WINDOW_MISSED", audit)


if __name__ == "__main__":
    unittest.main(verbosity=2)
