"""V1.2 Agent Contribution on historical (stand-in) data.

Full System vs Full-X for each listed agent, measured over a fixed match
sample with Brier / LogLoss / accuracy / mean probability change.

Nothing is tuned here - this only measures marginal contributions.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from football_simulation.agents.director import DirectorAgent, DirectorConfig
from football_simulation.backtest.metrics import full_metrics
from football_simulation.backtest.models import ModelPrediction, PredictionRecord
from football_simulation.data.historical.etl import HistoricalDataset
from football_simulation.data.historical.provider import HistoricalDataProvider
from football_simulation.data.historical.snapshot import SnapshotBuilder

ABLATION = [
    ("full_system", []),
    ("full_minus_team", ["Team"]),
    ("full_minus_player", ["Player"]),
    ("full_minus_coach", ["Coach"]),
    ("full_minus_tactical", ["Tactical"]),
    ("full_minus_fitness", ["Fitness"]),
    ("full_minus_psychology", ["Psychology"]),
    ("full_minus_referee", ["Referee"]),
    ("full_minus_environment", ["Environment"]),
    ("full_minus_momentum", ["Momentum"]),
]


def main(season: str = "2024-25", sample: int = 40, runs: int = 400, seed: int = 2024):
    dataset = HistoricalDataset.load(Path("data/historical/synthetic_epl.json"))
    builder = SnapshotBuilder(dataset.matches, strict=True)
    matches = dataset.matches_in_season(season)[:sample]

    records: dict = {name: [] for name, _ in ABLATION}
    for i, match in enumerate(matches):
        snapshot = builder.build(match)
        print(f"[{i + 1}/{len(matches)}] {match.match_id} {match.home_team} vs {match.away_team}")
        for name, disabled in ABLATION:
            provider = HistoricalDataProvider(dataset, snapshot)
            director = DirectorAgent(
                provider,
                DirectorConfig(simulation_runs=runs, seed=seed,
                               disabled_agents=list(disabled)),
            )
            report = director.analyze(match.match_id)
            r = report.result_probability
            records[name].append(PredictionRecord(
                match_id=match.match_id, kickoff=match.date,
                home_team=match.home_team, away_team=match.away_team,
                actual_home_goals=match.home_goals, actual_away_goals=match.away_goals,
                predictions={"model": ModelPrediction(
                    model=name, home_win=r.home_win, draw=r.draw, away_win=r.away_win,
                    expected_goals=report.goals_probability.expected_total_goals,
                    over25=report.goals_probability.over.get("2.5"),
                    btts_yes=report.btts.yes,
                    score_matrix=dict(report.score_probability.matrix))},
                synthetic=True))

    print(f"\n{'config':24s} {'brier':>8s} {'logloss':>9s} {'acc':>7s} {'ECE':>7s} {'exp_goals':>9s}")
    summary = {}
    base = full_metrics(records["full_system"], "model")["one_x_two"]
    for name, _ in ABLATION:
        metrics = full_metrics(records[name], "model")
        one = metrics["one_x_two"]
        cal = metrics["calibration"]
        goals = sum(r.predictions["model"].expected_goals for r in records[name]) / len(records[name])
        summary[name] = {"brier": one["brier"], "log_loss": one["log_loss"],
                         "accuracy": one["accuracy"], "ece": cal["ece"],
                         "expected_goals": goals,
                         "delta_brier_vs_full": round(one["brier"] - base["brier"], 4)}
        print(f"{name:24s} {one['brier']:8.4f} {one['log_loss']:9.4f} "
              f"{one['accuracy']:7.3f} {cal['ece']:7.4f} {goals:9.3f}")

    out = Path(f"backtest_output/v12_ablation_{season}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nsummary -> {out}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", default="2024-25")
    parser.add_argument("--sample", type=int, default=40)
    parser.add_argument("--runs", type=int, default=400)
    parser.add_argument("--seed", type=int, default=2024)
    args = parser.parse_args()
    main(args.season, args.sample, args.runs, args.seed)
