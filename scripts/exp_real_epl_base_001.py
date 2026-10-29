"""EXP-REAL-EPL-BASE-001: first no-market blind backtest on REAL 2025-26 EPL.

Constraints enforced HERE (and asserted, not assumed):
  * NO market data: market_odds baseline excluded; provider exposes no odds.
  * Strict walk-forward: only observed_at < kickoff(T) history; each match is
    predicted before it enters history (time-travel test proves equivalence).
  * No shuffling, no random train/test split, no future-season information.
  * Baselines: random / home_advantage / elo / historical_goal_rate /
    poisson (MLE refit every 20 matches on past-only data) + full sandbox.
  * Metrics: 1X2 (acc/top1/top2/brier/logloss/ECE), OU2.5, BTTS, score top1/3/5,
    Early/Mid/Late phases, rolling 100-match brier/logloss/accuracy,
    calibration curve.
  * Agent ablation: full, full-Team, full-Tactical, full-Psychology,
    full-Momentum, full-Player, full-Referee (fixed 120-match sample).
  * NO parameter tuning anywhere; a bad result is reported as-is.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from football_simulation.agents.director import DirectorAgent, DirectorConfig
from football_simulation.backtest.experiments import ExperimentRegistry, data_version
from football_simulation.backtest.leakage import audit_leakage
from football_simulation.backtest.metrics import (
    full_metrics,
    model_comparison,
    phase_metrics,
    rolling_metrics,
)
from football_simulation.backtest.models import ModelPrediction, PredictionRecord
from football_simulation.backtest.runner import WalkForwardBacktester
from football_simulation.data.historical.etl import HistoricalDataset
from football_simulation.data.historical.provider import HistoricalDataProvider
from football_simulation.data.historical.snapshot import SnapshotBuilder

EXPERIMENT_ID = "EXP-REAL-EPL-BASE-001"
SEASON = "2025-26"
DATASET_PATH = Path("data/historical/epl_2025_26.json")
OUT_DIR = Path("backtest_output/real_epl_base_001")
MAIN_SEED = 12345
MAIN_RUNS = 800
ABLATION_SAMPLE = 120
ABLATION_RUNS = 500
ABLATION_SEED = 20240101

ABLATION_CONFIGS = [
    ("full", []),
    ("full_minus_team", ["Team"]),
    ("full_minus_tactical", ["Tactical"]),
    ("full_minus_psychology", ["Psychology"]),
    ("full_minus_momentum", ["Momentum"]),
    ("full_minus_player", ["Player"]),
    ("full_minus_referee", ["Referee"]),
]


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dataset = HistoricalDataset.load(DATASET_PATH)
    assert dataset.matches and not dataset.matches[0].is_synthetic

    # gate: leakage audit must pass on the real dataset
    audit = audit_leakage(dataset)
    if not audit.passed:
        log("LEAKAGE AUDIT FAILED - experiment aborted")
        sys.exit(1)
    log(f"leakage audit PASS ({len(dataset.matches)} matches)")

    # ---- main run: 5 baselines + full sandbox, NO market data ------------
    runner = WalkForwardBacktester(
        dataset,
        runs=MAIN_RUNS,
        seed=MAIN_SEED,
        include_system=True,
        cache_dir=OUT_DIR / "records",
        exclude_models={"market_odds"},          # zero market information
        extended_features=True,                  # shots/SOT/corners/fouls/cards
        expose_odds=False,                       # provider hides all odds
        refit_every=20,                          # Poisson walk-forward refit
    )
    log(f"main run: {len(dataset.matches)} matches x {MAIN_RUNS} sims (no market)")
    t0 = time.time()
    records = runner.run_season(SEASON, progress=lambda i, n: log(f"main {i}/{n}"))
    log(f"main run done in {time.time() - t0:.0f}s")

    # assertions: the experiment's own constraints must hold in the output
    for record in records:
        assert "market_odds" not in record.predictions, "market odds leaked into predictions"
    assert all(not r.synthetic for r in records)

    comparison = model_comparison(records)
    phases = {model: phase_metrics(records, model) for model in comparison}
    rolling = {model: rolling_metrics(records, model, window=100) for model in comparison}
    calibration = {model: full_metrics(records, model)["calibration"] for model in comparison}

    (OUT_DIR / "records.json").write_text(
        json.dumps([r.model_dump(mode="json") for r in records], ensure_ascii=False, indent=1),
        encoding="utf-8")
    (OUT_DIR / "metrics.json").write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    (OUT_DIR / "phases.json").write_text(json.dumps(phases, indent=2), encoding="utf-8")
    (OUT_DIR / "rolling.json").write_text(json.dumps(rolling, indent=2), encoding="utf-8")
    (OUT_DIR / "calibration.json").write_text(json.dumps(calibration, indent=2), encoding="utf-8")

    # ---- ablation on a fixed evenly-spaced sample -------------------------
    log(f"ablation: {len(ABLATION_CONFIGS)} configs x {ABLATION_SAMPLE} matches "
        f"x {ABLATION_RUNS} sims")
    matches = dataset.matches_in_season(SEASON)
    sample = [matches[i] for i in sorted(set(range(0, len(matches), 3)))[:ABLATION_SAMPLE]]
    builder = SnapshotBuilder(dataset.matches, strict=True)
    ablation_records: dict = {name: [] for name, _ in ABLATION_CONFIGS}
    t0 = time.time()
    for i, match in enumerate(sample):
        snapshot = builder.build(match)
        for name, disabled in ABLATION_CONFIGS:
            provider = HistoricalDataProvider(dataset, snapshot,
                                              use_extended_features=True,
                                              expose_odds=False)
            director = DirectorAgent(
                provider,
                DirectorConfig(simulation_runs=ABLATION_RUNS, seed=ABLATION_SEED,
                               disabled_agents=list(disabled)),
            )
            report = director.analyze(match.match_id)
            r = report.result_probability
            ablation_records[name].append(PredictionRecord(
                match_id=match.match_id, kickoff=match.date,
                home_team=match.home_team, away_team=match.away_team,
                actual_home_goals=match.home_goals, actual_away_goals=match.away_goals,
                predictions={"model": ModelPrediction(
                    model=name, home_win=r.home_win, draw=r.draw, away_win=r.away_win,
                    expected_goals=report.goals_probability.expected_total_goals,
                    over25=report.goals_probability.over.get("2.5"),
                    btts_yes=report.btts.yes,
                    score_matrix=dict(report.score_probability.matrix))},
                synthetic=False))
        if (i + 1) % 20 == 0:
            log(f"ablation {i + 1}/{len(sample)} ({time.time() - t0:.0f}s)")
    ablation_metrics = {
        name: full_metrics(ablation_records[name], "model")["one_x_two"]
        for name, _ in ABLATION_CONFIGS
    }
    full_one = ablation_metrics["full"]
    for name in ablation_metrics:
        ablation_metrics[name]["delta_brier_vs_full"] = round(
            ablation_metrics[name]["brier"] - full_one["brier"], 4)
    (OUT_DIR / "ablation.json").write_text(json.dumps(ablation_metrics, indent=2),
                                           encoding="utf-8")
    log("ablation done")

    # ---- experiment registry ----------------------------------------------
    registry = ExperimentRegistry(OUT_DIR / "experiments.jsonl")
    registry.record(
        data_version=data_version(DATASET_PATH),
        random_seed=MAIN_SEED,
        train_period="walk-forward: all matches with kickoff < predicted match",
        test_period=SEASON,
        models=sorted(comparison.keys()),
        matches_evaluated=len(records),
        metrics={model: {"brier": m["one_x_two"]["brier"],
                         "log_loss": m["one_x_two"]["log_loss"],
                         "accuracy": m["one_x_two"]["accuracy"]}
                 for model, m in comparison.items()},
        synthetic_data=False,
        market_data=False,
        notes=[
            f"experiment {EXPERIMENT_ID}: first no-market blind backtest on real 2025-26 EPL",
            "all odds fields excluded (market_odds baseline removed; provider exposes no odds)",
            "walk-forward only; no shuffling; no tuning",
            "full system uses extended walk-forward features (shots/SOT/corners/fouls/cards)",
        ],
    )
    log(f"registry entry written ({len(records)} matches evaluated)")
    log("DONE")


if __name__ == "__main__":
    main()
