"""DATA-004: capture record models (pydantic, all times UTC-aware)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LineupState(BaseModel):
    """The lineup content observed at one point in time for one event+source."""

    event_id: str
    match_id: str
    season: str
    league: str = ""
    kickoff_utc: datetime
    home_team: str
    away_team: str
    home_xi: List[str] = Field(default_factory=list)
    away_xi: List[str] = Field(default_factory=list)
    home_formation: Optional[str] = None
    away_formation: Optional[str] = None
    source: str
    source_event_time: Optional[datetime] = None  # native publication time
    time_trust: str = "unknown"  # native_published_at | capture_proxy | unknown
    capture_time: datetime = Field(default_factory=utc_now)
    mock: bool = False

    @field_validator("kickoff_utc", "source_event_time", "capture_time")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        if v is None:
            return v
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    @property
    def information_available_time(self) -> Optional[datetime]:
        return self.source_event_time or self.capture_time

    @property
    def time_safe(self) -> bool:
        avail = self.information_available_time
        if avail is None:
            return False
        return avail < self.kickoff_utc  # STRICT inequality (boundary test)

    def content_key(self) -> str:
        """Identity of the lineup CONTENT (for change detection)."""
        return "|".join([
            "|".join(self.home_xi), "|".join(self.away_xi),
            str(self.home_formation or ""), str(self.away_formation or ""),
        ])


class CaptureRecord(BaseModel):
    """One immutable snapshot version for an event+source."""

    event_id: str
    match_id: str
    season: str
    league: str = ""
    source: str
    version: int = 1
    state: LineupState
    raw_snapshot_path: str
    raw_snapshot_sha256: str
    previous_snapshot_sha256: Optional[str] = None
    conflict: bool = False
    conflict_note: str = ""
    kickoff_updated: bool = False  # set when the schedule moved the kickoff
    postponed: bool = False
    capture_status: str = "lineup_captured"  # captured | no_lineup | error | post_kickoff

    @property
    def time_safe(self) -> bool:
        return self.state.time_safe


class PollObservation(BaseModel):
    """Every poll outcome (append-only log)."""

    event_id: str
    source: str
    poll_time: datetime = Field(default_factory=utc_now)
    outcome: str  # lineup_captured | no_lineup_yet | source_error | post_kickoff
    state_changed: bool = False
    version: Optional[int] = None
    error: str = ""
    kickoff_observed: Optional[datetime] = None


class CaptureManifest(BaseModel):
    """Per-event capture summary (written after the capture window closes)."""

    event_id: str
    match_id: str
    season: str
    kickoff_utc: Optional[datetime] = None
    sources: List[str] = Field(default_factory=list)
    versions: int = 0
    last_known_pre_kickoff: Optional[LineupState] = None
    first_capture_utc: Optional[datetime] = None
    last_capture_utc: Optional[datetime] = None
    time_safe_versions: int = 0
    polls: int = 0
    failures: int = 0
    postponed: bool = False
    conflict: bool = False
