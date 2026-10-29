"""EXP-DIAG-EPL-008 (DIAG-008) execution: Understat rolling xG/xGA
incremental-value validation over the frozen Elo baseline.

Strictly reuses the DIAG-005 conditional-calibration probe framework - the
probe/metrics/permutation functions below are VERBATIM copies of
scripts/exp_diag_005_run.py (framework frozen, not redesigned for xG).

Resilience design (operational, not a framework change):
  - each source runs as its OWN process with its OWN fresh rng(default_rng(
    20240101)) -> per-source permutation draws are the first 20,000 draws of
    the pre-registered seed stream (identical iid stream per source; the
    DIAG-005 sequential run drew from the same seed with a shared cursor -
    both are unbiased Monte Carlo estimates of the same quantities).
  - each source writes partial_{source}.json immediately on completion;
    `--assemble` merges the partials into probes.json / stats.json and writes
    the registry entry.  Interrupted runs can be resumed per source.

Sources (from the DATA-002 FROZEN rolling CSV, data_version
ae9e746b4654d8addb582bb3acf445ccbf575c72c31ede3f4f93be39f25cfa27,
window=10, strictly datetime<kickoff):
  1. xg_for_diff      = home_xg_for_roll - away_xg_for_roll
  2. xg_against_diff  = home_xg_against_roll - away_xg_against_roll
  3. xg_net_diff      = (home_xgf-home_xga) - (away_xgf-away_xga)
  4. home_xg_for      = home_xg_for_roll
  5. away_xg_for      = away_xg_for_roll

Success criteria (pre-registered): d_Brier <= -0.003 AND p < 0.0071 AND
split-half AND valid sample >= 100 AND fallback <= 30%.
No single source passes -> NO combination probe.

Usage:
  python scripts/exp_diag_008_run.py --source xg_for_diff   (one per process)
  python scripts/exp_diag_008_run.py --assemble             (merge + registry)
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from football_simulation.backtest.diagnosis import baseline_manifest
from football_simulation.backtest.experiments import ExperimentRegistry, data_version
from football_simulation.backtest.models import PredictionRecord
from football_simulation.data.historical.etl import HistoricalDataset

BASELINE_DIR = Path("backtest_output/real_epl_base_001")
DIAG1_DIR = Path("backtest_output/diagnosis_epl_001")
DIAG2_DIR = Path("backtest_output/diag_002_tactical_amp")
DIAG3_DIR = Path("backtest_output/diag_003_structure_info")
DIAG4_DIR = Path("backtest_output/diag_004_elo_error")
DIAG5_DIR = Path("backtest_output/diag_005_info_source")
OUT_DIR = Path("backtest_output/diag_008_xg_validation")
DATASET_PATH = Path("data/historical/epl_2025_26.json")
XG_ROLLING = Path("data/xg/understat/normalized/rolling_2025.csv")
XG_MANIFEST = Path("data/xg/understat/MANIFEST.json")

PERM_SEED = 20240101
N_PERM = 10_000
ALPHA = 0.05 / 7
DBRIER_THRESHOLD = -0.003
MIN_HISTORY = 30
MIN_CELL = 20
MIN_VALID_SAMPLE = 100
MAX_FALLBACK = 0.30

XG_DATA_VERSION = ("ae9e746b4654d8addb582bb3acf445ccbf575c72c31e"
                   "de3f4f93be39f25cfa27")
XG_FINGERPRINT = "ae9e746b4654d8ad"

SOURCES = ["xg_for_diff", "xg_against_diff", "xg_net_diff",
           "home_xg_for", "away_xg_for"]
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


# ---------------------------------------------------------------------------
# VERBATIM from exp_diag_005_run.py (framework frozen)
# ---------------------------------------------------------------------------

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
    k = len(feature_lists)
    n = elo.shape[1]
    probs = np.zeros((3, n))
    fallback = np.zeros(n, dtype=bool)
    hist_elo: List[List[float]] = [[], [], []]
    hist_s: List[List[Optional[float]]] = [[] for _ in range(k)]
    hist_actual: List[int] = []

    for t in range(n):
        s_vals = [feature_lists[k_][t] for k_ in range(k)]
        s_vals_eff = []
        for k_ in range(k):
            if perms is not None and perms[k_] is not None:
                s_vals_eff.append(perms[k_][t])
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
                hs_bin[np.isnan(hs)] = -1
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
            hist_s[k_].append(s_vals[k_])
        for o in range(3):
            hist_elo[o].append(elo[o, t])
        hist_actual.append(int(actual_vector[t]))
    return probs, fallback


# ---------------------------------------------------------------------------

def _f(v: str) -> Optional[float]:
    v = v.strip()
    return float(v) if v not in ("", "None") else None


def load_base() -> Tuple[np.ndarray, np.ndarray, Dict[str, List[Optional[float]]]]:
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

    roll_by_key: Dict[Tuple[str, str, str], Dict[str, Optional[float]]] = {}
    with XG_ROLLING.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            roll_by_key[(row["datetime_utc"][:10], row["home_team"],
                         row["away_team"])] = {
                "hgf": _f(row["home_xg_for_roll"]),
                "hga": _f(row["home_xg_against_roll"]),
                "agf": _f(row["away_xg_for_roll"]),
                "aga": _f(row["away_xg_against_roll"]),
            }
    feats: Dict[str, List[Optional[float]]] = {k: [] for k in SOURCES}
    for r in frozen:
        key = (r.kickoff.isoformat()[:10], r.home_team, r.away_team)
        v = roll_by_key.get(key)
        if v is None:
            raise RuntimeError(f"no xG rolling row for {key}")
        hgf, hga, agf, aga = v["hgf"], v["hga"], v["agf"], v["aga"]
        feats["xg_for_diff"].append(
            round(hgf - agf, 6) if hgf is not None and agf is not None else None)
        feats["xg_against_diff"].append(
            round(hga - aga, 6) if hga is not None and aga is not None else None)
        feats["xg_net_diff"].append(
            round((hgf - hga) - (agf - aga), 6)
            if None not in (hgf, hga, agf, aga) else None)
        feats["home_xg_for"].append(hgf)
        feats["away_xg_for"].append(agf)
    return elo, actuals, feats


def run_source(name: str) -> None:
    elo, actuals, feats = load_base()
    s_values = feats[name]
    n_valid = sum(1 for v in s_values if v is not None)

    rng = np.random.default_rng(PERM_SEED)

    probs, fallback = evaluate_probe([s_values], elo, actuals)
    brier_elo = brier_3way(elo, actuals)
    brier_p = brier_3way(probs, actuals)
    d_brier = brier_p - brier_elo
    d_ll = logloss_3way(probs, actuals) - logloss_3way(elo, actuals)
    c_p = murphy_c(probs, elo, actuals)
    half = 190
    d_first = (brier_3way(probs[:, :half], actuals[:half])
               - brier_3way(elo[:, :half], actuals[:half]))
    d_last = (brier_3way(probs[:, half:], actuals[half:])
              - brier_3way(elo[:, half:], actuals[half:]))
    split_consistent = bool(d_first < 0 and d_last < 0)
    fallback_rate = float(np.mean(fallback))

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

    out_perm_counts = np.empty(N_PERM)
    for rep in range(N_PERM):
        perm_actual = rng.permutation(actuals)
        p_rep, _ = evaluate_probe([s_values], elo, perm_actual)
        out_perm_counts[rep] = (brier_3way(p_rep, perm_actual)
                                - brier_3way(elo, perm_actual))
    p_d_brier_outcome_perm = float(np.mean(out_perm_counts <= d_brier))

    success = bool(d_brier <= DBRIER_THRESHOLD and p_d_brier < ALPHA
                   and split_consistent and n_valid >= MIN_VALID_SAMPLE
                   and fallback_rate <= MAX_FALLBACK)

    result = {
        "source": name,
        "feature": s_values,
        "probe_probs": [probs[:, i].tolist() for i in range(380)],
        "fallback_to_elo": fallback.astype(int).tolist(),
        "stats": {
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
            "valid_sample": n_valid,
            "fallback_rate": round(fallback_rate, 4),
            "success": success,
            "verdict": "EVIDENCE" if success else "INSUFFICIENT EVIDENCE",
        },
    }
    (OUT_DIR / f"partial_{name}.json").write_text(
        json.dumps(result, indent=1), encoding="utf-8")
    log(f"{name}: d_Brier={d_brier:+.5f} p={p_d_brier:.4f} "
        f"split=({d_first:+.4f},{d_last:+.4f}) valid={n_valid} "
        f"fallback={fallback_rate:.2f} -> {result['stats']['verdict']} "
        f"(partial written)")


def assemble() -> None:
    meta = {"perm_seed": PERM_SEED, "n_perm": N_PERM,
            "alpha_bonferroni": round(ALPHA, 6),
            "d_brier_threshold": DBRIER_THRESHOLD,
            "min_history": MIN_HISTORY, "min_cell": MIN_CELL,
            "min_valid_sample": MIN_VALID_SAMPLE,
            "max_fallback": MAX_FALLBACK,
            "xg_data_version": XG_DATA_VERSION,
            "xg_fingerprint": XG_FINGERPRINT,
            "rng_note": ("per-source fresh rng(default_rng(20240101)); identical "
                         "iid stream per source (see module docstring)")}
    sources: Dict[str, Any] = {}
    probes_out: Dict[str, Any] = {}
    missing = []
    for name in SOURCES:
        path = OUT_DIR / f"partial_{name}.json"
        if not path.exists():
            missing.append(name)
            continue
        part = json.loads(path.read_text(encoding="utf-8"))
        sources[name] = part["stats"]
        probes_out[name] = {"feature": part["feature"],
                            "probe_probs": part["probe_probs"],
                            "fallback_to_elo": part["fallback_to_elo"]}
    if missing:
        raise SystemExit(f"missing partials: {missing}")

    elo, actuals, _ = load_base()
    passed = [k for k, v in sources.items() if v["success"]]
    stats = {"meta": meta, "elo_brier": brier_3way(elo, actuals),
             "elo_logloss": logloss_3way(elo, actuals),
             "sources": sources,
             "combinations": {"computed": bool(passed), "detail": {},
                              "note": ""}}
    if passed:
        stats["combinations"]["note"] = (
            "single source(s) passed; combination probe = joint-grid evaluation "
            "(direction only, not a judgment criterion) - follow-up step")
    else:
        stats["combinations"]["note"] = ("no single source passed -> combination "
                                         "probe NOT executed (pre-registered rule)")

    (OUT_DIR / "probes.json").write_text(json.dumps(probes_out, indent=1),
                                         encoding="utf-8")
    (OUT_DIR / "stats.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")

    registry = ExperimentRegistry(OUT_DIR / "experiments.jsonl")
    registry.record(
        data_version=data_version(DATASET_PATH),
        random_seed=PERM_SEED,
        train_period="walk-forward (frozen baseline reference)",
        test_period="2025-26",
        models=SOURCES,
        matches_evaluated=380,
        metrics={k: {"d_brier": v["d_brier"], "verdict": v["verdict"]}
                 for k, v in sources.items()},
        synthetic_data=False,
        market_data=False,
        notes=[
            "EXP-DIAG-EPL-008 (DIAG-008): Understat rolling xG/xGA incremental "
            "value validation over frozen Elo",
            "probe framework VERBATIM from DIAG-005 (exp_diag_005_run.py); "
            "not redesigned for xG",
            "features from DATA-002 frozen rolling_2025.csv (window=10, "
            "strictly datetime<kickoff, no post-match xG, no re-fetch)",
            "xg data_version=ae9e746b4654d8addb582bb3acf445ccbf575c72c31ede3f4f"
            "93be39f25cfa27 (fingerprint ae9e746b4654d8ad)",
            "success criteria: d_Brier<=-0.003 AND p<0.0071 AND split-half AND "
            "valid sample>=100 AND fallback<=30%",
            "per-source fresh rng(20240101); identical iid stream per source",
            f"passed: {passed or 'none'} (see stats.json)",
        ],
    )
    log("registry entry EXP-DIAG-EPL-008 written")
    log("assemble DONE")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=None, choices=SOURCES)
    parser.add_argument("--assemble", action="store_true")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.assemble:
        assemble()
        return
    if args.source is None:
        raise SystemExit("specify --source NAME or --assemble")

    frozen_dirs = {"real_epl_base_001": BASELINE_DIR, "diagnosis_epl_001": DIAG1_DIR,
                   "diag_002_tactical_amp": DIAG2_DIR,
                   "diag_003_structure_info": DIAG3_DIR,
                   "diag_004_elo_error": DIAG4_DIR,
                   "diag_005_info_source": DIAG5_DIR}
    for dname, path in frozen_dirs.items():
        mf = OUT_DIR / f"baseline_manifest_{dname}.json"
        if not mf.exists():
            mf.write_text(json.dumps(baseline_manifest(Path(path)), indent=2),
                          encoding="utf-8")
    stored = json.loads((DIAG1_DIR / "baseline_manifest.json").read_text(encoding="utf-8"))
    if stored["files"] != baseline_manifest(BASELINE_DIR)["files"]:
        raise RuntimeError("FROZEN BASELINE EXP-REAL-EPL-BASE-001 CHANGED - aborting")
    xg_manifest = json.loads(XG_MANIFEST.read_text(encoding="utf-8"))
    if xg_manifest["data_version"] != XG_DATA_VERSION:
        raise RuntimeError("XG DATA VERSION MISMATCH - aborting")
    log(f"frozen baselines intact; xG fingerprint {XG_FINGERPRINT} locked")

    run_source(args.source)


if __name__ == "__main__":
    main()
