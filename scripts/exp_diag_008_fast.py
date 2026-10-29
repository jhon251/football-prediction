"""EXP-DIAG-EPL-008 (DIAG-008) FAST executor: vectorized implementation of the
EXACT same probe math as scripts/exp_diag_005_run.py (verbatim framework).

The probe DESIGN (formulas, thresholds, fallback chain, statistics) is
identical to DIAG-005; this module only replaces the inner Python loops with
a vectorized implementation, and VERIFIES per-source that the observed probe
probabilities match the verbatim implementation to <1e-12 before writing any
partial.  Permutation draws: per-source fresh rng(default_rng(20240101)).

Usage:
  python scripts/exp_diag_008_fast.py --source xg_for_diff
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from exp_diag_008_run import (  # noqa: E402
    ALPHA, DBRIER_THRESHOLD, MAX_FALLBACK, MIN_CELL, MIN_HISTORY,
    MIN_VALID_SAMPLE, N_PERM, OUT_DIR, PERM_SEED, SOURCES,
    brier_3way, evaluate_probe, load_base, logloss_3way, murphy_c,
)

MAX_PROB_DIFF = 1e-12  # consistency tolerance vs the verbatim implementation


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def _prefix_median(values: np.ndarray) -> np.ndarray:
    """median of non-None values in values[0:t] for every t."""
    n = len(values)
    out = np.full(n, np.nan)
    for t in range(1, n):
        win = values[:t]
        win = win[~np.isnan(win)]
        out[t] = float(np.median(win)) if win.size else np.nan
    return out


def _count_non_none_before(values: np.ndarray) -> np.ndarray:
    return np.concatenate([[0], np.cumsum(~np.isnan(values))[:-1]])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=None, choices=SOURCES)
    args = parser.parse_args()
    if args.source is None:
        raise SystemExit("specify --source NAME")
    name = args.source
    t0 = time.time()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    elo, actuals, feats = load_base()
    s_values = feats[name]
    s_arr = np.asarray([v if v is not None else np.nan for v in s_values])
    n_valid = int(np.sum(~np.isnan(s_arr)))
    n = 380

    # ---- fixed quantities (identical math to the verbatim probe) ----
    thr = _prefix_median(s_arr)
    nn_before = _count_non_none_before(s_arr)
    use_s_fixed = (np.arange(n) >= MIN_HISTORY) & (nn_before >= MIN_HISTORY)

    F_o = np.zeros((3, n, n), dtype=bool)
    for o in range(3):
        F_o[o] = (actuals[:, None] == o)

    E_mask = np.zeros((3, n, n), dtype=bool)   # [o,t,i]: elo-bin(i) == elo-bin(t)
    elo_cnt = np.zeros((3, n), dtype=np.int64)
    elo_freq = np.zeros((3, n), dtype=np.int64)
    for o in range(3):
        eo = elo[o]
        for t in range(1, n):
            terc = np.quantile(eo[:t], [1 / 3, 2 / 3])
            e_bin_t = 0 if eo[t] <= terc[0] else (1 if eo[t] <= terc[1] else 2)
            E_mask[o, t] = np.digitize(eo, [terc[0], terc[1]]) == e_bin_t
            cnt = np.cumsum(E_mask[o, t])
            elo_cnt[o, t] = cnt[t - 1]
            fr = np.cumsum(E_mask[o, t] & (actuals == o))
            elo_freq[o, t] = fr[t - 1]
    log(f"{name}: precompute done ({time.time() - t0:.0f}s)")

    def probe_from_eff(s_eff: np.ndarray, actual_vector: np.ndarray):
        """Vectorized probe for one effective source assignment and one actual
        vector.  Mathematically identical to evaluate_probe."""
        isnan_eff = np.isnan(s_eff)
        use_s = use_s_fixed & ~isnan_eff
        # orientation [t, i]: (evaluation match t, history match i)
        s_gt = (s_eff[None, :] > thr[:, None]) & ~isnan_eff[None, :]
        s_le = (s_eff[None, :] <= thr[:, None]) & ~isnan_eff[None, :]
        b_t = (s_eff > thr).astype(np.int64)
        probs = np.zeros((3, n))
        fallback = np.zeros(n, dtype=bool)
        fallback[~use_s] = True
        for o in range(3):
            Em = E_mask[o]
            Fo = (actual_vector[None, :] == o)
            cnt0 = np.cumsum(Em & s_le, axis=1)
            cnt1 = np.cumsum(Em & s_gt, axis=1)
            fr0 = np.cumsum(Em & s_le & Fo, axis=1)
            fr1 = np.cumsum(Em & s_gt & Fo, axis=1)
            for t in range(1, n):
                if not use_s[t]:
                    probs[o, t] = elo[o, t]
                    continue
                b = b_t[t]
                cc = int((cnt1 if b else cnt0)[t, t - 1])
                cf = int((fr1 if b else fr0)[t, t - 1])
                ec = int(elo_cnt[o, t])
                ef = int(elo_freq[o, t])
                if cc >= MIN_CELL:
                    probs[o, t] = cf / cc
                elif ec >= MIN_CELL:
                    probs[o, t] = ef / ec
                else:
                    probs[o, t] = elo[o, t]
                    fallback[t] = True
        for t in range(n):
            total = probs[:, t].sum()
            if total > 0:
                probs[:, t] /= total
            else:
                probs[:, t] = elo[:, t]
                fallback[t] = True
        return probs, fallback

    # ---- consistency check vs the verbatim implementation ----
    obs_v, fall_v = evaluate_probe([s_values], elo, actuals)
    obs_f, fall_f = probe_from_eff(s_arr, actuals)
    max_diff = float(np.max(np.abs(obs_v - obs_f)))
    if max_diff >= MAX_PROB_DIFF:
        raise RuntimeError(f"VECTORIZED PROBE DIVERGES from verbatim "
                           f"(max|d|={max_diff:.3e}) - aborting")
    fall_match = bool(np.array_equal(fall_v, fall_f))
    log(f"{name}: consistency vs verbatim probe OK "
        f"(max|d|={max_diff:.2e}, fallback match={fall_match})")

    probs, fallback = obs_f, fall_f
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

    rng = np.random.default_rng(PERM_SEED)

    # PRIMARY: source-value permutation
    s_perm_counts = np.empty(N_PERM)
    c_perm_s = np.empty(N_PERM)
    for rep in range(N_PERM):
        p_rep, _ = probe_from_eff(rng.permutation(s_arr), actuals)
        s_perm_counts[rep] = brier_3way(p_rep, actuals) - brier_elo
        c_perm_s[rep] = murphy_c(p_rep, elo, actuals)
    p_d_brier = float(np.mean(s_perm_counts <= d_brier))
    p_c = float(np.mean(c_perm_s <= c_p))

    # SECONDARY: outcome-vector permutation (transparency)
    out_perm_counts = np.empty(N_PERM)
    for rep in range(N_PERM):
        perm_actual = rng.permutation(actuals)
        p_rep, _ = probe_from_eff(s_arr, perm_actual)
        out_perm_counts[rep] = (brier_3way(p_rep, perm_actual)
                                - brier_3way(elo, perm_actual))
    p_d_brier_outcome_perm = float(np.mean(out_perm_counts <= d_brier))

    success = bool(d_brier <= DBRIER_THRESHOLD and p_d_brier < ALPHA
                   and split_consistent and n_valid >= MIN_VALID_SAMPLE
                   and fallback_rate <= MAX_FALLBACK)

    result = {
        "source": name,
        "feature": s_values,
        "probe_probs": [probs[:, i].tolist() for i in range(n)],
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
            "vectorized_consistency_max_diff": max_diff,
        },
    }
    (OUT_DIR / f"partial_{name}.json").write_text(
        json.dumps(result, indent=1), encoding="utf-8")
    log(f"{name}: d_Brier={d_brier:+.5f} p={p_d_brier:.4f} "
        f"split=({d_first:+.4f},{d_last:+.4f}) valid={n_valid} "
        f"fallback={fallback_rate:.2f} -> {result['stats']['verdict']} "
        f"(partial written, {time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
