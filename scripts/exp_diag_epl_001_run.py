"""EXP-DIAG-EPL-001 diagnostic runner.

Runs DIAGNOSTIC configurations ONLY - the frozen baseline EXP-REAL-EPL-BASE-001
(experiment_id 7c52c6bdfa37) is read as reference and never modified or
overwritten.  All outputs go to backtest_output/diagnosis_epl_001/.

Production model / rules / config / data layer stay READ-ONLY: the code below
only REUSES them via the frozen public interfaces with the same dataset, same
sample definition (indices range(0,380,3)[:120]) and same seed (20240101) as
the frozen ablation - labeled as diagnostic runs, not baseline numbers.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from football_simulation.agents.director import DirectorAgent, DirectorConfig
from football_simulation.backtest.diagnosis import baseline_manifest
from football_simulation.backtest.experiments import (
    ExperimentRegistry,
    code_fingerprint,
    data_version,
    knowledge_version,
    parameter_version,
)
from football_simulation.backtest.models import ModelPrediction
from football_simulation.data.historical.etl import HistoricalDataset
from football_simulation.data.historical.provider import HistoricalDataProvider
from football_simulation.data.historical.snapshot import SnapshotBuilder

BASELINE_DIR = Path("backtest_output/real_epl_base_001")
OUT_DIR = Path("backtest_output/diagnosis_epl_001")
DATASET_PATH = Path("data/historical/epl_2025_26.json")
SEASON = "2025-26"
SAMPLE_INDICES = sorted(set(range(0, 380, 3)))[:120]
SEED = 20240101  # same seed as the frozen ablation
RUNS = 400

_OFF = ["Scenario", "Counterfactual"]

CONFIGS: Dict[str, list] = {
    "full": [],
    "full_minus_team": ["Team"],
    "full_minus_tactical": ["Tactical"],
    "full_minus_psychology": ["Psychology"],
    "full_minus_momentum": ["Momentum"],
    "full_minus_referee": ["Referee"],
    "full_minus_player": ["Player"],
    "team_only": ["Coach", "Player", "Fitness", "Psychology", "Tactical",
                  "Environment", "Referee", "Momentum"] + _OFF,
    "tactical_only": ["Team", "Coach", "Player", "Fitness", "Psychology",
                      "Environment", "Referee", "Momentum"] + _OFF,
    "psychology_only": ["Team", "Coach", "Player", "Fitness", "Tactical",
                        "Environment", "Referee", "Momentum"] + _OFF,
    "momentum_only": ["Team", "Coach", "Player", "Fitness", "Psychology",
                      "Tactical", "Environment", "Referee"] + _OFF,
    "referee_only": ["Team", "Coach", "Player", "Fitness", "Psychology",
                     "Tactical", "Environment", "Momentum"] + _OFF,
    "player_only": ["Team", "Coach", "Fitness", "Psychology", "Tactical",
                    "Environment", "Referee", "Momentum"] + _OFF,
    "team_tactical": ["Coach", "Player", "Fitness", "Psychology",
                      "Environment", "Referee", "Momentum"] + _OFF,
    "team_psychology": ["Coach", "Player", "Fitness", "Tactical",
                        "Environment", "Referee", "Momentum"] + _OFF,
    "team_momentum": ["Coach", "Player", "Fitness", "Psychology", "Tactical",
                      "Environment", "Referee"] + _OFF,
    "team_referee": ["Coach", "Player", "Fitness", "Psychology", "Tactical",
                     "Environment", "Momentum"] + _OFF,
}


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 0) frozen baseline integrity: snapshot hashes, never modify baseline dir
    manifest = baseline_manifest(BASELINE_DIR)
    (OUT_DIR / "baseline_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    log(f"baseline manifest recorded ({len(manifest['files'])} files hashed)")

    dataset = HistoricalDataset.load(DATASET_PATH)
    matches = dataset.matches_in_season(SEASON)
    sample = [matches[i] for i in SAMPLE_INDICES]
    assert len(sample) == 120
    builder = SnapshotBuilder(dataset.matches, strict=True)

    # per-config per-match prediction store with cache
    preds: Dict[str, Dict[str, dict]] = {config: {} for config in CONFIGS}
    cache_dir = OUT_DIR / "records_diag"
    cache_dir.mkdir(parents=True, exist_ok=True)

    total_runs = len(CONFIGS) * len(sample)
    done = 0
    t0 = time.time()
    for config, disabled in CONFIGS.items():
        config_cache = cache_dir / config
        config_cache.mkdir(parents=True, exist_ok=True)
        for match in sample:
            cache_path = config_cache / f"{match.match_id}.json"
            if cache_path.exists():
                preds[config][match.match_id] = json.loads(cache_path.read_text(encoding="utf-8"))
                done += 1
                continue
            snapshot = builder.build(match)
            provider = HistoricalDataProvider(dataset, snapshot,
                                              use_extended_features=True,
                                              expose_odds=False)
            director = DirectorAgent(
                provider,
                DirectorConfig(simulation_runs=RUNS, seed=SEED,
                               disabled_agents=list(disabled)),
            )
            report = director.analyze(match.match_id)
            r = report.result_probability
            prediction = ModelPrediction(
                model=config, home_win=r.home_win, draw=r.draw, away_win=r.away_win,
                expected_goals=report.goals_probability.expected_total_goals,
                over25=report.goals_probability.over.get("2.5"),
                btts_yes=report.btts.yes,
                score_matrix=dict(report.score_probability.matrix),
            ).model_dump(mode="json")
            preds[config][match.match_id] = prediction
            cache_path.write_text(json.dumps(prediction), encoding="utf-8")
            done += 1
            if done % 40 == 0:
                log(f"diagnostic predictions {done}/{total_runs} "
                    f"({time.time() - t0:.0f}s)")

    (OUT_DIR / "preds.json").write_text(json.dumps(preds, indent=1), encoding="utf-8")
    log(f"preds.json written ({done} config-match predictions)")

    # registry entry for the diagnosis experiment
    registry = ExperimentRegistry(OUT_DIR / "experiments.jsonl")
    registry.record(
        data_version=data_version(DATASET_PATH),
        random_seed=SEED,
        train_period="walk-forward (frozen baseline reference)",
        test_period=SEASON,
        models=sorted(CONFIGS),
        matches_evaluated=len(sample) * len(CONFIGS),
        metrics={},
        synthetic_data=False,
        market_data=False,
        notes=[
            "EXP-DIAG-EPL-001: failure diagnosis, read-only vs production model",
            f"frozen baseline reference: experiment_id {manifest['experiment_id']} "
            f"(baseline dir untouched; hashes in baseline_manifest.json)",
            "diagnostic configs: only-X / full-X / Team+X on the frozen 120-match sample",
            "code/data/knowledge/parameter fingerprints recorded for traceability",
        ],
    )
    log("diagnosis registry entry written")
    log("DONE")


if __name__ == "__main__":
    main()
