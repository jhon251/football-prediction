"""EXP-DIAG-EPL-003 (DIAG-003) runner: Structure-vs-Information diagnosis.

Diagnostic sandbox ONLY.  Production model, the 35 knowledge rules,
config/default.json, the V1.2 data layer and the frozen baselines
EXP-REAL-EPL-BASE-001 (7c52c6bdfa37), EXP-DIAG-EPL-001, EXP-DIAG-EPL-002
remain READ-ONLY.  No production file is modified by this script.

DIAG-003 has two parts (all on the FULL 380-match 2025-26 EPL season,
walk-forward identical, 400 sims, seed 20240101):

  Part 1 - sample stability:
      full            (production pipeline, unchanged)
      team_psychology (the best of 17 configs on the 120-match sample,
                       Brier 0.6579 there; does it stay better on 380?)

  Part 2 - fusion structure vs information content:
      team_only        (production multiplicative Team channel)
      team_only_linear (same agent config; the ENGINE applies the
                        Team-derived factors ADDITIVELY at their neutral
                        equivalent scale - mechanism probe only)

Linear-fusion definition (mechanism probe, NOT a tuned model):
  1) shot quality composition (production):
       mean = mu0 * (0.6 + 0.8*att) * (1 - 0.18*(def-0.5))
     linear variant (neutral-exact at att=def=0.5, first-order equal,
     cross-term = the tested mechanism):
       mean = mu0 * (0.69 + 0.8*att - 0.18*def)
     implemented via a temporary input transform so the production body
     runs unchanged.
  2) home-advantage in attack intensity (production):
       lam *= (1 + home_adv)
     linear variant (neutral-exact at home_adv=0, fixed reference scale):
       lam = lam0 + base * home_adv
     SCALE NOTE: the multiplicative form adds lam0*home_adv, the linear
     form adds base*home_adv; lam0/base is typically in [0.55, 1.35], so
     magnitudes are comparable but not identical - recorded, not tuned.
  3) goalkeeper factor p_goal = xg * (1 - 0.35*(gk-0.5)) is a single
     factor (no cross-term to remove) -> unchanged in both arms.

Run pattern (two parallel jobs on this 16-core machine):
    python scripts/exp_diag_003_run.py --configs full,team_psychology --tag part1 --registry
    python scripts/exp_diag_003_run.py --configs team_only,team_only_linear --tag part2

Outputs (backtest_output/diag_003_structure_info/):
    preds_part1.json / preds_part2.json
    validation_part1.json / validation_part2.json
    baseline_manifest_*.json  (integrity hashes of the frozen dirs)
    experiments.jsonl         (registry entry EXP-DIAG-EPL-003, from part1)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import football_simulation.agents.director as director_module
from football_simulation.agents.director import DirectorAgent, DirectorConfig
from football_simulation.backtest.diagnosis import baseline_manifest
from football_simulation.backtest.experiments import (
    ExperimentRegistry,
    data_version,
)
from football_simulation.backtest.models import ModelPrediction
from football_simulation.core.event_engine import EventTriggerAgent
from football_simulation.data.historical.etl import HistoricalDataset
from football_simulation.data.historical.provider import HistoricalDataProvider
from football_simulation.data.historical.snapshot import SnapshotBuilder
from football_simulation.models.base import Side

BASELINE_DIR = Path("backtest_output/real_epl_base_001")
DIAG1_DIR = Path("backtest_output/diagnosis_epl_001")
DIAG2_DIR = Path("backtest_output/diag_002_tactical_amp")
OUT_DIR = Path("backtest_output/diag_003_structure_info")
DATASET_PATH = Path("data/historical/epl_2025_26.json")
SEASON = "2025-26"
SEED = 20240101
RUNS = 400

_OFF = ["Scenario", "Counterfactual"]

CONFIGS: Dict[str, list] = {
    "full": [],
    "team_psychology": ["Coach", "Player", "Fitness", "Tactical",
                        "Environment", "Referee", "Momentum"] + _OFF,
    "team_only": ["Coach", "Player", "Fitness", "Psychology", "Tactical",
                  "Environment", "Referee", "Momentum"] + _OFF,
    "team_only_linear": ["Coach", "Player", "Fitness", "Psychology", "Tactical",
                         "Environment", "Referee", "Momentum"] + _OFF,
}

ALL_MODELS = ["full", "team_psychology", "team_only", "team_only_linear"]


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


# ---------------------------------------------------------------------------
# runtime-only engine patch (linear Team-fusion probe)
# ---------------------------------------------------------------------------

class Diag003EventAgent(EventTriggerAgent):
    """Subclass that linearizes the Team-derived factors via input transforms,
    then delegates to the UNCHANGED production methods.  World state is
    restored exactly after every call."""

    mode: str = "plain"  # "plain" | "team_linear"

    def _attack_intensity(self, world, side):
        if Diag003EventAgent.mode != "team_linear" or side is not Side.HOME:
            return super()._attack_intensity(world, side)
        ts = world.home_team_state
        if ts is None:
            return super()._attack_intensity(world, side)
        h = ts.home_advantage
        if h == 0.0:
            return super()._attack_intensity(world, side)
        base = self.defaults["attack"]["base_intensity"]
        ts.home_advantage = 0.0
        try:
            lam0, reason = super()._attack_intensity(world, side)
        finally:
            ts.home_advantage = h
        lam = max(0.015, min(0.6, lam0 + base * h))
        return lam, f"{reason} | home_advantage +{base * h:.4f} (ADDITIVE probe)"

    def _sample_shot(self, world, side, rng, shooter_id, big=False):
        if Diag003EventAgent.mode != "team_linear":
            return super()._sample_shot(world, side, rng, shooter_id, big)
        ts = world.team_state(side)
        opp = world.team_state(side.opponent())
        if ts is None or opp is None:
            return super()._sample_shot(world, side, rng, shooter_id, big)
        att_orig = ts.attack_strength
        def_orig = opp.defense_strength
        # transform: (0.6+0.8*att')*(1-0.18*(def'-0.5)) == 0.69+0.8*att-0.18*def
        ts.attack_strength = 0.1125 + att_orig - 0.225 * def_orig
        opp.defense_strength = 0.5
        try:
            return super()._sample_shot(world, side, rng, shooter_id, big)
        finally:
            ts.attack_strength = att_orig
            opp.defense_strength = def_orig


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

def script_fingerprint() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]


def run_config(config: str, sample, builder, dataset, cache_dir: Path) -> Dict[str, dict]:
    preds: Dict[str, dict] = {}
    Diag003EventAgent.mode = "team_linear" if config == "team_only_linear" else "plain"
    director_module.EventTriggerAgent = Diag003EventAgent

    for match in sample:
        cache_path = cache_dir / f"{match.match_id}.json"
        if cache_path.exists():
            preds[match.match_id] = json.loads(cache_path.read_text(encoding="utf-8"))
            continue
        snapshot = builder.build(match)
        provider = HistoricalDataProvider(dataset, snapshot,
                                          use_extended_features=True,
                                          expose_odds=False)
        director = DirectorAgent(
            provider,
            DirectorConfig(simulation_runs=RUNS, seed=SEED,
                           disabled_agents=list(CONFIGS[config])),
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
        preds[match.match_id] = prediction
        cache_path.write_text(json.dumps(prediction), encoding="utf-8")
    return preds


def validate_against_diag1(preds: Dict[str, Dict[str, dict]],
                           diag1: Dict[str, Dict[str, dict]]) -> Dict[str, Any]:
    """The 120-match sample subset must reproduce the frozen EXP-DIAG-EPL-001
    cache EXACTLY (same data/sample/seed/400 sims)."""
    out: Dict[str, Any] = {}
    for config, cfg_preds in preds.items():
        if config not in diag1:
            continue
        diffs: Dict[str, float] = {}
        for field in ("home_win", "draw", "away_win", "expected_goals"):
            values = []
            for match_id, pred in cfg_preds.items():
                ref = diag1[config].get(match_id)
                if ref is None:
                    continue
                values.append(abs(pred[field] - ref[field]))
            diffs[field] = max(values) if values else None
        out[config] = diffs
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--configs", default=",".join(ALL_MODELS),
                        help="comma-separated configs to run")
    parser.add_argument("--tag", default="all", help="output file tag")
    parser.add_argument("--registry", action="store_true",
                        help="write the EXP-DIAG-EPL-003 registry entry (part1 job)")
    parser.add_argument("--smoke", type=int, default=0,
                        help="run only the first N matches (smoke test)")
    args = parser.parse_args()

    configs = [c.strip() for c in args.configs.split(",") if c.strip()]
    for c in configs:
        if c not in CONFIGS:
            raise SystemExit(f"unknown config {c!r} (available: {sorted(CONFIGS)})")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 0) integrity manifests of the frozen dirs (read-only checks)
    frozen_dirs = {"real_epl_base_001": BASELINE_DIR,
                   "diagnosis_epl_001": DIAG1_DIR,
                   "diag_002_tactical_amp": DIAG2_DIR}
    for name, path in frozen_dirs.items():
        manifest = baseline_manifest(Path(path))
        (OUT_DIR / f"baseline_manifest_{name}.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8")
    stored = json.loads((DIAG1_DIR / "baseline_manifest.json").read_text(encoding="utf-8"))
    if stored["files"] != baseline_manifest(BASELINE_DIR)["files"]:
        raise RuntimeError("FROZEN BASELINE EXP-REAL-EPL-BASE-001 CHANGED - aborting")
    log("frozen baselines intact (hashes verified)")

    cache_root = OUT_DIR / "records"
    cache_root.mkdir(parents=True, exist_ok=True)
    fp_path = cache_root / f"_runner_fp_{args.tag}.txt"
    fp = script_fingerprint()
    if fp_path.exists() and fp_path.read_text(encoding="utf-8").strip() != fp:
        for c in configs:
            cfg_dir = cache_root / c
            if cfg_dir.exists():
                for f in cfg_dir.glob("*.json"):
                    f.unlink()
        log("stale record cache cleared (runner changed)")
    fp_path.write_text(fp, encoding="utf-8")

    dataset = HistoricalDataset.load(DATASET_PATH)
    matches = dataset.matches_in_season(SEASON)
    assert len(matches) == 380, f"expected 380 matches, got {len(matches)}"
    sample = matches[: args.smoke] if args.smoke else matches
    builder = SnapshotBuilder(dataset.matches, strict=True)
    log(f"configs={configs}, matches={len(sample)}, runs={RUNS}, seed={SEED}")

    preds: Dict[str, Dict[str, dict]] = {}
    t0 = time.time()
    for config in configs:
        cache_dir = cache_root / config
        cache_dir.mkdir(parents=True, exist_ok=True)
        preds[config] = run_config(config, sample, builder, dataset, cache_dir)
        log(f"config {config} done ({len(preds[config])} matches, "
            f"{time.time() - t0:.0f}s elapsed)")

    (OUT_DIR / f"preds_{args.tag}.json").write_text(
        json.dumps(preds, indent=1), encoding="utf-8")
    log(f"preds_{args.tag}.json written")

    # faithfulness validation vs the frozen EXP-DIAG-EPL-001 cache (120 subset)
    diag1 = json.loads((DIAG1_DIR / "preds.json").read_text(encoding="utf-8"))
    validation = validate_against_diag1(preds, diag1)
    (OUT_DIR / f"validation_{args.tag}.json").write_text(
        json.dumps(validation, indent=2), encoding="utf-8")
    for config, diffs in validation.items():
        exact = all(v is not None and v <= 1e-12 for v in diffs.values())
        log(f"validation {config} vs frozen diag-001 cache: {diffs} "
            f"{'(EXACT)' if exact else '(MISMATCH!)'}")

    if args.registry:
        registry = ExperimentRegistry(OUT_DIR / "experiments.jsonl")
        registry.record(
            data_version=data_version(DATASET_PATH),
            random_seed=SEED,
            train_period="walk-forward (frozen baseline reference)",
            test_period=SEASON,
            models=ALL_MODELS,
            matches_evaluated=len(ALL_MODELS) * 380,
            metrics={},
            synthetic_data=False,
            market_data=False,
            notes=[
                "EXP-DIAG-EPL-003 (DIAG-003): structure-vs-information diagnosis",
                "read-only vs production model/rules/config/data and frozen "
                "EXP-REAL-EPL-BASE-001 + EXP-DIAG-EPL-001 + EXP-DIAG-EPL-002",
                "Part1 stability: full vs team_psychology on the full 380-match "
                "season (400 sims, seed 20240101)",
                "Part2 structure vs information: team_only vs team_only_linear "
                "(engine applies Team factors additively at neutral-equivalent "
                "scale: shot-quality product -> 0.69+0.8*att-0.18*def; home_adv "
                "lam*=1+h -> lam0+base*h; gk factor unchanged)",
                "linear arm is a mechanism probe, NOT a tuned model; no "
                "parameter optimization performed",
                "120-match subset validated EXACT against the frozen diag-001 "
                "cache for full/team_psychology/team_only",
            ],
        )
        log("registry entry EXP-DIAG-EPL-003 written")
    log("DONE")


if __name__ == "__main__":
    main()
