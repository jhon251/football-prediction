"""EXP-DIAG-EPL-002 (DIAG-002) runner: Tactical Multiplicative Amplification Diagnosis.

Diagnostic sandbox ONLY.  Production model, the 35 knowledge rules,
config/default.json, the V1.2 data layer, the frozen baselines
EXP-REAL-EPL-BASE-001 (7c52c6bdfa37) and EXP-DIAG-EPL-001 remain READ-ONLY.
No production file is modified by this script.

Three arms on the IDENTICAL frozen setup (2025-26 EPL, sample
range(0,380,3)[:120], seed 20240101, 400 sims, full agent pipeline):

    A "A_mult": production multiplicative combination  lam *= cc * f_att
    B "B_off" : tactical chance-creation channel disabled at the engine
                fusion point (cc forced to 1.0; f_att dynamics unchanged)
    C "C_add" : additive combination                     lam *= (cc + f_att - 1)

    cc    = tac.chance_creation_modifier  (TacticalMatchupAgent output,
             entered into the world via the Opening layer, production value)
    f_att = 0.55 + 0.9 * tac.attacking_intensity  (engine attacking factor)

Scale-equivalence note (reported, not tuned): A and C are EXACTLY equal at
the neutral point (cc=1, f_att=1) and first-order Taylor equivalent
(1+a+b+ab vs 1+a+b); the difference is the second-order cross term a*b,
which is precisely the mechanism under test.  C clips its combined factor
to [0.1, 3.0] (same domain as cc); the runner counts how often that clip
is active so the report can quantify any SCALE artifact.

The patch is applied at RUNTIME ONLY: the class reference
football_simulation.agents.director.EventTriggerAgent is replaced with a
subclass that transforms the two tactical factors for the duration of the
unchanged production _attack_intensity call, then restores the world state
exactly.  The production event engine code itself is never executed
differently in arm A (delegation is a no-op there).

Outputs (backtest_output/diag_002_tactical_amp/):
    preds.json          per-arm per-match predictions
    distributions.json  realized per-minute factor/lam distributions per arm
    validation.json     faithfulness checks vs the frozen EXP-DIAG-EPL-001 cache
    baseline_manifest_*.json  integrity hashes of the frozen directories
    experiments.jsonl   registry entry EXP-DIAG-EPL-002
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

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
OUT_DIR = Path("backtest_output/diag_002_tactical_amp")
DATASET_PATH = Path("data/historical/epl_2025_26.json")
SEASON = "2025-26"
SAMPLE_INDICES = sorted(set(range(0, 380, 3)))[:120]
SEED = 20240101  # frozen sample/seed of the baseline ablation
RUNS = 400

ARMS: Dict[str, str] = {
    "A_mult": "mult",
    "B_off": "off",
    "C_add": "add",
}

# histogram bin edges for realized per-minute quantities
_HIST_BINS: Dict[str, np.ndarray] = {
    "cc": np.linspace(0.1, 3.0, 30),
    "f_att": np.linspace(0.55, 1.45, 28),
    "factor": np.linspace(0.1, 3.45, 34),
    "lam": np.linspace(0.0, 0.6, 31),
}
_QUANTITIES = ("cc", "f_att", "factor", "lam")
_PER_MATCH_QUANTITIES = ("factor", "lam")


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


# ---------------------------------------------------------------------------
# runtime-only engine patch
# ---------------------------------------------------------------------------

class _Moments:
    __slots__ = ("n", "sum", "sumsq", "min", "max")

    def __init__(self) -> None:
        self.n = 0
        self.sum = 0.0
        self.sumsq = 0.0
        self.min = float("inf")
        self.max = float("-inf")

    def add(self, value: float) -> None:
        self.n += 1
        self.sum += value
        self.sumsq += value * value
        if value < self.min:
            self.min = value
        if value > self.max:
            self.max = value

    def as_dict(self) -> Dict[str, float]:
        if self.n == 0:
            return {"n": 0}
        mean = self.sum / self.n
        var = max(0.0, self.sumsq / self.n - mean * mean)
        return {
            "n": self.n,
            "mean": round(mean, 6),
            "std": round(var ** 0.5, 6),
            "min": round(self.min, 6),
            "max": round(self.max, 6),
        }


class Collector:
    """Aggregates realized per-minute quantities without touching the RNG."""

    def __init__(self, arm: str) -> None:
        self.arm = arm
        self.global_moments: Dict[str, _Moments] = {}
        self.hists: Dict[str, np.ndarray] = {}
        self.per_match: Dict[str, Dict[str, _Moments]] = {}
        self.clip_active = 0
        self.lam_tails: Dict[str, Dict[str, int]] = {}
        for side in ("HOME", "AWAY"):
            self.lam_tails[side] = {"lam_ge_0.3": 0, "lam_ge_0.4": 0, "lam_ge_0.5": 0}
            for qty in _QUANTITIES:
                key = f"{side}:{qty}"
                self.global_moments[key] = _Moments()
                self.hists[key] = np.zeros(len(_HIST_BINS[qty]) - 1, dtype=np.int64)
                if qty in _PER_MATCH_QUANTITIES:
                    self.per_match.setdefault(f"{side}:{qty}", {})

    def record(self, match_id: str, side: str, cc: float, f_att: float,
               factor: float, lam: float, clip_active: bool) -> None:
        if clip_active:
            self.clip_active += 1
        values = {"cc": cc, "f_att": f_att, "factor": factor, "lam": lam}
        for qty, value in values.items():
            key = f"{side}:{qty}"
            self.global_moments[key].add(value)
            bins = _HIST_BINS[qty]
            idx = min(len(bins) - 2, max(0, int(np.digitize(value, bins)) - 1))
            self.hists[key][idx] += 1
        for qty in _PER_MATCH_QUANTITIES:
            key = f"{side}:{qty}"
            self.per_match[key].setdefault(match_id, _Moments()).add(values[qty])
        for threshold, field in (("lam_ge_0.3", 0.3), ("lam_ge_0.4", 0.4),
                                 ("lam_ge_0.5", 0.5)):
            if lam >= field:
                self.lam_tails[side][threshold] += 1

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"arm": self.arm, "clip_active": self.clip_active}
        for key, moments in self.global_moments.items():
            out[key] = moments.as_dict()
        out["hists"] = {}
        for key, counts in self.hists.items():
            qty = key.split(":", 1)[1]
            out["hists"][key] = {
                "bins": [round(float(b), 4) for b in _HIST_BINS[qty]],
                "counts": [int(c) for c in counts],
            }
        out["per_match"] = {
            key: {mid: m.as_dict() for mid, m in per.items()}
            for key, per in self.per_match.items()
        }
        out["lam_tails"] = self.lam_tails
        return out


class Diag002EventAgent(EventTriggerAgent):
    """Subclass that transforms the two tactical factors, delegates to the
    UNCHANGED production _attack_intensity, then restores world state."""

    mode: str = "mult"           # arm selector, set by the runner
    collector: Optional[Collector] = None

    def _attack_intensity(self, world, side):
        mode = Diag002EventAgent.mode
        tac = world.tactical(side)
        orig_cc = tac.chance_creation_modifier
        orig_ai = tac.attacking_intensity
        f_att = 0.55 + 0.9 * orig_ai
        clip_active = False

        if mode == "mult":
            factor = orig_cc * f_att
        elif mode == "off":
            factor = f_att
            tac.chance_creation_modifier = 1.0
        elif mode == "add":
            raw = orig_cc + f_att - 1.0
            if raw < 0.1 or raw > 3.0:
                clip_active = True
            factor = min(3.0, max(0.1, raw))
            tac.chance_creation_modifier = factor
            tac.attacking_intensity = 0.5  # engine f_att becomes 1.0
        else:
            raise ValueError(f"unknown DIAG-002 mode: {mode!r}")

        try:
            lam, reason = super()._attack_intensity(world, side)
        finally:
            tac.chance_creation_modifier = orig_cc
            tac.attacking_intensity = orig_ai

        if Diag002EventAgent.collector is not None:
            Diag002EventAgent.collector.record(
                world.match_id, "HOME" if side is Side.HOME else "AWAY",
                orig_cc, f_att, factor, lam, clip_active)
        return lam, reason


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

def script_fingerprint() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]


def load_cached_diag1_preds() -> Dict[str, Dict[str, dict]]:
    return json.loads((DIAG1_DIR / "preds.json").read_text(encoding="utf-8"))


def validate_arms(preds: Dict[str, Dict[str, dict]]) -> Dict[str, Any]:
    """A_mult must reproduce the frozen full config EXACTLY (same seed/sample);
    B_off is compared against frozen full_minus_tactical (expected close but
    not identical: config-level ablation also neutralizes the opening channel)."""
    diag1 = load_cached_diag1_preds()
    out: Dict[str, Any] = {}
    for arm, ref_key in (("A_mult", "full"), ("B_off", "full_minus_tactical")):
        diffs: Dict[str, float] = {}
        for field in ("home_win", "draw", "away_win", "expected_goals"):
            values = []
            for match_id, pred in preds[arm].items():
                ref = diag1[ref_key].get(match_id)
                if ref is None:
                    continue
                values.append(abs(pred[field] - ref[field]))
            if values:
                diffs[field] = max(values)
        out[arm] = {"reference": ref_key, "max_abs_diff": diffs}
    return out


def merge_dists(arm: str, slices: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Exact merge of per-match collector slices (n/sum/sumsq/min/max are
    sufficient statistics; histograms and counters are additive)."""
    out: Dict[str, Any] = {"arm": arm, "clip_active": 0,
                           "hists": {}, "per_match": {}, "lam_tails": {}}
    for side in ("HOME", "AWAY"):
        out["lam_tails"][side] = {"lam_ge_0.3": 0, "lam_ge_0.4": 0, "lam_ge_0.5": 0}
    for match_id, slice_dict in slices.items():
        if not slice_dict:
            continue
        out["clip_active"] += int(slice_dict.get("clip_active", 0))
        for side in ("HOME", "AWAY"):
            for threshold in out["lam_tails"][side]:
                out["lam_tails"][side][threshold] += int(
                    slice_dict.get("lam_tails", {}).get(side, {}).get(threshold, 0))
        for key, per in slice_dict.get("per_match", {}).items():
            out["per_match"].setdefault(key, {}).update(per)
        for key, moments in slice_dict.items():
            if key in ("arm", "clip_active", "hists", "per_match", "lam_tails"):
                continue
            if not isinstance(moments, dict) or "n" not in moments:
                continue
            if moments["n"] == 0:
                continue
            n = moments["n"]
            mean = moments["mean"]
            sumsq = n * (moments["std"] ** 2 + mean * mean)
            target = out.setdefault(key, {"n": 0, "sum": 0.0, "sumsq": 0.0,
                                          "min": float("inf"), "max": float("-inf")})
            target["n"] += n
            target["sum"] += mean * n
            target["sumsq"] += sumsq
            target["min"] = min(target["min"], moments["min"])
            target["max"] = max(target["max"], moments["max"])
        for key, hist in slice_dict.get("hists", {}).items():
            target = out["hists"].setdefault(
                key, {"bins": hist.get("bins", []),
                      "counts": [0] * len(hist.get("counts", []))})
            for i, count in enumerate(hist.get("counts", [])):
                target["counts"][i] += int(count)
    # finalize global moments -> mean/std
    for key, moments in list(out.items()):
        if not (isinstance(moments, dict) and "n" in moments and "sum" in moments):
            continue
        if moments["n"] == 0:
            out[key] = {"n": 0}
            continue
        mean = moments["sum"] / moments["n"]
        var = max(0.0, moments["sumsq"] / moments["n"] - mean * mean)
        out[key] = {"n": moments["n"], "mean": round(mean, 6),
                    "std": round(var ** 0.5, 6),
                    "min": round(moments["min"], 6), "max": round(moments["max"], 6)}
    return out


