"""Historical data schemas (V1.2).

``HistoricalMatch`` is the unified schema every historical source must map
into.  Every pre-match-visible field carries provenance: observations have
``observed_at`` timestamps, odds carry ``odds_timestamp``, lineups carry a
tri-state status.  Post-match fields are structurally separated so the
snapshot builder can never mix them into pre-match features.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from football_simulation.models.base import new_id, utc_now


class LineupTriState:
    CONFIRMED = "confirmed"   # official XI published before kickoff
    PREDICTED = "predicted"   # pre-match media prediction, NOT official
    UNKNOWN = "unknown"       # no reliable pre-match information


class HistoricalOdds(BaseModel):
    """Market odds.  ``odds_timestamp`` is MANDATORY: post-kickoff odds must
    never enter a pre-match snapshot (V1.2 rule #8)."""

    model_config = ConfigDict(extra="forbid")

    home: Optional[float] = None
    draw: Optional[float] = None
    away: Optional[float] = None
    bookmaker: str = ""
    odds_timestamp: Optional[datetime] = None
    kind: str = "closing"  # opening | closing | average

    def implied_probabilities(self) -> Dict[str, float]:
        """Margin-removed implied probabilities (proportional method)."""
        if not (self.home and self.draw and self.away):
            return {}
        inv = {"home": 1.0 / self.home, "draw": 1.0 / self.draw, "away": 1.0 / self.away}
        total = sum(inv.values())
        return {k: v / total for k, v in inv.items()}


class HistoricalGoal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minute: Optional[int] = None
    team: str = ""
    scorer: Optional[str] = None
    own_goal: bool = False
    penalty: bool = False


class HistoricalCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minute: Optional[int] = None
    team: str = ""
    card: str = ""  # yellow | second_yellow | red


class HistoricalEvents(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goals: List[HistoricalGoal] = Field(default_factory=list)
    cards: List[HistoricalCard] = Field(default_factory=list)
    penalties: List[Dict[str, Any]] = Field(default_factory=list)
    own_goals: List[Dict[str, Any]] = Field(default_factory=list)
    substitutions: List[Dict[str, Any]] = Field(default_factory=list)
    complete: bool = False  # False when event-level detail is unavailable


class HistoricalMatch(BaseModel):
    """One real (or synthetic-labeled) football match."""

    model_config = ConfigDict(extra="forbid")

    match_id: str = Field(default_factory=new_id)
    competition: str = "premier_league"
    season: str = ""
    date: datetime  # kickoff
    home_team: str
    away_team: str
    venue: str = ""

    # ---- pre-match observations (all optional; absent = UNKNOWN) ----------
    # structure-only: optional pre-match states provided by richer sources.
    pre_match_states: Dict[str, Any] = Field(default_factory=dict)
    opening_odds: Optional[HistoricalOdds] = None
    closing_odds: Optional[HistoricalOdds] = None
    # Every other odds column is preserved VERBATIM with its time-semantics
    # label (closing-convention vs unknown).  Unknown semantics are never
    # promoted into closing/opening (V1.2 principle 5).
    raw_odds: Dict[str, Any] = Field(default_factory=dict)
    odds_semantics_note: str = ""
    home_lineup_status: str = LineupTriState.UNKNOWN
    away_lineup_status: str = LineupTriState.UNKNOWN
    home_lineup: List[str] = Field(default_factory=list)
    away_lineup: List[str] = Field(default_factory=list)
    lineup_observed_at: Optional[datetime] = None
    referee: Optional[str] = None
    weather: Dict[str, Any] = Field(default_factory=dict)
    injuries_known: List[str] = Field(default_factory=list)

    # ---- result (post-match; never usable by pre-match features) -----------
    home_goals: int = 0
    away_goals: int = 0
    half_time_home_goals: int = 0
    half_time_away_goals: int = 0
    home_shots: Optional[int] = None
    away_shots: Optional[int] = None
    home_shots_on_target: Optional[int] = None
    away_shots_on_target: Optional[int] = None
    home_fouls: Optional[int] = None
    away_fouls: Optional[int] = None
    home_corners: Optional[int] = None
    away_corners: Optional[int] = None
    home_yellow_cards: Optional[int] = None
    away_yellow_cards: Optional[int] = None
    home_red_cards: Optional[int] = None
    away_red_cards: Optional[int] = None
    events: HistoricalEvents = Field(default_factory=HistoricalEvents)

    # ---- provenance ----------------------------------------------------------
    source: str = ""
    is_synthetic: bool = Field(
        default=False,
        description="True ONLY for the clearly-labeled development stand-in dataset.",
    )
    observed_at: datetime = Field(default_factory=utc_now)

    # ------------------------------------------------------------------
    def result(self) -> str:
        if self.home_goals > self.away_goals:
            return "home_win"
        if self.home_goals < self.away_goals:
            return "away_win"
        return "draw"

    def total_goals(self) -> int:
        return self.home_goals + self.away_goals

    def btts(self) -> bool:
        return self.home_goals > 0 and self.away_goals > 0


class HistoricalPreMatchSnapshot(BaseModel):
    """PreMatchFreeze 2.0: everything the system may know at T < kickoff.

    The snapshot builder enforces ``observed_at < kickoff`` for EVERY entry;
    anything later is REJECTED (never silently dropped).
    """

    model_config = ConfigDict(extra="forbid")

    match_id: str
    kickoff: datetime
    built_at: datetime = Field(default_factory=utc_now)

    home_team: str
    away_team: str

    # derived walk-forward features (computed ONLY from matches before kickoff)
    team_features: Dict[str, Any] = Field(default_factory=dict)

    # direct observations with timestamps
    odds: Optional[HistoricalOdds] = None
    home_lineup_status: str = LineupTriState.UNKNOWN
    away_lineup_status: str = LineupTriState.UNKNOWN
    home_lineup: List[str] = Field(default_factory=list)
    away_lineup: List[str] = Field(default_factory=list)
    referee: Optional[str] = None
    weather: Dict[str, Any] = Field(default_factory=dict)

    # honesty bookkeeping
    unknowns: List[str] = Field(default_factory=list)
    no_signal: List[str] = Field(default_factory=list)

    # rejection log for temporal-integrity debugging
    rejected_observations: List[Dict[str, Any]] = Field(default_factory=list)
