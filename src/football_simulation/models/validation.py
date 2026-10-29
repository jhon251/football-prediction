"""V1.1 validation report models (system-level sanity dashboard)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from football_simulation.models.base import utc_now


class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    detail: str = ""


class ValidationSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    results: List[CheckResult] = Field(default_factory=list)


class AgentContributionRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: str
    home_win: float
    draw: float
    away_win: float
    expected_goals: float
    delta_home_win: Optional[float] = None  # vs previous row (None for baseline)
    note: str = ""


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime = Field(default_factory=utc_now)
    real_data_ready: bool = False
    real_data_gates: List[str] = Field(default_factory=list)
    overall_verdict: str = "NOT READY FOR REAL PREDICTION"
    sections: List[ValidationSection] = Field(default_factory=list)
    contributions: List[AgentContributionRow] = Field(default_factory=list)
    rule_counts: Dict[str, int] = Field(default_factory=dict)
    anomalies: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)

    def all_passed(self) -> bool:
        return all(s.passed for s in self.sections)


REAL_DATA_GATES = [
    "real_data_provider",
    "historical_data",
    "historical_backtest",
    "leakage_audit",
    "calibration_test",
    "brier_score",
    "log_loss",
    "roi_simulation",
    "baseline_comparison",
]
