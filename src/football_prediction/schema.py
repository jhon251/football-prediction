# -*- coding: utf-8 -*-
"""prediction_input / prediction_output schemas (pydantic v2)."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

OUTPUT_STATES = ("VALID", "CONDITIONAL", "INSUFFICIENT_DATA", "UNKNOWN", "REJECTED", "STOP")
# worst-first severity ordering for aggregate status
_SEVERITY = {s: i for i, s in enumerate(
    ("STOP", "REJECTED", "INSUFFICIENT_DATA", "UNKNOWN", "CONDITIONAL", "VALID"))}


def worst_state(states: list[str]) -> str:
    return min(states, key=lambda s: _SEVERITY[s]) if states else "UNKNOWN"


class MatchInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    home_team: str = Field(min_length=1)
    away_team: str = Field(min_length=1)
    league: str = Field(min_length=1)
    kickoff_utc: str


class OddsBlock(BaseModel):
    model_config = ConfigDict(extra="allow")
    context: Literal["preclosing"]
    source: str = "unspecified"
    retrieved_at: Optional[str] = None
    books: dict[str, dict[str, Any]] = Field(default_factory=dict)


class PredictionInput(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["prediction_input.v1"]
    match: MatchInfo
    odds: OddsBlock
    external_signals: list[dict[str, Any]] = Field(default_factory=list)
