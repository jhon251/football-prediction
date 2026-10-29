"""DATA-004 CLI: dry-run / verify / fingerprint / live capture loop.

  python scripts/data_004_lineup_capture.py --dry-run
  python scripts/data_004_lineup_capture.py --verify
  python scripts/data_004_lineup_capture.py --fingerprint
  python scripts/data_004_lineup_capture.py --capture-loop --event <espn_event_id>

Dry-run uses ONLY mock data (labeled mock=True) - never presented as real
validation samples.  No live EPL season is running in this environment, so
no real time_safe samples can be produced here.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from lineup_capture.adapters import MockAdapter, build_mock_script
from lineup_capture.pipeline import CaptureWindow
from lineup_capture.storage import SnapshotStore, compute_store_fingerprint

DRY_DIR = Path("backtest_output/data_004_lineup_capture/dryrun")


def utc(offset_min: float) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=offset_min)


def build_dry_script():
    """4 mock events: normal, late change, source outage then recovery,
    postponed/kickoff change."""
    return build_mock_script([
        {
            "event_id": "MOCK-E1", "season": "2026-27", "kickoff": utc(10),
            "home": "TeamAlpha", "away": "TeamBeta",
            "states": [
                {"at_seconds": 0,
                 "home_xi": ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10", "A11"],
                 "away_xi": ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10", "B11"],
                 "home_formation": "4-3-3", "away_formation": "4-4-2"},
                {"at_seconds": 6,   # late pre-kickoff change (warm-up injury)
                 "home_xi": ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10", "A12"],
                 "away_xi": ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10", "B11"],
                 "home_formation": "4-3-3", "away_formation": "4-4-2"},
            ],
        },
        {
            "event_id": "MOCK-E2", "season": "2026-27", "kickoff": utc(15),
            "home": "TeamGamma", "away": "TeamDelta",
            "states": [
                {"at_seconds": 0,
                 "home_xi": ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11"],
                 "away_xi": ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10", "D11"]},
            ],
        },
        {
            "event_id": "MOCK-E3", "season": "2026-27", "kickoff": utc(20),
            "home": "TeamEpsilon", "away": "TeamZeta",
            "errors": [{"after_seconds": 2, "until_seconds": 5,
                        "message": "espn 500"}],
            "states": [
                {"at_seconds": 6,
                 "home_xi": ["E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9", "E10", "E11"],
                 "away_xi": ["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11"]},
            ],
        },
        {
            "event_id": "MOCK-E4", "season": "2026-27", "kickoff": utc(25),
            "home": "TeamEta", "away": "TeamTheta",
            "kickoff_updates": [{"after_seconds": 3,
                                 "kickoff": utc(25) + timedelta(minutes=45)}],
            "states": [
                {"at_seconds": 1,
                 "home_xi": ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G10", "G11"],
                 "away_xi": ["H1", "H2", "H3", "H4", "H5", "H6", "H7", "H8", "H9", "H10", "H11"]},
                {"at_seconds": 7,
                 "home_xi": ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G10", "G12"],
                 "away_xi": ["H1", "H2", "H3", "H4", "H5", "H6", "H7", "H8", "H9", "H10", "H11"]},
            ],
        },
    ])


def dry_run() -> None:
    shutil.rmtree(DRY_DIR, ignore_errors=True)
    store = SnapshotStore(DRY_DIR)
    script = build_dry_script()
    adapter = MockAdapter(script)
    results = {}
    for event_id in ["MOCK-E1", "MOCK-E2", "MOCK-E3", "MOCK-E4"]:
        window = CaptureWindow(store, adapter, event_id,
                               pre_window_min=120, poll_interval_s=2,
                               post_window_min=10)
        manifest = window.run(stop_after_s=12)
        results[event_id] = manifest.model_dump(mode="json")
        last = store.last_known_pre_kickoff(event_id, "mock", manifest.kickoff_utc)
        print(f"{event_id}: versions={manifest.versions} "
              f"time_safe={manifest.time_safe_versions} polls={manifest.polls} "
              f"failures={manifest.failures} postponed={manifest.postponed} "
              f"last_known_pre_kickoff_xi11="
              f"{len(last.home_xi) if last else 'NONE'}")
    (DRY_DIR / "dryrun_results.json").write_text(
        json.dumps({"mock": True,
                    "note": "MOCK data only - NOT real validation samples",
                    "results": results,
                    "store_fingerprint": compute_store_fingerprint(DRY_DIR)},
                   indent=1, default=str), encoding="utf-8")
    print("dry-run DONE (mock only)")


def verify() -> None:
    store = SnapshotStore(DRY_DIR)
    fps = compute_store_fingerprint(DRY_DIR)
    manifests = store.all_manifests()
    print(f"manifests={len(manifests)} store_fingerprint={fps[:16]}")
    for m in manifests:
        records = []
        for source in m.sources:
            records.extend(store.load_records(m.event_id, source))
        safe = [r for r in records if r.time_safe]
        print(f"- {m.event_id}: kickoff={m.kickoff_utc} versions={m.versions} "
              f"time_safe={len(safe)}/{len(records)} "
              f"last_pre_kickoff="
              f"{len(m.last_known_pre_kickoff.home_xi) if m.last_known_pre_kickoff else 0}"
              f"-man")
    # immutability spot check: raw files must equal their sha256 records
    bad = 0
    for m in manifests:
        for source in m.sources:
            for rec in store.load_records(m.event_id, source):
                p = Path(rec.raw_snapshot_path)
                if not p.exists() or store.sha256(p) != rec.raw_snapshot_sha256:
                    bad += 1
                    print(f"  IMMUTABILITY FAIL: {rec.raw_snapshot_path}")
    print(f"immutability check: {'OK' if bad == 0 else f'{bad} FAILURES'}")


def live_capture_loop(event_id: str, pre_window: int, poll: int) -> None:
    """Real capture loop against ESPN.  Requires a live upcoming fixture;
    no live EPL matches exist in this environment, so this is for future
    seasons only."""
    from lineup_capture.adapters import ESPNAdapter
    store = SnapshotStore(Path("data/lineups/prospective"))
    window = CaptureWindow(store, ESPNAdapter(), event_id,
                           pre_window_min=pre_window, poll_interval_s=poll)
    manifest = window.run()
    print(json.dumps(manifest.model_dump(mode="json"), indent=1, default=str))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--fingerprint", action="store_true")
    parser.add_argument("--capture-loop", action="store_true")
    parser.add_argument("--event", default=None)
    parser.add_argument("--pre-window", type=int, default=120)
    parser.add_argument("--poll", type=int, default=120)
    args = parser.parse_args()
    if args.dry_run:
        dry_run()
    elif args.verify:
        verify()
    elif args.fingerprint:
        print(compute_store_fingerprint(DRY_DIR))
    elif args.capture_loop:
        if not args.event:
            raise SystemExit("--capture-loop requires --event <espn_event_id>")
        live_capture_loop(args.event, args.pre_window, args.poll)
    else:
        raise SystemExit("specify --dry-run | --verify | --fingerprint | --capture-loop")


if __name__ == "__main__":
    main()
