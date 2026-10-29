"""Event models: match events and the event dependency rules that keep the
simulation physically plausible (no one-minute three-red-card black swans)."""

from __future__ import annotations

import enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from football_simulation.models.base import Side, new_id


class EventType(str, enum.Enum):
    GOAL = "goal"
    BIG_CHANCE = "big_chance"
    SHOT = "shot"
    SHOT_ON_TARGET = "shot_on_target"
    MISS = "miss"
    CORNER = "corner"
    FREE_KICK = "free_kick"
    FOUL = "foul"
    YELLOW_CARD = "yellow_card"
    SECOND_YELLOW = "second_yellow"
    RED_CARD = "red_card"
    PENALTY = "penalty"
    INJURY = "injury"
    SUBSTITUTION = "substitution"
    VAR_REVIEW = "var_review"
    OWN_GOAL = "own_goal"
    GOALKEEPER_ERROR = "goalkeeper_error"
    DEFENSIVE_ERROR = "defensive_error"


class MatchEvent(BaseModel):
    """One event sampled by the Event Trigger Agent / Event Engine."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=new_id)
    match_id: str = ""
    minute: int
    second: int
    side: Side
    event_type: EventType
    player_id: Optional[str] = None
    detail: str = ""
    xg: float = 0.0
    probability: float = Field(default=0.0, ge=0.0, le=1.0)
    state_before_version: int = 0
    state_after_version: int = 0
    scenario_tag: str = ""


class EventDependencyRule(BaseModel):
    """Constraints between events.

    ``requires``      - this event may only occur if one of these event types
                        occurred within ``window_minutes`` before it.
    ``forbids_after`` - if any of these events occurred recently, this event
                        is suppressed (cooldown).
    ``max_per_match`` - hard cap for the whole match.
    ``max_per_team``  - hard cap per team.
    """

    model_config = ConfigDict(extra="forbid")

    event_type: EventType
    requires: List[EventType] = Field(default_factory=list)
    window_minutes: int = 10
    forbids_after: List[EventType] = Field(default_factory=list)
    cooldown_minutes: int = 5
    max_per_match: int = 99
    max_per_team: int = 99
    max_per_minute: int = 3


class EventProbabilities(BaseModel):
    """Per-minute event intensity estimates produced by the Event Trigger Agent.

    All values are *rates/intensities per minute* or conditional probabilities
    in 0..1 - never directly "who wins".
    """

    model_config = ConfigDict(extra="forbid")

    match_id: str = ""
    minute: int = 0
    state_version: int = 0
    attack_intensity_home: float = Field(default=0.0, ge=0.0)
    attack_intensity_away: float = Field(default=0.0, ge=0.0)
    attack_outcomes: Dict[str, float] = Field(default_factory=dict)
    foul_rate_home: float = Field(default=0.0, ge=0.0)
    foul_rate_away: float = Field(default=0.0, ge=0.0)
    p_yellow_given_foul_home: float = Field(default=0.0, ge=0.0, le=1.0)
    p_yellow_given_foul_away: float = Field(default=0.0, ge=0.0, le=1.0)
    p_penalty_given_attack: float = Field(default=0.0, ge=0.0, le=1.0)
    p_injury_per_minute: float = Field(default=0.0, ge=0.0, le=1.0)
    reasons: Dict[str, str] = Field(default_factory=dict)
