"""DATA-005: prospective LIVE lineup capture runner (real matches only).

Captures starting XIs from REAL upcoming matches (La Liga 2026-27 first;
EPL 2026-27 when it starts) via ESPN, storing immutable raw snapshots (full
ESPN summary JSON) + normalized records + capture logs under
backtest_output/data_005_lineup_live/store/.

Time safety (unchanged from DATA-004):
  information_available_time = source_event_time if present else capture_time
  time_safe = information_available_time < kickoff_time (STRICT)
  ESPN has no native published_at -> time_trust='capture_proxy' (never called
  the official publication time).  First capture after kickoff -> time_safe=
  False, no remediation.  Mock/historical data are never used here.

Usage (bounded runs; resume-safe):
  python scripts/data_005_live_capture.py --events 401882925:esp.1 \
      --run-seconds 500 --poll 30 --pre-window 120 --post-window 15
  python scripts/data_005_live_capture.py --manifest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from lineup_capture.adapters import ESPNAdapter
from lineup_capture.models import CaptureManifest, CaptureRecord, LineupState
from lineup_capture.storage import SnapshotConflictError

OUT_DIR = Path("backtest_output/data_005_lineup_live")
STORE = OUT_DIR / "store"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LiveStore:
    def __init__(self, root: Path = STORE):
        self.root = Path(root)
        for d in ("raw", "normalized", "observations", "manifests"):
            (self.root / d).mkdir(parents=True, exist_ok=True)

    def raw_path(self, event_id: str, version: int, capture_ts: datetime) -> Path:
        stamp = capture_ts.strftime("%Y%m%dT%H%M%S%fZ")
        return self.root / "raw" / event_id / f"{version:03d}_{stamp}.json"

    def save_raw(self, event_id: str, version: int, capture_ts: datetime,
                 payload: dict) -> Path:
        path = self.raw_path(event_id, version, capture_ts)
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                          default=str).encode("utf-8")
        if path.exists() and path.read_bytes() != data:
            raise SnapshotConflictError(f"immutable conflict: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    @staticmethod
    def sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def records(self, event_id: str) -> List[CaptureRecord]:
        path = self.root / "normalized" / f"{event_id}.jsonl"
        if not path.exists():
            return []
        return [CaptureRecord.model_validate(json.loads(line))
                for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def append_record(self, record: CaptureRecord) -> None:
        with (self.root / "normalized" / f"{record.event_id}.jsonl").open(
                "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record.model_dump(mode="json"),
                                ensure_ascii=False) + "\n")

    def observe(self, event_id: str, entry: dict) -> None:
        with (self.root / "observations" / f"{event_id}.jsonl").open(
                "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    def write_manifest(self, manifest: CaptureManifest) -> None:
        (self.root / "manifests" / f"{manifest.event_id}.json").write_text(
            json.dumps(manifest.model_dump(mode="json"), indent=1),
            encoding="utf-8")


class LiveSession:
    def __init__(self, store: LiveStore, adapter: ESPNAdapter,
                 events: List[str], pre_window_min: int = 120,
                 poll_s: int = 30, post_window_min: int = 15):
        self.store = store
        self.adapter = adapter
        self.events = events
        self.pre_window = timedelta(minutes=pre_window_min)
        self.post_window = timedelta(minutes=post_window_min)
        self.poll_s = poll_s
        self.kickoffs: Dict[str, Optional[datetime]] = {e: None for e in events}
        self.versions: Dict[str, int] = {}
        self.polls = {e: 0 for e in events}
        self.failures = {e: 0 for e in events}
        for e in events:
            recs = store.records(e)
            if recs:
                self.versions[e] = recs[-1].version
                self.kickoffs[e] = recs[-1].state.kickoff_utc

    def _window_open(self, event_id: str, now: datetime) -> bool:
        k = self.kickoffs[event_id]
        if k is None:
            return False
        return (k - self.pre_window) <= now <= (k + self.post_window)

    def _poll_event(self, event_id: str, now: datetime) -> None:
        try:
            ev = self.adapter.get_event(event_id)
        except Exception as exc:  # noqa: BLE001
            self.failures[event_id] += 1
            self.store.observe(event_id, {
                "event_id": event_id, "source": self.adapter.name,
                "poll_time": now.isoformat(), "outcome": "source_error",
                "error": str(exc)[:200],
                "kickoff_observed": None})
            return
        kickoff = ev["kickoff_utc"]
        if self.kickoffs[event_id] is not None and kickoff != self.kickoffs[event_id]:
            self.store.observe(event_id, {
                "event_id": event_id, "source": self.adapter.name,
                "poll_time": now.isoformat(), "outcome": "kickoff_changed",
                "kickoff_old": self.kickoffs[event_id].isoformat(),
                "kickoff_new": kickoff.isoformat()})
        self.kickoffs[event_id] = kickoff
        self.polls[event_id] += 1

        if not self._window_open(event_id, now):
            self.store.observe(event_id, {
                "event_id": event_id, "source": self.adapter.name,
                "poll_time": now.isoformat(), "outcome": "outside_window",
                "kickoff_observed": kickoff.isoformat()})
            return
        pre_kickoff = now < kickoff
        try:
            state = self.adapter.get_lineup(event_id)
        except Exception as exc:  # noqa: BLE001
            self.failures[event_id] += 1
            self.store.observe(event_id, {
                "event_id": event_id, "source": self.adapter.name,
                "poll_time": now.isoformat(), "outcome": "source_error",
                "error": str(exc)[:200],
                "kickoff_observed": kickoff.isoformat()})
            return
        if state is None:
            self.store.observe(event_id, {
                "event_id": event_id, "source": self.adapter.name,
                "poll_time": now.isoformat(),
                "outcome": "no_lineup_yet" if pre_kickoff else "post_kickoff_no_lineup",
                "kickoff_observed": kickoff.isoformat()})
            return
        if state.kickoff_utc != kickoff:
            state = state.model_copy(update={"kickoff_utc": kickoff})
        recs = self.store.records(event_id)
        last = recs[-1].state if recs else None
        changed = last is None or last.content_key() != state.content_key()
        if not changed:
            self.store.observe(event_id, {
                "event_id": event_id, "source": self.adapter.name,
                "poll_time": now.isoformat(), "outcome": "lineup_unchanged",
                "version": recs[-1].version,
                "kickoff_observed": kickoff.isoformat()})
            return
        version = self.versions.get(event_id, 0) + 1
        # full ESPN summary as the raw snapshot
        import urllib.request
        req = urllib.request.Request(
            f"{self.adapter.base}/summary?event={event_id}",
            headers=self.adapter.headers)
        with urllib.request.urlopen(req, timeout=40) as resp:
            summary = json.loads(resp.read().decode("utf-8"))
        raw_payload = {"event_id": event_id, "capture_time": now.isoformat(),
                       "league": self.adapter.league,
                       "lineup_state": state.model_dump(mode="json"),
                       "summary": summary}
        raw_path = self.store.save_raw(event_id, version, now, raw_payload)
        prev_hash = self.store.sha256(
            Path(recs[-1].raw_snapshot_path)) if recs else None
        record = CaptureRecord(
            event_id=event_id, match_id=state.match_id, season=state.season,
            league=state.league, source=self.adapter.name, version=version,
            state=state, raw_snapshot_path=str(raw_path),
            raw_snapshot_sha256=self.store.sha256(raw_path),
            previous_snapshot_sha256=prev_hash,
            capture_status=("lineup_captured" if pre_kickoff
                            else "post_kickoff_final_xi"),
        )
        self.versions[event_id] = version
        self.store.append_record(record)
        self.store.observe(event_id, {
            "event_id": event_id, "source": self.adapter.name,
            "poll_time": now.isoformat(),
            "outcome": "lineup_captured" if pre_kickoff else "post_kickoff",
            "version": version, "state_changed": True,
            "time_safe": record.time_safe,
            "capture_time": state.capture_time.isoformat(),
            "information_available_time": state.information_available_time.isoformat(),
            "kickoff_observed": kickoff.isoformat()})

    def run(self, run_seconds: float) -> None:
        deadline = utc_now() + timedelta(seconds=run_seconds)
        print(f"[{utc_now().isoformat()}] session start: {len(self.events)} events, "
              f"run_seconds={run_seconds}, poll={self.poll_s}s", flush=True)
        while utc_now() < deadline:
            now = utc_now()
            for e in self.events:
                self._poll_event(e, now)
            remaining = (deadline - utc_now()).total_seconds()
            if remaining <= 0:
                break
            time.sleep(min(self.poll_s, remaining))
        print(f"[{utc_now().isoformat()}] session end. polls="
              f"{self.polls} failures={self.failures} versions={self.versions}",
              flush=True)

    def finalize(self) -> None:
        for e in self.events:
            recs = self.store.records(e)
            manifest = CaptureManifest(
                event_id=e,
                match_id=recs[0].match_id if recs else "",
                season=recs[0].season if recs else "",
                kickoff_utc=self.kickoffs[e],
                sources=[self.adapter.name] if recs else [],
                versions=len(recs),
                polls=self.polls[e], failures=self.failures[e],
                time_safe_versions=sum(1 for r in recs if r.time_safe),
                first_capture_utc=min((r.state.capture_time for r in recs),
                                      default=None),
                last_capture_utc=max((r.state.capture_time for r in recs),
                                     default=None),
            )
            if recs and self.kickoffs[e] is not None:
                last = None
                for r in recs:
                    if r.state.capture_time < self.kickoffs[e]:
                        last = r.state
                manifest.last_known_pre_kickoff = last
            self.store.write_manifest(manifest)
            print(f"- {e}: versions={len(recs)} "
                  f"time_safe={manifest.time_safe_versions} "
                  f"polls={self.polls[e]} failures={self.failures[e]} "
                  f"kickoff={self.kickoffs[e]}", flush=True)


def build_overall_manifest() -> dict:
    store = LiveStore()
    manifests = []
    for p in sorted((STORE / "manifests").glob("*.json")):
        manifests.append(CaptureManifest.model_validate(json.loads(p.read_text(encoding="utf-8"))))
    all_records = []
    for p in sorted((STORE / "normalized").glob("*.jsonl")):
        all_records.extend(store.records(p.stem))
    total = len(all_records)
    time_safe = sum(1 for r in all_records if r.time_safe)
    digest = hashlib.sha256()
    for p in sorted(STORE.rglob("*")):
        if p.is_file():
            digest.update(str(p.relative_to(STORE)).encode("utf-8"))
            digest.update(p.read_bytes())
    overall = {
        "real_matches": len(manifests),
        "total_versions": total,
        "time_safe_versions": time_safe,
        "time_safe_rate": round(time_safe / total, 4) if total else None,
        "store_fingerprint": digest.hexdigest(),
        "note": ("REAL-WORLD captures only; mock and historical data are never "
                 "included. time_safe requires information_available_time < "
                 "kickoff (capture-proxy for ESPN)."),
    }
    (OUT_DIR / "MANIFEST.json").write_text(json.dumps(overall, indent=1),
                                           encoding="utf-8")
    print(json.dumps(overall, indent=1))
    return overall


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", default="", help="comma list event_id:league")
    parser.add_argument("--run-seconds", type=float, default=480.0)
    parser.add_argument("--poll", type=int, default=30)
    parser.add_argument("--pre-window", type=int, default=120)
    parser.add_argument("--post-window", type=int, default=15)
    parser.add_argument("--manifest", action="store_true")
    args = parser.parse_args()
    if args.manifest:
        build_overall_manifest()
        return
    if not args.events:
        raise SystemExit("--events required")
    store = LiveStore()
    events = []
    for item in args.events.split(","):
        item = item.strip()
        if ":" in item:
            eid, league = item.split(":")
        else:
            eid, league = item, "esp.1"
        events.append((eid, league))
    adapter = ESPNAdapter(league=events[0][1])
    if len({lg for _, lg in events}) > 1:
        raise SystemExit("one league per session (adapter is league-bound)")
    session = LiveSession(store, adapter, [eid for eid, _ in events],
                          pre_window_min=args.pre_window, poll_s=args.poll,
                          post_window_min=args.post_window)
    session.run(args.run_seconds)
    session.finalize()


if __name__ == "__main__":
    main()
