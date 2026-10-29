# -*- coding: utf-8 -*-
"""Score probability matrix derived from devigged market probabilities.

STATUS: derived reparameterization of the validated market baseline
(M4/O2 Shin devig), NOT an independently validated signal. The full-score
distribution is obtained by

  1. fitting a Dixon-Coles bivariate Poisson (lambda_home, lambda_away, rho)
     to the devigged 1X2 (and O/U 2.5 when available) probabilities, then
  2. raking (iterative proportional fitting) the cell probabilities so the
     aggregates reproduce the devigged targets exactly.

Invariant (mirrors P1 in PREDICTION_MATRIX.md): after raking, matrix
aggregates for home/draw/away (and over/under 2.5 when a target is given)
match the devigged probabilities up to numerical tolerance, and the matrix
sums to 1. Cells are never negative. Research use only; no betting.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np

MODULE_VERSION = "score_matrix 0.1.0"
DEFAULT_MAX_GOALS = 8  # matrix covers 0..8 goals per side; tail beyond is negligible
_RHO_LIMIT = 0.15      # Dixon-Coles rho is empirically small; keep the fit tame
_RAKE_TOL = 1e-12
_RAKE_MAX_ITER = 2000

INVARIANT_NOTE = (
    "aggregates reproduce the devigged market probabilities (M4/O2 Shin) exactly "
    "up to 1e-9; the cell distribution is a Dixon-Coles bivariate-Poisson "
    "reparameterization of those probabilities, not an independently validated "
    "signal; research use only, no betting"
)


# ---------------------------------------------------------------- Dixon-Coles
def _tau(h: int, a: int, lh: float, la: float, rho: float) -> float:
    """Dixon-Coles low-score dependence adjustment tau(h, a)."""
    if h == 0 and a == 0:
        return 1.0 - lh * la * rho
    if h == 0 and a == 1:
        return 1.0 + lh * rho
    if h == 1 and a == 0:
        return 1.0 + la * rho
    if h == 1 and a == 1:
        return 1.0 - rho
    return 1.0


def _dc_matrix(lh: float, la: float, rho: float, max_goals: int) -> np.ndarray:
    """Untruncated-normalized DC score matrix for h,a in 0..max_goals."""
    hs = np.arange(max_goals + 1)
    log_fact = np.array([math.lgamma(k + 1) for k in hs])
    logp_h = -lh + hs * math.log(lh) - log_fact
    logp_a = -la + hs * math.log(la) - log_fact
    m = np.exp(logp_h[:, None] + logp_a[None, :])
    for h in range(min(2, max_goals + 1)):
        for a in range(min(2, max_goals + 1)):
            m[h, a] *= max(_tau(h, a, lh, la, rho), 1e-12)
    return m / m.sum()


def _aggregates(m: np.ndarray) -> dict[str, float]:
    n = m.shape[0]
    idx = np.arange(n)
    home = float(np.tril(m, -1).sum())          # h > a  (rows = home goals)
    draw = float(np.trace(m))
    away = float(np.triu(m, 1).sum())           # a > h
    total = idx[:, None] + idx[None, :]
    over = float(m[total > 2.5].sum())
    return {"home": home, "draw": draw, "away": away, "over25": over}


# ------------------------------------------------------------- optimization
def _nelder_mead(f, x0, step=0.25, iters=600) -> list[float]:
    n = len(x0)
    simplex = [list(x0)]
    for i in range(n):
        vertex = list(x0)
        vertex[i] += step
        simplex.append(vertex)
    for _ in range(iters):
        simplex.sort(key=f)
        if abs(f(simplex[0]) - f(simplex[-1])) < 1e-15:
            break
        centroid = [sum(v[i] for v in simplex[:-1]) / n for i in range(n)]
        worst = simplex[-1]
        refl = [c + (c - w) for c, w in zip(centroid, worst)]
        if f(refl) < f(simplex[0]):
            expn = [c + 2.0 * (c - w) for c, w in zip(centroid, worst)]
            simplex[-1] = expn if f(expn) < f(refl) else refl
        elif f(refl) < f(simplex[-2]):
            simplex[-1] = refl
        else:
            contr = [c + 0.5 * (w - c) for c, w in zip(centroid, worst)]
            if f(contr) < f(worst):
                simplex[-1] = contr
            else:
                best = simplex[0]
                simplex = [best] + [[b + 0.5 * (v - b) for b, v in zip(best, v)]
                                    for v in simplex[1:]]
    return simplex[0]


def _fit_dc(targets: dict[str, float], max_goals: int) -> tuple[np.ndarray, dict[str, float]]:
    """Fit DC parameters to targets; return (matrix, params)."""
    p_h, p_d, p_a = targets["home"], targets["draw"], targets["away"]
    p_o = targets.get("over25")
    base_total = 2.7
    share = p_h / max(p_h + p_a, 1e-9)

    def objective(x: list[float]) -> float:
        lh = math.exp(x[0])
        la = math.exp(x[1])
        rho = _RHO_LIMIT * math.tanh(x[2])
        agg = _aggregates(_dc_matrix(lh, la, rho, max_goals))
        err = (agg["home"] - p_h) ** 2 + (agg["draw"] - p_d) ** 2 + (agg["away"] - p_a) ** 2
        if p_o is not None:
            err += (agg["over25"] - p_o) ** 2
        return err

    lh0 = max(base_total * share, 0.05)
    la0 = max(base_total * (1.0 - share), 0.05)
    x0 = [math.log(lh0), math.log(la0), math.atanh(-0.03 / _RHO_LIMIT)]
    x = _nelder_mead(objective, x0)
    lh, la = math.exp(x[0]), math.exp(x[1])
    rho = _RHO_LIMIT * math.tanh(x[2])
    m = _dc_matrix(lh, la, rho, max_goals)
    return m, {"lambda_home": lh, "lambda_away": la, "rho": rho}


def _rake(m: np.ndarray, targets: dict[str, float]) -> tuple[np.ndarray, float, bool]:
    """Scale regions so aggregates match targets exactly (iterative proportional fitting)."""
    p_h, p_d, p_a = targets["home"], targets["draw"], targets["away"]
    p_o = targets.get("over25")
    n = m.shape[0]
    idx = np.arange(n)
    total = idx[:, None] + idx[None, :]
    over_mask = total > 2.5
    m = m.copy()
    for _ in range(_RAKE_MAX_ITER):
        home_m, draw_m, away_m = np.tril(m, -1), np.eye(n) * m, np.triu(m, 1)
        h_sum, d_sum, a_sum = home_m.sum(), float(np.trace(m)), away_m.sum()
        if h_sum > 0:
            m[np.tril_indices(n, -1)] *= p_h / h_sum
        if d_sum > 0:
            m[np.diag_indices(n)] *= p_d / d_sum
        if a_sum > 0:
            m[np.triu_indices(n, 1)] *= p_a / a_sum
        if p_o is not None:
            o_sum, u_sum = m[over_mask].sum(), m[~over_mask].sum()
            if o_sum > 0 and u_sum > 0:
                m[over_mask] *= p_o / o_sum
                m[~over_mask] *= (1.0 - p_o) / u_sum
        agg = _aggregates(m)
        resid = max(abs(agg["home"] - p_h), abs(agg["draw"] - p_d),
                    abs(agg["away"] - p_a))
        if p_o is not None:
            resid = max(resid, abs(agg["over25"] - p_o))
        if resid < _RAKE_TOL:
            break
    m = m / m.sum()
    agg = _aggregates(m)
    resid = max(abs(agg["home"] - p_h), abs(agg["draw"] - p_d), abs(agg["away"] - p_a))
    if p_o is not None:
        resid = max(resid, abs(agg["over25"] - p_o))
    return m, resid, resid < 1e-9


# ------------------------------------------------------------------- public
def derive_score_matrix(p_home: float, p_draw: float, p_away: float,
                        p_over: Optional[float] = None,
                        max_goals: int = DEFAULT_MAX_GOALS) -> dict[str, Any]:
    """Derive a full score probability matrix from devigged probabilities.

    p_home/p_draw/p_away must be positive and sum to ~1 (devigged market
    output). p_over, when given, is the devigged P(total goals > 2.5).
    Returns a JSON-able prediction_output-style block.
    """
    p_home, p_draw, p_away = float(p_home), float(p_draw), float(p_away)
    if min(p_home, p_draw, p_away) <= 0:
        raise ValueError("probabilities must be strictly positive")
    s = p_home + p_draw + p_away
    if abs(s - 1.0) > 0.01:
        raise ValueError(f"1X2 probabilities must sum to 1 (got {s:.6f})")
    p_home, p_draw, p_away = p_home / s, p_draw / s, p_away / s
    if p_over is not None:
        p_over = float(p_over)
        if not 0.0 < p_over < 1.0:
            raise ValueError(f"p_over must be in (0,1) exclusive (got {p_over})")
        p_over = min(max(p_over, 1e-6), 1.0 - 1e-6)

    targets: dict[str, float] = {"home": p_home, "draw": p_draw, "away": p_away}
    if p_over is not None:
        targets["over25"] = p_over

    fitted, params = _fit_dc(targets, max_goals)
    m, resid, converged = _rake(fitted, targets)
    agg = _aggregates(m)

    n = m.shape[0]
    goals = np.arange(n)
    xg_home = float((m.sum(axis=1) * goals).sum())
    xg_away = float((m.sum(axis=0) * goals).sum())
    btts = float(m[1:, 1:].sum())

    cells = [((h, a), float(m[h, a])) for h in range(n) for a in range(n)]
    cells.sort(key=lambda c: -c[1])
    top = [{"score": f"{h}-{a}", "home": h, "away": a, "probability": p}
           for (h, a), p in cells[:10]]

    return {
        "module_version": MODULE_VERSION,
        "status": "VALID" if converged else "APPROXIMATE",
        "derived_from": {"home": p_home, "draw": p_draw, "away": p_away, "over25": p_over},
        "method": {
            "model": "dixon-coles bivariate poisson",
            "fit": "nelder-mead + raking (iterative proportional fitting)",
            **{k: round(v, 6) for k, v in params.items()},
            "raking_converged": converged,
            "max_aggregate_residual": float(f"{resid:.3e}"),
        },
        "max_goals": max_goals,
        "matrix": [[round(float(m[h, a]), 8) for a in range(n)] for h in range(n)],
        "aggregates": {
            "home": round(agg["home"], 8), "draw": round(agg["draw"], 8),
            "away": round(agg["away"], 8),
            "over25": round(agg["over25"], 8), "under25": round(1.0 - agg["over25"], 8),
            "btts_yes": round(btts, 8),
        },
        "top_scorelines": top,
        "expected_goals": {
            "home": round(xg_home, 4), "away": round(xg_away, 4),
            "total": round(xg_home + xg_away, 4),
        },
        "evidence_level": "Derived",
        "invariant_note": INVARIANT_NOTE,
    }
