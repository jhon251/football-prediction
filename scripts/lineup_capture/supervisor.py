"""DATA-006: local long-running capture supervisor.

Fully decoupled from the DeepSeek Harness lifecycle.  A single long-lived
Python process (or Windows Scheduled Task) that:

  - reads the fixtures feed (data/lineups/prospective/fixtures_feed.json,
    refreshed by fixtures_feed.py) and plans one short-lifecycle capture job
    per scheduled fixture: window = kickoff-120min .. kickoff+20min;
  - spawns the UNCHANGED DATA-005 runner (data_005_live_capture.py) as a
    per-match child process whose run-seconds exactly cover the window - the
    runner self-terminates at kickoff+20min;
  - monitors the child: on early death BEFORE kickoff, restarts it (max
    `max_restarts`); NEVER restarts after kickoff and NEVER captures post-
    match data (window_missed is recorded instead);
  - writes a heartbeat, an append-only audit log (every start/stop/restart/
    miss/complete), and a state file for crash recovery;
  - on supervisor restart, resumes unfinished jobs from state - but a job
    whose kickoff passed while the supervisor was down is marked
    window_missed (no post-match capture, no time_safe fabrication).

DATA-005 store structure and time-safety rules are UNCHANGED: the supervisor
only orchestrates the existing runner.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from lineup_capture.fixtures_feed import load_feed  # noqa: E402
from lineup_capture.storage import SnapshotStore  # noqa: E402

DEFAULT_STORE = ROOT / "backtest_output" / "data_005_lineup_live" / "store"
OP_DIR = ROOT / "data" / "lineups" / "prospective" / "supervisor"
RUNNER = ROOT / "scripts" / "data_005_live_capture.py"
PRE_WINDOW_MIN = 120
POST_WINDOW_MIN = 20
POLL_S = 60
ADOPT_TOLERANCE_S = 10  # max |CIM CreationDate - started_at| to adopt a pid


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CaptureJob:
    def __init__(self, event_id: str, league: str, kickoff_utc: datetime):
        self.event_id = event_id
        self.league = league
        self.kickoff_utc = kickoff_utc
        self.status = "pending"  # pending|running|complete|window_missed|failed
        self.restarts = 0
        self.runner_pid: Optional[int] = None
        self.runner_uuid: str = ""  # identity token, survives restarts
        self.started_at: Optional[str] = None
        self.ended_at: Optional[str] = None
        self.last_error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"event_id": self.event_id, "league": self.league,
                "kickoff_utc": self.kickoff_utc.isoformat(),
                "status": self.status, "restarts": self.restarts,
                "runner_pid": self.runner_pid,
                "runner_uuid": self.runner_uuid,
                "started_at": self.started_at,
                "ended_at": self.ended_at, "last_error": self.last_error}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CaptureJob":
        job = cls(d["event_id"], d["league"],
                  datetime.fromisoformat(d["kickoff_utc"]))
        job.status = d["status"]
        job.restarts = d.get("restarts", 0)
        job.runner_pid = d.get("runner_pid")
        job.runner_uuid = d.get("runner_uuid", "")
        job.started_at = d.get("started_at")
        job.ended_at = d.get("ended_at")
        job.last_error = d.get("last_error", "")
        return job


class Supervisor:
    def __init__(self, store_root: Path = DEFAULT_STORE,
                 op_dir: Path = OP_DIR, poll_s: int = POLL_S,
                 pre_window_min: int = PRE_WINDOW_MIN,
                 post_window_min: int = POST_WINDOW_MIN,
                 max_restarts: int = 3,
                 runner_factory=None, feed_loader=None):
        self.store = SnapshotStore(store_root)
        self.store_root = Path(store_root)
        self.op_dir = Path(op_dir)
        self.op_dir.mkdir(parents=True, exist_ok=True)
        self.poll_s = poll_s
        self.pre_window = timedelta(minutes=pre_window_min)
        self.post_window = timedelta(minutes=post_window_min)
        self.max_restarts = max_restarts
        self.runner_factory = runner_factory  # test injection hook
        self.feed_loader = feed_loader or load_feed  # test injection hook
        self.jobs: Dict[str, CaptureJob] = {}
        self.procs: Dict[str, Any] = {}  # event_id -> Popen (runtime only)
        self.load_state()

    # ------------------------------------------------------------------
    def state_path(self) -> Path:
        return self.op_dir / "supervisor_state.json"

    def heartbeat_path(self) -> Path:
        return self.op_dir / "supervisor_heartbeat.json"

    def audit_path(self) -> Path:
        return self.op_dir / "supervisor_audit.log"

    def log_dir(self) -> Path:
        p = self.op_dir / "logs"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def audit(self, action: str, event_id: str, detail: str = "") -> None:
        line = (f"{utc_now().isoformat()} | {action} | {event_id} | {detail}")
        with self.audit_path().open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        print(line, flush=True)

    def load_state(self) -> None:
        if self.state_path().exists():
            data = json.loads(self.state_path().read_text(encoding="utf-8"))
            self.jobs = {k: CaptureJob.from_dict(v)
                         for k, v in data.get("jobs", {}).items()}
        self._adopt_running_jobs()

    def _adopt_running_jobs(self) -> None:
        """P1-1: adopt state's "running" jobs only with verified identity.

        Token (pid+started_at+uuid) must match the state AND the live process
        at that pid must have a CIM CreationDate equal to started_at.  A pid
        that was reused by an unrelated process is REJECTED (no adoption, no
        double-capture, no killing an innocent process).  Jobs whose window is
        already over are left for tick() to finalize.
        """
        now = utc_now()
        for job in self.jobs.values():
            if job.status != "running":
                continue
            if now > job.kickoff_utc + self.post_window:
                continue  # window over: tick() finalizes, nothing to adopt
            tok = self._read_token(job.event_id)
            if not (tok and tok.get("pid") == job.runner_pid
                    and tok.get("started_at") == job.started_at
                    and tok.get("uuid") == job.runner_uuid):
                self._reject_adoption(job,
                                      "token mismatch" if tok else "no token")
                continue
            try:
                created = self._cim_creation_time(job.runner_pid)
            except Exception as exc:  # noqa: BLE001
                self._reject_adoption(job,
                                      f"cim probe error {str(exc)[:60]}")
                continue
            if created is None:
                self._reject_adoption(job, "runner process gone")
                continue
            try:
                started = datetime.fromisoformat(job.started_at or "")
            except ValueError:
                self._reject_adoption(job, "bad started_at in state")
                continue
            if abs((created - started).total_seconds()) > ADOPT_TOLERANCE_S:
                self._reject_adoption(job, "pid reused: creation time mismatch")
                continue
            self.audit("ADOPT", job.event_id, f"pid={job.runner_pid}")

    def save_state(self) -> None:
        self.state_path().write_text(
            json.dumps({"saved_at": utc_now().isoformat(),
                        "jobs": {k: j.to_dict() for k, j in self.jobs.items()}},
                       indent=1), encoding="utf-8")

    def write_heartbeat(self) -> None:
        self.heartbeat_path().write_text(json.dumps({
            "timestamp": utc_now().isoformat(),
            "jobs": {k: j.to_dict() for k, j in self.jobs.items()},
            "running": [k for k, j in self.jobs.items() if j.status == "running"],
        }, indent=1, default=str), encoding="utf-8")

    # ------------------------------------------------------------------
    def plan_jobs(self, fixtures: List[Dict[str, Any]]) -> None:
        for f in fixtures:
            eid = f["event_id"]
            if eid in self.jobs:
                continue
            kickoff = datetime.fromisoformat(
                f["kickoff_utc"].replace("Z", "+00:00"))
            self.jobs[eid] = CaptureJob(eid, f["league"], kickoff)
            self.audit("PLAN", eid, f"kickoff={kickoff.isoformat()} "
                       f"league={f['league']}")

    # ------------------------------------------------------------------
    def _runner_cmd(self, job: CaptureJob) -> List[str]:
        now = utc_now()
        run_seconds = max(
            60.0, (job.kickoff_utc + self.post_window - now).total_seconds())
        return [sys.executable, str(RUNNER),
                "--events", f"{job.event_id}:{job.league}",
                "--run-seconds", str(int(run_seconds)),
                "--poll", str(self.poll_s),
                "--pre-window", str(int(self.pre_window.total_seconds() // 60)),
                "--post-window", str(int(self.post_window.total_seconds() // 60))]

    def _spawn(self, job: CaptureJob) -> None:
        if self.runner_factory is not None:  # test hook
            proc = self.runner_factory(job)
            job.runner_pid = getattr(proc, "pid", None)
            self.procs[job.event_id] = proc
            job.runner_uuid = uuid.uuid4().hex
            job.started_at = utc_now().isoformat()
            job.status = "running"
            self._write_token(job)
            return
        cmd = self._runner_cmd(job)
        log_file = (self.log_dir() / f"{job.event_id}.log").open(
            "ab", buffering=0)
        proc = subprocess.Popen(cmd, cwd=str(ROOT),
                                stdout=log_file, stderr=subprocess.STDOUT)
        self.procs[job.event_id] = proc
        job.runner_pid = proc.pid
        job.runner_uuid = uuid.uuid4().hex
        job.started_at = utc_now().isoformat()
        job.status = "running"
        self._write_token(job)
        self.audit("START", job.event_id,
                   f"pid={proc.pid} uuid={job.runner_uuid[:8]}")

    def _runner_alive(self, job: CaptureJob) -> bool:
        # Prefer the retained Popen handle: poll() is identity-safe and
        # immune to PID reuse.  Jobs adopted across a supervisor restart have
        # no live handle; verify them via CIM pid+CreationDate instead of the
        # unreliable os.kill(pid,0) (cross-session Access Denied).
        proc = self.procs.get(job.event_id)
        if proc is not None and hasattr(proc, "poll"):
            return proc.poll() is None
        if job.runner_pid is None:
            return False
        return self._adopted_alive(job)

    # ------------------------------------------------------------------
    # Runner identity tokens: OP_DIR/runner_tokens/{event_id}.json holds
    # {pid, started_at, uuid} for the CURRENT runner of that event.  Written
    # on spawn, deleted when the runner is finalized/terminated.  Used by
    # adoption (P1-1) and readable by the watchdog (P1-2); never affects the
    # DATA-005 store.
    def tokens_dir(self) -> Path:
        p = self.op_dir / "runner_tokens"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _token_path(self, event_id: str) -> Path:
        return self.tokens_dir() / f"{event_id}.json"

    def _write_token(self, job: CaptureJob) -> None:
        self._token_path(job.event_id).write_text(json.dumps({
            "event_id": job.event_id, "pid": job.runner_pid,
            "started_at": job.started_at, "uuid": job.runner_uuid,
        }, indent=1), encoding="utf-8")

    def _delete_token(self, event_id: str) -> None:
        try:
            self._token_path(event_id).unlink()
        except FileNotFoundError:
            pass

    def _read_token(self, event_id: str) -> Optional[Dict[str, Any]]:
        p = self._token_path(event_id)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None

    def _cim_creation_time(self, pid: int) -> Optional[datetime]:
        """UTC creation time of pid via Win32_Process (None if gone/unknown).

        CIM (not os.kill/OpenProcess) avoids cross-session Access Denied.
        Output goes through a temp FILE, never a stdio pipe (sandbox-safe).
        """
        ps = ("Get-CimInstance Win32_Process -Filter 'ProcessId={}' | "
              "Select-Object -ExpandProperty CreationDate").format(pid)
        fd, tmp_path = tempfile.mkstemp(prefix="cimprobe_", dir=str(self.op_dir))
        os.close(fd)
        try:
            with open(tmp_path, "wb") as fh:
                subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                               stdout=fh, stderr=subprocess.STDOUT,
                               timeout=60, check=False)
            text = Path(tmp_path).read_text(encoding="utf-8",
                                            errors="replace")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        m = re.search(r"(\d{14})\.\d+([+-]\d{3})", text)
        if not m:
            return None
        wall = datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
        offset_min = int(m.group(2)[1:])
        offset = timedelta(minutes=offset_min)
        if m.group(2).startswith("-"):
            offset = -offset
        return wall.replace(tzinfo=timezone.utc) - offset

    def _adopted_alive(self, job: CaptureJob) -> bool:
        """Adopted runner liveness: process exists AND is the same process.

        Fail-closed (assume alive) on query errors: a transient CIM failure
        must not cause a duplicate spawn; the runner self-terminates at
        kickoff+post so a false-alive costs one capture window, a duplicate
        would double-capture.
        """
        try:
            created = self._cim_creation_time(job.runner_pid)
        except Exception:  # noqa: BLE001
            return True
        if created is None:
            return False
        try:
            started = datetime.fromisoformat(job.started_at or "")
        except ValueError:
            return False
        return abs((created - started).total_seconds()) <= ADOPT_TOLERANCE_S

    def _reject_adoption(self, job: CaptureJob, reason: str) -> None:
        self.audit("ADOPT_REJECT", job.event_id, reason)
        job.runner_pid = None
        job.runner_uuid = ""
        if utc_now() >= job.kickoff_utc:
            # NEVER restart after kickoff: keep status "running" so tick()
            # takes the dead-runner branch and marks window_missed (no
            # post-kickoff respawn, no post-match capture).
            job.status = "running"
        else:
            job.status = "pending"  # tick() respawns fresh inside the window

    def _captured_any(self, job: CaptureJob) -> bool:
        # DATA-005 runner writes records with source=adapter.name ("espn")
        return bool(self.store.load_records(job.event_id, "espn"))

    # ------------------------------------------------------------------
    def tick(self) -> None:
        now = utc_now()
        for job in self.jobs.values():
            if job.status in ("complete", "window_missed"):
                continue
            kickoff = job.kickoff_utc
            if now < kickoff - self.pre_window:
                continue  # waiting for the window
            if now > kickoff + self.post_window:
                # window over
                if job.status == "running":
                    job.runner_pid = None
                    job.runner_uuid = ""
                    job.ended_at = utc_now().isoformat()
                self._delete_token(job.event_id)
                captured = self._captured_any(job)
                job.status = "complete" if captured else "window_missed"
                self.audit(job.status.upper(), job.event_id,
                           f"captured={captured}")
                continue
            # inside the window
            if job.status == "pending":
                self._spawn(job)
                continue
            if job.status == "running" and not self._runner_alive(job):
                if now < kickoff and job.restarts < self.max_restarts:
                    job.restarts += 1
                    self.audit("RESTART", job.event_id,
                               f"attempt={job.restarts}")
                    self._delete_token(job.event_id)
                    self._spawn(job)
                else:
                    self._delete_token(job.event_id)
                    job.runner_pid = None
                    job.runner_uuid = ""
                    job.ended_at = utc_now().isoformat()
                    job.status = "window_missed" if now >= kickoff else "failed"
                    self.audit(job.status.upper(), job.event_id,
                               f"restarts={job.restarts} "
                               f"last_error={job.last_error}")
        self.write_heartbeat()
        self.save_state()

    def _shutdown(self, reason: str) -> None:
        """Graceful stop: STOP audit, terminate tracked runners, final state.

        Only runners tracked via a live Popen handle are terminated (identity-
        safe).  Adopted runners (spawned by a previous supervisor instance)
        are left to self-terminate at kickoff+post: terminating them by pid
        would risk killing an unrelated process after PID reuse.
        """
        self.audit("SUPERVISOR_STOP", "-", reason)
        for event_id, proc in list(self.procs.items()):
            try:
                if hasattr(proc, "poll") and proc.poll() is None:
                    proc.terminate()
                    self._delete_token(event_id)
                    self.audit("RUNNER_TERMINATED", event_id,
                               f"pid={getattr(proc, 'pid', '?')}")
            except Exception as exc:  # noqa: BLE001
                self.audit("RUNNER_TERMINATE_ERROR", event_id, str(exc)[:100])
        self.write_heartbeat()
        self.save_state()

    def _stop_requested(self) -> bool:
        return (self.op_dir / "supervisor.stop").exists()

    def run_forever(self, max_runtime_s: Optional[float] = None) -> None:
        started = utc_now()
        self.audit("SUPERVISOR_START", "-", f"pid={os.getpid()}")
        stop_reason = "max_runtime reached"
        try:
            while True:
                try:
                    if self._stop_requested():
                        stop_reason = "stop file requested"
                        break
                    fixtures = self.feed_loader()
                    self.plan_jobs(fixtures)
                    self.tick()
                except KeyboardInterrupt:
                    stop_reason = "KeyboardInterrupt"
                    break
                except Exception as exc:  # noqa: BLE001
                    self.audit("SUPERVISOR_ERROR", "-", str(exc)[:200])
                if max_runtime_s and \
                        (utc_now() - started).total_seconds() >= max_runtime_s:
                    break
                time.sleep(self.poll_s)
        finally:
            self._shutdown(stop_reason)


def acquire_lock(op_dir: Path = OP_DIR) -> Optional[int]:
    """Single-instance guard (lock file + pid-alive check).

    Prevents duplicate supervisors (e.g. logon-startup firing while an
    instance is already running).  A stale lock from a previous boot is
    taken over.  If the recorded pid is somehow reused by another process,
    the caller refuses to start (fail-safe: no duplicate scheduling).
    """
    op_dir = Path(op_dir)
    op_dir.mkdir(parents=True, exist_ok=True)
    lock_path = op_dir / "supervisor.lock"
    if lock_path.exists():
        try:
            old_pid = int(lock_path.read_text(encoding="utf-8").strip())
            os.kill(old_pid, 0)  # alive?
            return None          # another supervisor is running
        except (ValueError, OSError):
            pass                 # stale lock -> take over
    lock_path.write_text(str(os.getpid()), encoding="utf-8")
    return os.getpid()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-forever", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-runtime", type=float, default=None)
    parser.add_argument("--poll", type=int, default=POLL_S)
    parser.add_argument("--max-restarts", type=int, default=3)
    parser.add_argument("--store", default=None)
    parser.add_argument("--feed", default=None,
                        help="fixtures feed JSON override (tests use a temp feed)")
    parser.add_argument("--op-dir", default=None,
                        help="operational dir override (heartbeat/state/audit); "
                             "tests use a temp dir")
    args = parser.parse_args()

    store_root = Path(args.store) if args.store else DEFAULT_STORE
    op_dir = Path(args.op_dir) if args.op_dir else OP_DIR

    if args.run_forever and acquire_lock(op_dir) is None:
        print("another supervisor is running - exiting (no duplicate scheduling)",
              flush=True)
        return

    feed_loader = (lambda: load_feed(Path(args.feed))) if args.feed else None
    sup = Supervisor(store_root=store_root, op_dir=op_dir, poll_s=args.poll,
                     max_restarts=args.max_restarts, feed_loader=feed_loader)
    if args.run_forever:
        sup.run_forever(max_runtime_s=args.max_runtime)
    elif args.once:
        fixtures = load_feed()
        sup.plan_jobs(fixtures)
        sup.tick()
        print(json.dumps({k: j.to_dict() for k, j in sup.jobs.items()},
                         indent=1))
    else:
        raise SystemExit("specify --run-forever or --once")


if __name__ == "__main__":
    main()
