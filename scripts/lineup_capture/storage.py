"""DATA-004: immutable snapshot storage + per-event manifest + manifest store.

Immutability contract: a raw snapshot file path is written exactly once; any
attempt to write the same path again with DIFFERENT content raises
SnapshotConflictError.  Never overwrite history.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from lineup_capture.models import CaptureManifest, CaptureRecord, LineupState


class SnapshotConflictError(RuntimeError):
    pass


class SnapshotStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.raw_dir = self.root / "raw"
        self.records_dir = self.root / "records"
        self.observations_dir = self.root / "observations"
        self.manifests_dir = self.root / "manifests"
        for d in (self.raw_dir, self.records_dir, self.observations_dir,
                  self.manifests_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    def _raw_path(self, event_id: str, source: str, version: int,
                  capture_ts: datetime) -> Path:
        stamp = capture_ts.strftime("%Y%m%dT%H%M%S%fZ")
        return self.raw_dir / event_id / f"{version:03d}_{source}_{stamp}.json"

    def save_raw_snapshot(self, event_id: str, source: str, version: int,
                          capture_ts: datetime, payload: dict) -> Path:
        """Immutable write: existing path with different bytes -> error."""
        path = self._raw_path(event_id, source, version, capture_ts)
        if path.exists():
            existing = path.read_bytes()
            new = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                             default=str).encode("utf-8")
            if existing != new:
                raise SnapshotConflictError(
                    f"immutable snapshot conflict: {path}")
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                    default=str).encode("utf-8"))
        return path

    def sha256(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    # ------------------------------------------------------------------
    def record_path(self, event_id: str, source: str) -> Path:
        return self.records_dir / f"{event_id}__{source}.jsonl"

    def append_record(self, record: CaptureRecord) -> None:
        with self.record_path(record.event_id, record.source).open(
                "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record.model_dump(mode="json"),
                                ensure_ascii=False) + "\n")

    def load_records(self, event_id: str, source: str) -> List[CaptureRecord]:
        path = self.record_path(event_id, source)
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(CaptureRecord.model_validate(json.loads(line)))
        return out

    # ------------------------------------------------------------------
    def append_observation(self, obs: dict) -> None:
        with (self.observations_dir / f"{obs['event_id']}.jsonl").open(
                "a", encoding="utf-8") as fh:
            fh.write(json.dumps(obs, ensure_ascii=False, default=str) + "\n")

    def write_manifest(self, manifest: CaptureManifest) -> None:
        (self.manifests_dir / f"{manifest.event_id}.json").write_text(
            json.dumps(manifest.model_dump(mode="json"), indent=1),
            encoding="utf-8")

    def load_manifest(self, event_id: str) -> Optional[CaptureManifest]:
        path = self.manifests_dir / f"{event_id}.json"
        if not path.exists():
            return None
        return CaptureManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def all_manifests(self) -> List[CaptureManifest]:
        out = []
        for p in sorted(self.manifests_dir.glob("*.json")):
            out.append(CaptureManifest.model_validate(json.loads(p.read_text(encoding="utf-8"))))
        return out

    # ------------------------------------------------------------------
    def last_known_pre_kickoff(self, event_id: str, source: str,
                               kickoff: datetime) -> Optional[LineupState]:
        """The last lineup content the system knew BEFORE kickoff (strict)."""
        last: Optional[LineupState] = None
        for rec in self.load_records(event_id, source):
            st = rec.state
            if st.capture_time < kickoff:  # strict
                if last is None or st.capture_time > last.capture_time:
                    last = st
        return last


def compute_store_fingerprint(store_root: Path) -> str:
    """Fingerprint of every raw snapshot + record + manifest file."""
    digest = hashlib.sha256()
    for p in sorted(Path(store_root).rglob("*")):
        if p.is_file():
            digest.update(str(p.relative_to(store_root)).encode("utf-8"))
            digest.update(p.read_bytes())
    return digest.hexdigest()
