"""P1-2 watchdog tests: restore / skip-running / stop-file / stale grace.

Each scenario uses its own temp op dir + empty feed, so production state is
never touched.  All child output goes through files (no stdio pipes), per
sandbox constraints.  Real supervisor processes started here are stopped via
supervisor.stop and removed before the test ends.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TMP = ROOT / "backtest_output" / "data_006_watchdog_tmp"
WATCHDOG = ROOT / "scripts" / "lineup_capture" / "watchdog.ps1"
LAUNCHER = ROOT / "scripts" / "lineup_capture" / "supervisor_launcher.ps1"
POWERSHELL = "powershell"


def run_ps(args: list, out: Path) -> int:
    with out.open("wb") as fh:
        proc = subprocess.Popen([POWERSHELL, "-NoProfile", "-ExecutionPolicy",
                                 "Bypass"] + args,
                                stdout=fh, stderr=subprocess.STDOUT,
                                cwd=str(ROOT))
        proc.wait(timeout=120)
        return proc.returncode


def supervisor_count(op_dir: Path) -> int:
    out = TMP / "count_out.txt"
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          "Where-Object { $_.CommandLine -like '*supervisor.py*' -and "
          f"$_.CommandLine -like '*--op-dir {op_dir}*' }} | "
          "Measure-Object | Select-Object -ExpandProperty Count")
    with out.open("wb") as fh:
        r = subprocess.run([POWERSHELL, "-NoProfile", "-Command", ps],
                           stdout=fh, stderr=subprocess.STDOUT, cwd=str(ROOT),
                           timeout=120)
    text = out.read_text(encoding="utf-8", errors="replace").strip()
    if r.returncode != 0 or not text.isdigit():
        raise RuntimeError(f"CIM count failed (rc={r.returncode}): {text[:200]}")
    return int(text)


def wait_for(predicate, timeout_s: float, step: float = 0.5) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return False


class TestWatchdog(unittest.TestCase):

    def setUp(self):
        shutil.rmtree(TMP, ignore_errors=True)
        TMP.mkdir(parents=True)

    def _scenario(self, name):
        op = TMP / name / "op"
        store = TMP / name / "store"
        feed = TMP / name / "feed.json"
        op.mkdir(parents=True)
        store.mkdir(parents=True)
        feed.write_text('{"fixtures": []}', encoding="utf-8")
        return op, store, feed

    def _watchdog_once(self, op, store, feed, poll=1) -> str:
        out = TMP / "wd_out.txt"
        rc = run_ps(["-File", str(WATCHDOG), "-Once",
                     "-OpDir", str(op), "-Store", str(store),
                     "-Feed", str(feed), "-Poll", str(poll)], out)
        text = out.read_text(encoding="utf-8", errors="replace")
        self.assertEqual(rc, 0, f"watchdog -Once rc={rc}: {text}")
        return text

    def _stop_supervisor(self, op):
        (op / "supervisor.stop").write_text("stop", encoding="utf-8")
        wait_for(lambda: supervisor_count(op) == 0, 60, 1)

    def tearDown(self):
        for name in ("restore", "skiprunning", "stopfile", "grace"):
            op = TMP / name / "op"
            if op.exists():
                try:
                    (op / "supervisor.stop").write_text("stop", encoding="utf-8")
                except OSError:
                    pass
        # give supervisors time to observe the stop file, then clean up
        time.sleep(2)
        for name in ("restore", "skiprunning", "stopfile", "grace"):
            op = TMP / name / "op"
            if op.exists():
                try:
                    wait_for(lambda: supervisor_count(op) == 0, 30, 1)
                except RuntimeError:
                    pass
        shutil.rmtree(TMP, ignore_errors=True)

    def test_restore_starts_supervisor(self):
        """No process + no heartbeat + no stop file -> watchdog starts one."""
        op, store, feed = self._scenario("restore")
        text = self._watchdog_once(op, store, feed)
        self.assertIn("ACTION=start", text)
        self.assertTrue(wait_for(lambda: supervisor_count(op) >= 1, 30),
                        "supervisor not started by watchdog")
        self.assertTrue(wait_for(lambda: (op / "supervisor_heartbeat.json")
                                 .exists(), 30),
                        "heartbeat never appeared after watchdog restore")
        self._stop_supervisor(op)
        self.assertEqual(supervisor_count(op), 0)

    def test_skip_when_running_and_fresh(self):
        """Supervisor running with fresh heartbeat -> watchdog does nothing."""
        op, store, feed = self._scenario("skiprunning")
        out = TMP / "launch_out.txt"
        rc = run_ps(["-File", str(LAUNCHER), "-OpDir", str(op),
                     "-Store", str(store), "-Feed", str(feed), "-Poll", "1"],
                    out)
        self.assertEqual(rc, 0, out.read_text(encoding="utf-8",
                                              errors="replace"))
        self.assertTrue(wait_for(lambda: (op / "supervisor_heartbeat.json")
                                 .exists(), 30), "heartbeat never appeared")
        text = self._watchdog_once(op, store, feed)
        self.assertIn("ACTION=skip-running", text)
        self.assertEqual(supervisor_count(op), 1, "watchdog duplicated the "
                         "supervisor despite it being healthy")
        self._stop_supervisor(op)

    def test_skip_when_stop_file_present(self):
        """supervisor.stop freezes the watchdog even with no process."""
        op, store, feed = self._scenario("stopfile")
        (op / "supervisor.stop").write_text("stop", encoding="utf-8")
        text = self._watchdog_once(op, store, feed)
        self.assertIn("ACTION=skip-stopfile", text)
        self.assertEqual(supervisor_count(op), 0,
                         "watchdog started a supervisor despite stop file")
        wd = (op / "watchdog.log").read_text(encoding="utf-8",
                                             errors="replace")
        self.assertIn("manual freeze", wd)

    def test_wait_when_heartbeat_fresh_but_no_process(self):
        """No process but FRESH heartbeat -> grace period, no start."""
        op, store, feed = self._scenario("grace")
        (op / "supervisor_heartbeat.json").write_text(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "jobs": {}, "running": []}), encoding="utf-8")
        text = self._watchdog_once(op, store, feed)
        self.assertIn("ACTION=wait-fresh-heartbeat", text)
        self.assertEqual(supervisor_count(op), 0,
                         "watchdog started during the fresh-heartbeat grace")


if __name__ == "__main__":
    unittest.main(verbosity=2)
