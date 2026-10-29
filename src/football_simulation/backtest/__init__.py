"""Backtesting package (V1.2)."""

from football_simulation.backtest.baselines import (
    BASELINE_NAMES,
    EloBaseline,
    HistoricalGoalRateBaseline,
    HomeAdvantageBaseline,
    MarketBaseline,
    PoissonBaseline,
    RandomBaseline,
    make_baselines,
)
from football_simulation.backtest.leakage import LeakageAuditReport, audit_leakage, format_audit
from football_simulation.backtest.metrics import (
    calibration_curve,
    full_metrics,
    model_comparison,
    one_x_two_metrics,
    score_metrics,
)
from football_simulation.backtest.models import (
    ExperimentRecord,
    FailureCase,
    ModelPrediction,
    PredictionRecord,
)
from football_simulation.backtest.runner import WalkForwardBacktester, run_backtest

__all__ = [
    "BASELINE_NAMES",
    "EloBaseline",
    "ExperimentRecord",
    "FailureCase",
    "HistoricalGoalRateBaseline",
    "HomeAdvantageBaseline",
    "LeakageAuditReport",
    "MarketBaseline",
    "ModelPrediction",
    "PoissonBaseline",
    "PredictionRecord",
    "RandomBaseline",
    "WalkForwardBacktester",
    "audit_leakage",
    "calibration_curve",
    "format_audit",
    "full_metrics",
    "make_baselines",
    "model_comparison",
    "one_x_two_metrics",
    "run_backtest",
    "score_metrics",
]
