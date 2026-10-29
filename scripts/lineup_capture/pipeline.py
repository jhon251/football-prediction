"""DATA-004: the capture pipeline (polling / snapshot / versioning).

One capture window per event:
  - start at max(kickoff - pre_window, now) or as soon as launched
  - poll every poll_interval seconds
  - whenever the observed lineup CONTENT differs from the last saved version,
    save a NEW immutable snapshot version (never overwrite)
  - capture_time is stamped at poll time; time_safe = available < kickoff
  - pre-kickoff snapshots stop being WRITTEN after kickoff (post-kickoff
    observations are logged with time_safe=False, never promoted)
  - schedule re-polling detects postponement / kickoff changes (window
    extends; old snapshots are preserved; kickoff_updated/postponed flags)
  - source errors are recorded as poll observations (safe degradation),
    the loop retries until the window closes
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from lineup_capture.adapters import ESPNAdapter, MockAdapter
from lineup_capture.models import CaptureManifest, CaptureRecord, LineupState
from lineup_capture.storage import SnapshotConflictError, SnapshotStore


class CaptureWindow:
    """One event's capture lifecycle."""

    def __init__(self, store: SnapshotStore, adapter, event_id: str,
                 pre_window_min: int = 120, poll_interval_s: int = 120,
                 post_window_min: int = 10):
        self.store = store
        self.adapter = adapter
        self.event_id = event_id
        self.pre_window = timedelta(minutes=pre_window_min)
        self.poll_interval = timedelta(seconds=poll_interval_s)
        self.post_window = timedelta(minutes=post_window_min)
        self.kickoff: Optional[datetime] = None
        self.versions: Dict[str, int] = {}  # source -> version counter
        self.polls = 0
        self.failures = 0
        self.postponed = False
        self.kickoff_updated = False

    # ------------------------------------------------------------------
    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _observe(self, outcome: str, state_changed: bool = False,
                 version: Optional[int] = None, error: str = "",
                 kickoff_observed: Optional[datetime] = None) -> None:
        self.store.append_observation({
            "event_id": self.event_id, "source": self.adapter.name,
            "poll_time": self._now().isoformat(), "outcome": outcome,
            "state_changed": state_changed, "version": version,
            "error": error,
            "kickoff_observed": kickoff_observed.isoformat()
            if kickoff_observed else None,
        })

    # ------------------------------------------------------------------
    def _save_version(self, state: LineupState, conflict: bool = False,
                      conflict_note: str = "") -> CaptureRecord:
        ver = self.versions.get(state.source, 0) + 1
        raw_payload = state.model_dump(mode="json")
        raw_path = self.store.save_raw_snapshot(
            self.event_id, state.source, ver, state.capture_time, raw_payload)
        record = CaptureRecord(
            event_id=self.event_id, match_id=state.match_id,
            season=state.season, source=state.source, version=ver,
            state=state, raw_snapshot_path=str(raw_path),
            raw_snapshot_sha256=self.store.sha256(raw_path),
            conflict=conflict, conflict_note=conflict_note,
            kickoff_updated=self.kickoff_updated, postponed=self.postponed,
        )
        self.versions[state.source] = ver
        self.store.append_record(record)
        return record

    # ------------------------------------------------------------------
    def _refresh_kickoff(self) -> None:
        try:
            ev = self.adapter.get_event(self.event_id)
        except Exception as exc:  # noqa: BLE001
            self.failures += 1
            self._observe("source_error", error=f"get_event: {exc}")
            return
        if ev["postponed"]:
            self.postponed = True
        if self.kickoff is not None and ev["kickoff_utc"] != self.kickoff:
            self.kickoff_updated = True
        self.kickoff = ev["kickoff_utc"]

    # ------------------------------------------------------------------
    def run(self, stop_after_s: Optional[float] = None) -> CaptureManifest:
        started = self._now()
        self._refresh_kickoff()
        if self.kickoff is None:
            raise RuntimeError("kickoff unknown - cannot open capture window")
        window_start = max(started, self.kickoff - self.pre_window)
        window_end = self.kickoff + self.post_window

        while True:
            now = self._now()
            if now >= window_end or (stop_after_s and
                                     (now - started).total_seconds() >= stop_after_s):
                break
            if now < window_start:
                time.sleep(min(5.0, (window_start - now).total_seconds()))
                continue
            # periodic schedule refresh (postponement / kickoff change)
            self._refresh_kickoff()
            if self.kickoff is not None and self.kickoff > window_end:
                window_end = self.kickoff + self.post_window  # window extends
            pre_kickoff = now < self.kickoff
            try:
                state = self.adapter.get_lineup(self.event_id)
            except Exception as exc:  # noqa: BLE001
                self.failures += 1
                self._observe("source_error", error=str(exc)[:200])
                time.sleep(min(15.0, self.poll_interval.total_seconds()))
                continue
            self.polls += 1
            if state is None:
                self._observe("no_lineup_yet" if pre_kickoff else "post_kickoff")
                time.sleep(self.poll_interval.total_seconds())
                continue
            last = self.store.load_records(self.event_id, state.source)
            last_state = last[-1].state if last else None
            changed = last_state is None or \
                last_state.content_key() != state.content_key()
            if changed:
                # kickoff has moved since the record was built? re-stamp
                if state.kickoff_utc != self.kickoff:
                    state = state.model_copy(update={"kickoff_utc": self.kickoff})
                record = self._save_version(state)
                self._observe(
                    "lineup_captured" if pre_kickoff else "post_kickoff",
                    state_changed=True, version=record.version,
                    kickoff_observed=self.kickoff)
                if not pre_kickoff:
                    self._observe("post_kickoff", state_changed=False,
                                  version=record.version)
            else:
                self._observe("lineup_captured" if pre_kickoff else "post_kickoff",
                              state_changed=False, version=last[-1].version)
            time.sleep(self.poll_interval.total_seconds())

        return self.finalize()

    # ------------------------------------------------------------------
    def finalize(self) -> CaptureManifest:
        manifest = CaptureManifest(
            event_id=self.event_id,
            match_id=self.store.load_records(self.event_id,
                                             self.adapter.name)[0].match_id
            if self.store.load_records(self.event_id, self.adapter.name) else "",
            season="",
            kickoff_utc=self.kickoff,
            sources=list(self.versions),
            versions=sum(self.versions.values()),
            polls=self.polls, failures=self.failures,
            postponed=self.postponed,
        )
        records = []
        for source in self.versions:
            records.extend(self.store.load_records(self.event_id, source))
        if records:
            manifest.match_id = records[0].match_id
            manifest.season = records[0].season
            manifest.time_safe_versions = sum(1 for r in records if r.time_safe)
            manifest.first_capture_utc = min(r.state.capture_time for r in records)
            manifest.last_capture_utc = max(r.state.capture_time for r in records)
            manifest.conflict = any(r.conflict for r in records)
            if self.kickoff is not None:
                manifest.last_known_pre_kickoff = self.store.last_known_pre_kickoff(
                    self.event_id, self.adapter.name, self.kickoff)
        self.store.write_manifest(manifest)
        return manifest
