"""Scenario models (Match Script Agent / Scenario Ranking Agent outputs)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from football_simulation.models.base import Side, new_id


class ScenarioTimelineEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minute: int
    state: str = ""
    event: Optional[str] = None


class ScenarioKeyEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minute: int
    side: Side
    event_type: str
    detail: str = ""


class ScorePathEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minute: int
    score_home: int
    score_away: int


class Scenario(BaseModel):
    """One match scenario / script per the spec (section 45)."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(default_factory=new_id)
    name: str
    probability: float = Field(default=0.0, ge=0.0, le=1.0)
    description: str = ""
    initial_conditions: Dict[str, Any] = Field(default_factory=dict)
    timeline: List[ScenarioTimelineEntry] = Field(default_factory=list)
    key_events: List[ScenarioKeyEvent] = Field(default_factory=list)
    tactical_changes: List[Dict[str, Any]] = Field(default_factory=list)
    score_path: List[ScorePathEntry] = Field(default_factory=list)
    final_result: Dict[str, Any] = Field(default_factory=dict)
    failure_conditions: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    # Ranking metadata
    consistency: float = Field(default=1.0, ge=0.0, le=1.0)
    plausibility: float = Field(default=1.0, ge=0.0, le=1.0)
    archetype: str = "long_tail"
    sample_count: int = 0


class ScenarioRanking(BaseModel):
    """Ordered scenario list plus the mandatory long tail."""

    model_config = ConfigDict(extra="forbid")

    scenarios: List[Scenario] = Field(default_factory=list)
    long_tail_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    long_tail_count: int = 0
