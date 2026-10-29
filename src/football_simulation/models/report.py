"""Standard report models - the final output contract (spec sections 43/44).

All probabilities are stored in 0..1; the presentation layer converts to %.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from football_simulation.models.base import ConfidenceLevel, RiskLevel, new_id
from football_simulation.models.scenario import Scenario


class MatchInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match_id: str
    home: str
    away: str
    competition: str
    season: str = ""
    kickoff: datetime


class ResultProbability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    home_win: float = Field(ge=0.0, le=1.0)
    draw: float = Field(ge=0.0, le=1.0)
    away_win: float = Field(ge=0.0, le=1.0)

    def outcome(self) -> str:
        if self.home_win >= self.draw and self.home_win >= self.away_win:
            return "home_win"
        if self.away_win >= self.home_win and self.away_win >= self.draw:
            return "away_win"
        return "draw"


class ScoreProbability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matrix: Dict[str, float] = Field(default_factory=dict)  # "h-a" -> probability
    max_goals_individual: int = 6

    def total(self) -> float:
        return sum(self.matrix.values())

    def top(self, n: int = 10) -> List[Dict[str, Any]]:
        items = sorted(self.matrix.items(), key=lambda kv: -kv[1])
        return [{"score": k, "probability": v} for k, v in items[:n]]


class GoalsLineProbability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    over: Dict[str, float] = Field(default_factory=dict)  # "0.5" -> P(total > 0.5)
    under: Dict[str, float] = Field(default_factory=dict)
    expected_total_goals: float = 0.0
    total_goals_distribution: Dict[str, float] = Field(default_factory=dict)  # "0".."10+" -> P


class BTTSProbability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    yes: float = Field(ge=0.0, le=1.0)
    no: float = Field(ge=0.0, le=1.0)


class HTFTProbability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    combinations: Dict[str, float] = Field(default_factory=dict)  # "home/home" etc.
    ht_home_win: float = Field(ge=0.0, le=1.0)
    ht_draw: float = Field(ge=0.0, le=1.0)
    ht_away_win: float = Field(ge=0.0, le=1.0)


class UpsetRiskReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: RiskLevel = RiskLevel.LOW
    probability: float = Field(default=0.0, ge=0.0, le=1.0)
    direction: str = ""
    upset_type: str = ""
    severity: float = Field(default=0.0, ge=0.0, le=1.0)
    drivers: List[str] = Field(default_factory=list)


class RiskComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    level: RiskLevel = RiskLevel.LOW
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    reasons: List[str] = Field(default_factory=list)


class RiskReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall_risk: RiskLevel = RiskLevel.LOW
    overall_score: float = Field(default=0.0, ge=0.0, le=1.0)
    components: List[RiskComponent] = Field(default_factory=list)


class ConfidenceReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: ConfidenceLevel = ConfidenceLevel.MEDIUM
    score: float = Field(default=0.5, ge=0.0, le=1.0)
    scenario_concentration: float = Field(default=0.0, ge=0.0, le=1.0)
    data_completeness: float = Field(default=0.0, ge=0.0, le=1.0)
    agent_agreement: float = Field(default=0.0, ge=0.0, le=1.0)
    lineup_certainty: float = Field(default=0.0, ge=0.0, le=1.0)
    reasons: List[str] = Field(default_factory=list)


class FailureCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    condition: str
    impact: str = ""
    severity: RiskLevel = RiskLevel.MEDIUM


class DataQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completeness: float = Field(default=0.0, ge=0.0, le=1.0)
    unknowns: List[str] = Field(default_factory=list)
    lineup_confirmed: Dict[str, bool] = Field(default_factory=dict)
    notes: List[str] = Field(default_factory=list)


class ConvergenceReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    converged: bool = False
    threshold: float = 0.005
    samples: List[Dict[str, Any]] = Field(default_factory=list)  # {n, home_win, draw, away_win}
    max_delta: float = 1.0


class CounterfactualReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    counterfactual_id: str = Field(default_factory=new_id)
    description: str
    removed_event: Optional[str] = None
    probability_delta: Dict[str, float] = Field(default_factory=dict)
    result_delta: Dict[str, float] = Field(default_factory=dict)
    risk_delta: Dict[str, float] = Field(default_factory=dict)


class MatchPredictionReport(BaseModel):
    """The final V1 output per the spec's recommended structure."""

    model_config = ConfigDict(extra="forbid")

    match: MatchInfo
    result_probability: ResultProbability
    score_probability: ScoreProbability
    goals_probability: GoalsLineProbability
    btts: BTTSProbability
    half_time_full_time: HTFTProbability
    scenarios: List[Scenario] = Field(default_factory=list)
    scenario_ranking: Dict[str, Any] = Field(default_factory=dict)
    upset_risk: UpsetRiskReport
    risk: RiskReport
    confidence: ConfidenceReport
    failure_conditions: List[FailureCondition] = Field(default_factory=list)
    explanation: str = ""
    data_quality: DataQualityReport = Field(default_factory=DataQualityReport)
    convergence: Optional[ConvergenceReport] = None
    counterfactuals: List[CounterfactualReport] = Field(default_factory=list)
    trace: List[Any] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    simulation_runs: int = 0
    seed: int = 0
    model_version: str = "1.0.0"