def run_arm(arm: str, mode: str, sample, builder, dataset,
            cache_root: Path) -> Dict[str, dict]:
    preds: Dict[str, dict] = {}
    dists: Dict[str, dict] = {}
    cache_dir = cache_root / arm
    cache_dir.mkdir(parents=True, exist_ok=True)
    director_module.EventTriggerAgent = Diag002EventAgent
    Diag002EventAgent.mode = mode

    for match in sample:
        cache_path = cache_dir / f"{match.match_id}.json"
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            preds[match.match_id] = cached["prediction"]
            dists[match.match_id] = cached.get("dist", {})
            continue
        match_collector = Collector(arm)
        Diag002EventAgent.collector = match_collector
        snapshot = builder.build(match)
        provider = HistoricalDataProvider(dataset, snapshot,
                                          use_extended_features=True,
                                          expose_odds=False)
        director = DirectorAgent(
            provider,
            DirectorConfig(simulation_runs=RUNS, seed=SEED, disabled_agents=[]),
        )
        report = director.analyze(match.match_id)
        r = report.result_probability
        prediction = ModelPrediction(
            model=arm, home_win=r.home_win, draw=r.draw, away_win=r.away_win,
            expected_goals=report.goals_probability.expected_total_goals,
            over25=report.goals_probability.over.get("2.5"),
            btts_yes=report.btts.yes,
            score_matrix=dict(report.score_probability.matrix),
        ).model_dump(mode="json")
        dist_slice = match_collector.as_dict()
        preds[match.match_id] = prediction
        dists[match.match_id] = dist_slice
        cache_path.write_text(json.dumps(
            {"prediction": prediction, "dist": dist_slice}), encoding="utf-8")

    return preds, dists


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", type=int, default=0,
                        help="run only the first N matches of the sample")
    parser.add_argument("--merge-only", action="store_true",
                        help="re-merge distributions/preds from the records cache "
                             "(no simulation)")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.merge_only:
        preds_m: Dict[str, Dict[str, dict]] = {}
        slices: Dict[str, Dict[str, dict]] = {}
        for arm in ARMS:
            preds_m[arm] = {}
            slices[arm] = {}
            arm_dir = OUT_DIR / "records" / arm
            if not arm_dir.exists():
                raise RuntimeError(f"records cache missing for {arm} - run the sims first")
            for f in sorted(arm_dir.glob("*.json")):
                cached = json.loads(f.read_text(encoding="utf-8"))
                preds_m[arm][f.stem] = cached["prediction"]
                slices[arm][f.stem] = cached.get("dist", {})
        (OUT_DIR / "preds.json").write_text(json.dumps(preds_m, indent=1), encoding="utf-8")
        (OUT_DIR / "distributions.json").write_text(
            json.dumps({arm: merge_dists(arm, slices[arm]) for arm in ARMS}, indent=1),
            encoding="utf-8")
        (OUT_DIR / "validation.json").write_text(
            json.dumps(validate_arms(preds_m), indent=2), encoding="utf-8")
        log("merge-only: preds.json + distributions.json + validation.json rewritten")
        return

    # 0) integrity manifests of BOTH frozen directories (read-only checks)
    frozen_dirs = {"real_epl_base_001": BASELINE_DIR, "diagnosis_epl_001": DIAG1_DIR}
    for name, path in frozen_dirs.items():
        manifest = baseline_manifest(Path(path))
        (OUT_DIR / f"baseline_manifest_{name}.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8")
    stored = json.loads((DIAG1_DIR / "baseline_manifest.json").read_text(encoding="utf-8"))
    if stored["files"] != baseline_manifest(BASELINE_DIR)["files"]:
        raise RuntimeError("FROZEN BASELINE EXP-REAL-EPL-BASE-001 CHANGED - aborting")
    log("frozen baselines intact (hashes verified)")

    # cache fingerprint: stale caches from an older script version are discarded
    cache_root = OUT_DIR / ("records_smoke" if args.smoke else "records")
    if args.smoke and cache_root.exists():
        import shutil
        shutil.rmtree(cache_root)
    fp_path = cache_root / "_runner_fp.txt"
    fp = script_fingerprint()
    if fp_path.exists() and fp_path.read_text(encoding="utf-8").strip() != fp:
        import shutil
        for child in cache_root.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
        log("stale record cache cleared (runner changed)")
    fp_path.parent.mkdir(parents=True, exist_ok=True)
    fp_path.write_text(fp, encoding="utf-8")

    dataset = HistoricalDataset.load(DATASET_PATH)
    matches = dataset.matches_in_season(SEASON)
    sample = [matches[i] for i in SAMPLE_INDICES]
    if args.smoke:
        sample = sample[: args.smoke]
    assert len(sample) > 0
    builder = SnapshotBuilder(dataset.matches, strict=True)
    log(f"sample size={len(sample)}, arms={list(ARMS)}, runs={RUNS}, seed={SEED}")

    preds: Dict[str, Dict[str, dict]] = {}
    merged_dists: Dict[str, Dict[str, Any]] = {}
    t0 = time.time()
    for arm, mode in ARMS.items():
        arm_preds, arm_dists = run_arm(arm, mode, sample, builder, dataset, cache_root)
        preds[arm] = arm_preds
        merged_dists[arm] = merge_dists(arm, arm_dists)
        log(f"arm {arm} done ({len(arm_preds)} matches, "
            f"{time.time() - t0:.0f}s elapsed)")

    (OUT_DIR / "preds.json").write_text(json.dumps(preds, indent=1), encoding="utf-8")
    (OUT_DIR / "distributions.json").write_text(
        json.dumps(merged_dists, indent=1), encoding="utf-8")
    log("preds.json + distributions.json written")

    # faithfulness validation against the frozen EXP-DIAG-EPL-001 cache
    validation = validate_arms(preds)
    (OUT_DIR / "validation.json").write_text(
        json.dumps(validation, indent=2), encoding="utf-8")
    a_ok = all(v <= 1e-12 for v in validation["A_mult"]["max_abs_diff"].values())
    log(f"validation: A_mult vs frozen full -> {validation['A_mult']['max_abs_diff']} "
        f"{'(EXACT)' if a_ok else '(MISMATCH!)'}")
    log(f"validation: B_off vs frozen full_minus_tactical -> "
        f"{validation['B_off']['max_abs_diff']}")

    # registry entry
    registry = ExperimentRegistry(OUT_DIR / "experiments.jsonl")
    registry.record(
        data_version=data_version(DATASET_PATH),
        random_seed=SEED,
        train_period="walk-forward (frozen baseline reference)",
        test_period=SEASON,
        models=sorted(ARMS),
        matches_evaluated=len(ARMS) * len(sample),
        metrics={},
        synthetic_data=False,
        market_data=False,
        notes=[
            "EXP-DIAG-EPL-002 (DIAG-002): Tactical Multiplicative Amplification Diagnosis",
            "read-only vs production model/rules/config/data and frozen "
            "EXP-REAL-EPL-BASE-001 (7c52c6bdfa37) + EXP-DIAG-EPL-001",
            "arms: A_mult=production lam*=cc*f_att; B_off=cc forced 1.0 at engine "
            "fusion point; C_add=lam*=(cc+f_att-1) clipped to [0.1,3.0]",
            "identical data/sample(range(0,380,3)[:120])/seed(20240101)/400 sims; "
            "all other agents unchanged",
            "runtime-only monkey-patch of director.EventTriggerAgent; production "
            "files untouched (code_fingerprint records src/)",
            "A_mult validated EXACT against frozen full predictions; B_off compared "
            "against frozen full_minus_tactical (opening channel differs by design)",
            "no parameter optimization; additive arm uses neutral-point/first-order "
            "equivalent default scale (cc+f_att-1), not a tuned coefficient",
        ],
    )
    log("registry entry EXP-DIAG-EPL-002 written")
    log("DONE")


if __name__ == "__main__":
    main()
