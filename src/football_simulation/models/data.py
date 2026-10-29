"""Data-layer models: match history, weather, odds, actual results.

These are *raw data* types - everything downstream (agents) consumes them via
the Data Provider interface, never via files or database tables directly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from football_simulation.models.base import utc_now


class MatchHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: datetime
    opponent: str
    home: bool = True
    goals_for: int = 0
    goals_against: int = 0
    xg_for: Optional[float] = None
    xg_against: Optional[float] = None
    competition: str = ""


class MatchHistory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: str
    competition_id: str = ""
    season: str = ""
    entries: List[MatchHistoryEntry] = Field(default_factory=list)
    complete: bool = True


class WeatherData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match_id: str = ""
    venue: str = ""
    temperature_c: Optional[float] = None
    humidity: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    rain: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    wind: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    pitch_condition: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    altitude_m: Optional[float] = None
    forecast_at: Optional[datetime] = Field(default_factory=utc_now)
    known: bool = True


class OddsData(BaseModel):
    """Optional market signal.  Purely an *evidence source*, never the core."""

    model_config = ConfigDict(extra="forbid")

    match_id: str = ""
    home_win: Optional[float] = None
    draw: Optional[float] = None
    away_win: Optional[float] = None
    over_under_line: Optional[float] = None
    as_of: Optional[datetime] = Field(default_factory=utc_now)
    bookmaker: str = ""


class ActualMatchResult(BaseModel):
    """Post-match ground truth (only usable by Learning/Evaluation agents)."""

    model_config = ConfigDict(extra="forbid")

    match_id: str
    kickoff: datetime
    score_home: int
    score_away: int
    ht_score_home: int
    ht_score_away: int
    xg_home: Optional[float] = None
    xg_away: Optional[float] = None
    possession_home: Optional[float] = None
    shots_home: int = 0
    shots_away: int = 0
    shots_on_target_home: int = 0
    shots_on_target_away: int = 0
    corners_home: int = 0
    corners_away: int = 0
    fouls_home: int = 0
    fouls_away: int = 0
    yellow_cards_home: int = 0
    yellow_cards_away: int = 0
    red_cards_home: int = 0
    red_cards_away: int = 0
    events: List[Dict[str, Any]] = Field(default_factory=list)
    home_formation: str = ""
    away_formation: str = ""
    home_pressing_style: str = ""
    away_pressing_style: str = ""
    home_starters: List[str] = Field(default_factory=list)
    away_starters: List[str] = Field(default_factory=list)
    available: bool = False


class DataQualityInfo(BaseModel):
    """Aggregated data completeness signals used by the Confidence Agent."""

    model_config = ConfigDict(extra="forbid")

    completeness: float = Field(default=0.0, ge=0.0, le=1.0)
    unknowns: List[str] = Field(default_factory=list)
    lineup_confirmed: Dict[str, bool] = Field(default_factory=dict)
    notes: List[str] = Field(default_factory=list)
