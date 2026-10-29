"""P0-2 integration test for supervisor_launcher.ps1 detachment.

Scenario: a console owner (here: a wrapper powershell) starts the supervisor
through the launcher and then dies (the equivalent of Ctrl+C / closing the
console).  The DETACHED supervisor must survive, the single-instance guard
must refuse a duplicate, and supervisor.stop must shut it down cleanly.

Uses a temp op dir / store / empty feed, so a real production supervisor
and the production capture store are never touched.  All child output is
redirected to files (no stdio pipes), per sandbox constraints.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TMP = ROOT / "backtest_output" / "data_006_launcher_tmp"
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


class TestLauncherDetach(unittest.TestCase):

    def setUp(self):
        shutil.rmtree(TMP, ignore_errors=True)
        self.op_dir = TMP / "op"
        self.store = TMP / "store"
        self.feed = TMP / "feed.json"
        self.op_dir.mkdir(parents=True)
        self.store.mkdir(parents=True)
        self.feed.write_text('{"fixtures": []}', encoding="utf-8")
        self.wrapper = None

    def tearDown(self):
        try:
            (self.op_dir / "supervisor.stop").write_text("stop", encoding="utf-8")
        except OSError:
            pass
        if self.wrapper is not None and self.wrapper.poll() is None:
            self.wrapper.terminate()
        # brief grace for the supervisor to observe the stop file
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                if supervisor_count(self.op_dir) == 0:
                    break
            except RuntimeError:
                break
            time.sleep(1)
        shutil.rmtree(TMP, ignore_errors=True)

    def test_launcher_detach_guard_and_stop(self):
        # 1) wrapper console owner: runs the launcher, then stays alive so
        #    killing it simulates Ctrl+C / console close.
        wrapper_ps = TMP / "wrapper.ps1"
        wrapper_ps.write_text(
            f"param($Launcher,$OpDir,$Store,$Feed)\n"
            f"& $Launcher -OpDir $OpDir -Store $Store -Feed $Feed -Poll 1\n"
            f"while ($true) {{ Start-Sleep -Seconds 1 }}\n",
            encoding="utf-8")
        with open(TMP / "wrapper_out.txt", "wb") as fh:
            self.wrapper = subprocess.Popen(
                [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", str(wrapper_ps),
                 "-Launcher", str(LAUNCHER),
                 "-OpDir", str(self.op_dir),
                 "-Store", str(self.store),
                 "-Feed", str(self.feed)],
                stdout=fh, stderr=subprocess.STDOUT, cwd=str(ROOT))

        # 2) supervisor comes up (lock + heartbeat written)
        hb = self.op_dir / "supervisor_heartbeat.json"
        deadline = time.time() + 60
        while time.time() < deadline and not hb.exists():
            time.sleep(0.5)
        self.assertTrue(hb.exists(), "supervisor heartbeat never appeared")
        lock = self.op_dir / "supervisor.lock"
        self.assertTrue(lock.exists(), "supervisor lock file never appeared")

        # 3) kill the console owner; the detached supervisor must survive
        self.wrapper.terminate()
        self.wrapper.wait(timeout=30)
        time.sleep(3)
        self.assertEqual(supervisor_count(self.op_dir), 1,
                         "supervisor did not survive its console owner's death")

        # 4) heartbeat still advancing (supervisor truly alive, not a zombie)
        def hb_ts():
            return json.loads(hb.read_text(encoding="utf-8"))["timestamp"]
        t1 = hb_ts()
        deadline = time.time() + 15
        while time.time() < deadline and hb_ts() == t1:
            time.sleep(1)
        self.assertNotEqual(t1, hb_ts(), "heartbeat stopped updating")

        # 5) single-instance guard: second launch exits without a duplicate
        guard_out = TMP / "guard_out.txt"
        rc = run_ps(["-File", str(LAUNCHER),
                     "-OpDir", str(self.op_dir),
                     "-Store", str(self.store),
                     "-Feed", str(self.feed)], guard_out)
        self.assertEqual(rc, 0)
        self.assertIn("already running",
                      guard_out.read_text(encoding="utf-8",
                                          errors="replace"))
        self.assertEqual(supervisor_count(self.op_dir), 1)

        # 6) graceful stop via supervisor.stop
        (self.op_dir / "supervisor.stop").write_text("stop", encoding="utf-8")
        deadline = time.time() + 60
        while time.time() < deadline and supervisor_count(self.op_dir) > 0:
            time.sleep(1)
        self.assertEqual(supervisor_count(self.op_dir), 0,
                         "supervisor did not stop on supervisor.stop")
        audit = (self.op_dir / "supervisor_audit.log").read_text(
            encoding="utf-8", errors="replace")
        self.assertIn("SUPERVISOR_STOP", audit)


if __name__ == "__main__":
    unittest.main(verbosity=2)
