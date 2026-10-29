"""Backtest data models (V1.2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from football_simulation.models.base import new_id, utc_now


class ModelPrediction(BaseModel):
    """Probability output of ONE model/baseline for ONE match."""

    model_config = ConfigDict(extra="forbid")

    model: str
    home_win: float
    draw: float
    away_win: float
    expected_goals: float = 0.0
    over25: Optional[float] = None
    over35: Optional[float] = None
    btts_yes: Optional[float] = None
    score_matrix: Dict[str, float] = Field(default_factory=dict)  # "h-a" -> p
    is_synthetic_note: str = ""

    def validate_probabilities(self) -> List[str]:
        problems: List[str] = []
        total = self.home_win + self.draw + self.away_win
        if abs(total - 1.0) > 1e-4:
            problems.append(f"{self.model}: 1X2 sums to {total:.5f}")
        for key, value in (("over25", self.over25), ("over35", self.over35),
                           ("btts_yes", self.btts_yes)):
            if value is not None and not (0.0 <= value <= 1.0):
                problems.append(f"{self.model}: {key}={value} out of range")
        return problems


class PredictionRecord(BaseModel):
    """One frozen prediction + its actual outcome (for evaluation)."""

    model_config = ConfigDict(extra="forbid")

    match_id: str
    kickoff: datetime
    home_team: str
    away_team: str
    actual_home_goals: int
    actual_away_goals: int
    actual_ht_home_goals: int = 0
    actual_ht_away_goals: int = 0
    predictions: Dict[str, ModelPrediction] = Field(default_factory=dict)
    unknowns: List[str] = Field(default_factory=list)
    no_signal: List[str] = Field(default_factory=list)
    top_scenario: Optional[str] = None
    seed: int = 0
    runs: int = 0
    synthetic: bool = True

    def actual_result(self) -> str:
        if self.actual_home_goals > self.actual_away_goals:
            return "home_win"
        if self.actual_home_goals < self.actual_away_goals:
            return "away_win"
        return "draw"


class ExperimentRecord(BaseModel):
    """Experiment Registry entry (spec V1.2 section 17)."""

    model_config = ConfigDict(extra="forbid")

    experiment_id: str = Field(default_factory=new_id)
    git_commit: str = "unavailable"
    code_fingerprint: str = ""
    data_version: str = ""
    knowledge_version: str = ""
    parameter_version: str = ""
    snapshot_version: str = "1"
    random_seed: int = 0
    train_period: str = ""
    test_period: str = ""
    models: List[str] = Field(default_factory=list)
    matches_evaluated: int = 0
    metrics: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    synthetic_data: bool = True
    market_data: bool = Field(
        default=False,
        description="Whether odds/market fields were used. EXP-REAL-EPL-BASE-001 "
                    "excludes ALL odds -> false.",
    )
    notes: List[str] = Field(default_factory=list)


class FailureCase(BaseModel):
    """One failed prediction analyzed (spec V1.2 section 20)."""

    model_config = ConfigDict(extra="forbid")

    match_id: str
    prediction: Dict[str, Any] = Field(default_factory=dict)
    actual_result: Dict[str, Any] = Field(default_factory=dict)
    pre_match_summary: Dict[str, Any] = Field(default_factory=dict)
    top_scenario: Optional[str] = None
    probability: Optional[float] = None
    error_location: str = "UNKNOWN"  # data|agent|world_model|simulation|randomness|unknown
    error_reason: str = ""
