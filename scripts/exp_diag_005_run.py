"""EXP-DIAG-EPL-005 (DIAG-005) execution: Information Source Incremental Value.

Strictly follows docs/DIAG_005_INFO_SOURCE_DESIGN.md (pre-registration).
No training, no parameter fitting, no weight adjustment, no production code
changes, no new unregistered information sources.

Conditional-calibration probe over the FROZEN Elo probabilities (380 matches):
    P_probe(outcome | t) = walk-forward empirical outcome frequency in
        (elo_prob strata x source bins), with pre-registered fallback chain
        ((elo x s) cell >= MIN_CELL -> elo-bin only -> raw elo).
Primary statistic: d_Brier = Brier(probe) - Brier(elo).
Permutation tests (seed 20240101, 10,000 reps):
    PRIMARY  = permute the SOURCE feature values across matches
               (operationalizes the pre-registered H0 'the source has no
               Elo-extra increment'; disclosed refinement over the design's
               literal outcome-vector permutation, which is anti-conservative
               per DIAG-004 S1).
    SECONDARY = outcome-vector permutation (design-literal), for transparency.
Plus split-half consistency (first/last 190) and Bonferroni alpha=0.05/7.

Tested sources: shot quality (SOT share), SOT volume, congestion_14d,
time-varying home factor.  xG/xGA: proxy limitation recorded, NO probe.
Lineup stability & injuries: DATA_UNAVAILABLE, no inference.
closing_odds: excluded (no-market discipline).

Outputs (backtest_output/diag_005_info_source/):
    probes.json  per-match probe probabilities + features + fallback flags
    stats.json   d_Brier / d_LogLoss / Murphy C / permutation p / split-half
    baseline_manifest_*.json   integrity hashes of the frozen dirs
    experiments.jsonl          registry entry EXP-DIAG-EPL-005
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from football_simulation.backtest.diagnosis import baseline_manifest
from football_simulation.backtest.experiments import ExperimentRegistry, data_version
from football_simulation.backtest.models import PredictionRecord
from football_simulation.data.historical import features as feats
from football_simulation.data.historical.etl import HistoricalDataset

BASELINE_DIR = Path("backtest_output/real_epl_base_001")
DIAG1_DIR = Path("backtest_output/diagnosis_epl_001")
DIAG2_DIR = Path("backtest_output/diag_002_tactical_amp")
DIAG3_DIR = Path("backtest_output/diag_003_structure_info")
DIAG4_DIR = Path("backtest_output/diag_004_elo_error")
OUT_DIR = Path("backtest_output/diag_005_info_source")
DATASET_PATH = Path("data/historical/epl_2025_26.json")

PERM_SEED = 20240101
N_PERM = 10_000
ALPHA = 0.05 / 7          # pre-registered Bonferroni across the 7 design candidates
DBRIER_THRESHOLD = -0.003  # pre-registered success threshold
MIN_HISTORY = 30          # pre-registered minimum walk-forward history (matches)
MIN_CELL = 20             # pre-registered minimum cell count before fallback
WINDOW = 10               # rolling stat window (matches)

OUTCOMES = ["home_win", "draw", "away_win"]


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def actual_idx(hg: int, ag: int) -> int:
    if hg > ag:
        return 0
    if hg < ag:
        return 2
    return 1


def load_frozen_records() -> List[PredictionRecord]:
    raw = json.loads((BASELINE_DIR / "records.json").read_text(encoding="utf-8"))
    return [PredictionRecord.model_validate(r) for r in raw]


def brier_3way(probs: np.ndarray, actuals: np.ndarray) -> float:
    y = np.zeros((probs.shape[1], 3))
    y[np.arange(len(actuals)), actuals] = 1.0
    return float(np.mean(np.sum((probs.T - y) ** 2, axis=1)))


def logloss_3way(probs: np.ndarray, actuals: np.ndarray) -> float:
    p = np.clip(probs[actuals, np.arange(len(actuals))], 1e-12, 1.0)
    return float(np.mean(-np.log(p)))


def murphy_c(probe: np.ndarray, elo: np.ndarray, actuals: np.ndarray) -> float:
    A = probe[actuals, np.arange(len(actuals))]
    E = elo[actuals, np.arange(len(actuals))]
    return float(np.mean((A - E) * (E - 1.0)))


def evaluate_probe(
    feature_lists: Sequence[List[Optional[float]]],
    elo: np.ndarray,
    actual_vector: np.ndarray,
    perms: Optional[Sequence[Optional[np.ndarray]]] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Sequential expanding-window conditional-frequency probe.

    feature_lists[k][t] = walk-forward value of source k at match t (None =
    unavailable -> match is handled via the elo-only fallback path).
    perms[k] (optional) = permuted assignment of source k's values across
    matches (same length 380; used by the source-value permutation test).

    Returns (probe_probs (3,380), fallback_mask (380,)).
    """
    k = len(feature_lists)
    n = elo.shape[1]
    probs = np.zeros((3, n))
    fallback = np.zeros(n, dtype=bool)
    hist_elo: List[List[float]] = [[], [], []]
    hist_s: List[List[float]] = [[] for _ in range(k)]
    hist_actual: List[int] = []

    for t in range(n):
        s_vals = [feature_lists[k_][t] for k_ in range(k)]
        s_vals_eff = []
        for k_ in range(k):
            if perms is not None and perms[k_] is not None:
                s_vals_eff.append(perms[k_][t])  # permuted assignment (may be NaN)
            else:
                s_vals_eff.append(s_vals[k_])
        use_s = (len(hist_actual) >= MIN_HISTORY
                 and all(sum(1 for v in hist_s[k_] if v is not None) >= MIN_HISTORY
                         for k_ in range(k))
                 and all(v is not None and not (isinstance(v, float) and np.isnan(v))
                         for v in s_vals_eff))
        s_bins = None
        if use_s:
            thr = [float(np.median([v for v in hist_s[k_] if v is not None]))
                   for k_ in range(k)]
            s_bins = tuple(0 if s_vals_eff[k_] <= thr[k_] else 1 for k_ in range(k))
        if not use_s:
            fallback[t] = True
        for o in range(3):
            if not use_s:
                probs[o, t] = elo[o, t]
                continue
            he = np.asarray(hist_elo[o])
            terc = np.quantile(he, [1 / 3, 2 / 3])
            e_bin_t = 0 if elo[o, t] <= terc[0] else (1 if elo[o, t] <= terc[1] else 2)
            he_bin = np.digitize(he, [terc[0], terc[1]])
            ha = np.asarray(hist_actual)
            elo_cell = he_bin == e_bin_t
            cell = elo_cell.copy()
            for k_ in range(k):
                hs = np.asarray([v if v is not None else np.nan for v in hist_s[k_]])
                hs_bin = (hs > thr[k_]).astype(int)
                hs_bin[np.isnan(hs)] = -1  # unavailable -> never matches a real bin
                cell &= hs_bin == s_bins[k_]
            cell_counts = int(cell.sum())
            elo_counts = int(elo_cell.sum())
            if cell_counts >= MIN_CELL:
                probs[o, t] = float(np.mean(ha[cell] == o))
            elif elo_counts >= MIN_CELL:
                probs[o, t] = float(np.mean(ha[elo_cell] == o))
            else:
                probs[o, t] = elo[o, t]
                fallback[t] = True
        total = probs[:, t].sum()
        if total > 0:
            probs[:, t] /= total
        else:
            probs[:, t] = elo[:, t]
            fallback[t] = True
        for k_ in range(k):
            hist_s[k_].append(s_vals[k_])  # aligned with hist_actual (None allowed)
        for o in range(3):
            hist_elo[o].append(elo[o, t])
        hist_actual.append(int(actual_vector[t]))
    return probs, fallback


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # ---- 0) frozen integrity -------------------------------------------------
    frozen_dirs = {"real_epl_base_001": BASELINE_DIR, "diagnosis_epl_001": DIAG1_DIR,
                   "diag_002_tactical_amp": DIAG2_DIR,
                   "diag_003_structure_info": DIAG3_DIR,
                   "diag_004_elo_error": DIAG4_DIR}
    for name, path in frozen_dirs.items():
        (OUT_DIR / f"baseline_manifest_{name}.json").write_text(
            json.dumps(baseline_manifest(Path(path)), indent=2), encoding="utf-8")
    stored = json.loads((DIAG1_DIR / "baseline_manifest.json").read_text(encoding="utf-8"))
    if stored["files"] != baseline_manifest(BASELINE_DIR)["files"]:
        raise RuntimeError("FROZEN BASELINE EXP-REAL-EPL-BASE-001 CHANGED - aborting")
    log("frozen baselines intact (hashes verified)")

    # ---- 1) base vectors (chronological) -------------------------------------
    dataset = HistoricalDataset.load(DATASET_PATH)
    matches = dataset.matches_in_season("2025-26")
    order = {m.match_id: i for i, m in enumerate(matches)}
    frozen = sorted(load_frozen_records(), key=lambda r: order.get(r.match_id, 10 ** 9))
    assert len(frozen) == 380

    elo = np.zeros((3, 380))
    actuals = np.zeros(380, dtype=np.int64)
    for i, r in enumerate(frozen):
        for o in OUTCOMES:
            elo[OUTCOMES.index(o), i] = getattr(r.predictions["elo"], o)
        actuals[i] = actual_idx(r.actual_home_goals, r.actual_away_goals)

    # ---- 2) walk-forward source features (pre-registered) ---------------------
    def shot_quality(i: int) -> Optional[float]:
        r = frozen[i]
        h = feats.rolling_match_stats(dataset.matches, r.home_team, r.kickoff, n=WINDOW)
        a = feats.rolling_match_stats(dataset.matches, r.away_team, r.kickoff, n=WINDOW)
        if h.get("shots_for", 0) < 5 or a.get("shots_for", 0) < 5:
            return None
        return float(h["sot_for"] / h["shots_for"] - a["sot_for"] / a["shots_for"])

    def sot_rate(i: int) -> Optional[float]:
        r = frozen[i]
        h = feats.rolling_match_stats(dataset.matches, r.home_team, r.kickoff, n=WINDOW)
        a = feats.rolling_match_stats(dataset.matches, r.away_team, r.kickoff, n=WINDOW)
        if h.get("n_sot", 0) < 5 or a.get("n_sot", 0) < 5:
            return None
        return float(h["sot_for"] - a["sot_for"])

    def congestion(i: int) -> Optional[float]:
        r = frozen[i]
        return float(feats.fixture_congestion(dataset.matches, r.home_team, r.kickoff)
                     - feats.fixture_congestion(dataset.matches, r.away_team, r.kickoff))

    def home_factor(i: int) -> Optional[float]:
        # time-varying league home-win share before kickoff (operationalization
        # of the design's 'time-varying home factor'; the constant home
        # indicator is already embedded in Elo's fixed +60 adjustment)
        prior = dataset.matches_before(frozen[i].kickoff)
        if len(prior) < MIN_HISTORY:
            return None
        return float(sum(1 for m in prior if m.home_goals > m.away_goals) / len(prior))

    FEATURES = {
        "shot_quality": shot_quality,
        "sot_rate": sot_rate,
        "congestion_14d": congestion,
        "home_factor": home_factor,
    }

    feature_values: Dict[str, List[Optional[float]]] = {}
    for name, fn in FEATURES.items():
        vals = []
        for i in range(380):
            try:
                vals.append(fn(i))
            except Exception:
                vals.append(None)
        feature_values[name] = vals
        n_avail = sum(1 for v in vals if v is not None)
        log(f"feature {name}: available n={n_avail}/380")

    # ---- 3) probes + statistics ------------------------------------------------
    stats: Dict[str, Any] = {}
    stats["meta"] = {"perm_seed": PERM_SEED, "n_perm": N_PERM,
                     "alpha_bonferroni": round(ALPHA, 6),
                     "d_brier_threshold": DBRIER_THRESHOLD,
                     "min_history": MIN_HISTORY, "min_cell": MIN_CELL,
                     "window": WINDOW}
    stats["sources"] = {}
    probes_out: Dict[str, Any] = {}

    brier_elo = brier_3way(elo, actuals)
    logloss_elo = logloss_3way(elo, actuals)
    stats["elo_brier"] = brier_elo
    stats["elo_logloss"] = logloss_elo

    rng = np.random.default_rng(PERM_SEED)
    passed_sources: List[str] = []

    for name in FEATURES:
        s_values = feature_values[name]
        probs, fallback = evaluate_probe([s_values], elo, actuals)
        probes_out[name] = {
            "feature": s_values,
            "probe_probs": [probs[:, i].tolist() for i in range(380)],
            "fallback_to_elo": fallback.astype(int).tolist(),
        }
        brier_p = brier_3way(probs, actuals)
        d_brier = brier_p - brier_elo
        d_ll = logloss_3way(probs, actuals) - logloss_elo
        c_p = murphy_c(probs, elo, actuals)
        half = 190
        d_first = (brier_3way(probs[:, :half], actuals[:half])
                   - brier_3way(elo[:, :half], actuals[:half]))
        d_last = (brier_3way(probs[:, half:], actuals[half:])
                  - brier_3way(elo[:, half:], actuals[half:]))
        split_consistent = bool(d_first < 0 and d_last < 0)

        # PRIMARY permutation: permute the source values across matches
        s_arr = np.asarray([v if v is not None else np.nan for v in s_values])
        s_perm_counts = np.empty(N_PERM)
        c_perm_s = np.empty(N_PERM)
        for rep in range(N_PERM):
            p_rep, _ = evaluate_probe([s_values], elo, actuals,
                                      perms=[rng.permutation(s_arr)])
            s_perm_counts[rep] = brier_3way(p_rep, actuals) - brier_elo
            c_perm_s[rep] = murphy_c(p_rep, elo, actuals)
        p_d_brier = float(np.mean(s_perm_counts <= d_brier))
        p_c = float(np.mean(c_perm_s <= c_p))

        # SECONDARY permutation (design-literal): permute the outcome vector
        out_perm_counts = np.empty(N_PERM)
        for rep in range(N_PERM):
            perm_actual = rng.permutation(actuals)
            p_rep, _ = evaluate_probe([s_values], elo, perm_actual)
            out_perm_counts[rep] = (brier_3way(p_rep, perm_actual)
                                    - brier_3way(elo, perm_actual))
        p_d_brier_outcome_perm = float(np.mean(out_perm_counts <= d_brier))

        success = bool(d_brier <= DBRIER_THRESHOLD and p_d_brier < ALPHA
                       and split_consistent)
        stats["sources"][name] = {
            "d_brier": round(d_brier, 6),
            "d_logloss": round(d_ll, 6),
            "murphy_c": round(c_p, 6),
            "brier_probe": round(brier_p, 6),
            "perm_p_d_brier_source_value": round(p_d_brier, 6),
            "perm_p_murphy_c": round(p_c, 6),
            "perm_p_d_brier_outcome_vector": round(p_d_brier_outcome_perm, 6),
            "split_half_first190": round(d_first, 6),
            "split_half_last190": round(d_last, 6),
            "split_half_consistent": split_consistent,
            "fallback_share": round(float(np.mean(fallback)), 4),
            "success": success,
            "verdict": "EVIDENCE" if success else "INSUFFICIENT EVIDENCE",
        }
        if success:
            passed_sources.append(name)
        log(f"{name}: d_Brier={d_brier:+.5f} p={p_d_brier:.4f} "
            f"split=({d_first:+.4f},{d_last:+.4f}) fallback={float(np.mean(fallback)):.2f} "
            f"-> {stats['sources'][name]['verdict']}")

    # ---- 4) combination probes (pre-registered: only for passed sources) -----
    stats["combinations"] = {"computed": bool(passed_sources), "detail": {}}
    if passed_sources:
        for i in range(len(passed_sources)):
            for j in range(i + 1, len(passed_sources)):
                s1, s2 = passed_sources[i], passed_sources[j]
                comb_name = f"{s1}+{s2}"
                pair = [feature_values[s1], feature_values[s2]]
                p_comb, _ = evaluate_probe(pair, elo, actuals)
                d_comb = brier_3way(p_comb, actuals) - brier_elo
                d_single_sum = (stats["sources"][s1]["d_brier"]
                                + stats["sources"][s2]["d_brier"])
                stats["combinations"]["detail"][comb_name] = {
                    "d_brier_combined": round(d_comb, 6),
                    "sum_of_single_d_brier": round(d_single_sum, 6),
                    "direction": ("combined >= sum of singles"
                                  if d_comb <= d_single_sum
                                  else "combined < sum of singles"),
                    "note": "direction only; not a judgment criterion",
                }
                log(f"combination {comb_name}: d_Brier={d_comb:+.5f} "
                    f"(sum singles {d_single_sum:+.5f})")
    else:
        log("combination probes: not computed (no single source passed)")

    # ---- 5) write outputs -----------------------------------------------------
    (OUT_DIR / "probes.json").write_text(json.dumps(probes_out, indent=1),
                                         encoding="utf-8")
    (OUT_DIR / "stats.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")

    registry = ExperimentRegistry(OUT_DIR / "experiments.jsonl")
    registry.record(
        data_version=data_version(DATASET_PATH),
        random_seed=PERM_SEED,
        train_period="walk-forward (frozen baseline reference)",
        test_period="2025-26",
        models=sorted(FEATURES),
        matches_evaluated=380,
        metrics={k: {"d_brier": v["d_brier"], "verdict": v["verdict"]}
                 for k, v in stats["sources"].items()},
        synthetic_data=False,
        market_data=False,
        notes=[
            "EXP-DIAG-EPL-005 (DIAG-005): Information Source Incremental Value",
            "strictly follows docs/DIAG_005_INFO_SOURCE_DESIGN.md pre-registration",
            "conditional-calibration probe over frozen Elo probs; no training, "
            "no weights, no production changes",
            "primary permutation permutes SOURCE values (operationalizes H0 "
            "'source has no Elo-extra increment'); outcome-vector permutation "
            "reported as secondary (design-literal variant)",
            "xG/xGA proxy limitation recorded, no probe; lineups & injuries "
            "DATA_UNAVAILABLE, no inference; closing_odds excluded (no-market)",
            f"passed: {passed_sources or 'none'} (see stats.json)",
        ],
    )
    log("registry entry EXP-DIAG-EPL-005 written")
    log(f"DONE in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
