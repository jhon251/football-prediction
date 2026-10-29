# -*- coding: utf-8 -*-
"""Market baseline methods M1..M5 (1X2) and O1..O4 (OU25) — minimal prediction module.

REUSE POLICY: the Shin solver below is the same algorithm as
backtest_output/experiments/phase4a_market_baseline/run_phase4a.py::shin_probs
(the Phase 4A validated implementation). tests/prediction/test_market.py pins
numerical equivalence against that file so this module can never silently
diverge from the validated baseline. No calibration layer (5.1-A CLOSED),
no closing odds (5.1-D CONDITIONAL, never SAFE), no ML.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

BOOKS_1X2 = ["B365", "BFD", "BMGM", "BV", "BW", "CL", "IW", "LB", "PS", "VC", "WH", "BFE", "1XB"]
BOOKS_OU = ["B365", "PS", "GB", "BFE"]
FTR_LEGS = ("H", "D", "A")
OU_LEGS = (">2.5", "<2.5")


# ---------------- Shin solver (verbatim algorithm from phase4a run_phase4a.py) ----------------
def shin_probs(q):
    """q: (n, k) raw implied probs (1/odds). Returns (p, z) with z=0 fallback."""
    q = np.asarray(q, dtype=float)
    n, k = q.shape
    out_p = np.empty_like(q)
    out_z = np.zeros(n)
    s = q.sum(axis=1)
    ok = s > 1.0 + 1e-12
    # z=0 case (no overround): normalized
    out_p[~ok] = q[~ok] / np.maximum(s[~ok, None], 1e-12)
    if ok.any():
        qi = q[ok]
        zmax = np.min(qi / (1.0 + qi), axis=1)  # per-match upper bound
        lo = np.zeros(qi.shape[0])
        hi = zmax.copy()
        for _ in range(100):
            z = 0.5 * (lo + hi)
            inner = qi * ((1.0 - z[:, None]) * qi - z[:, None])
            inner = np.maximum(inner, 0.0)
            total = np.sqrt(inner).sum(axis=1)
            above = total > 1.0
            lo = np.where(above, z, lo)
            hi = np.where(above, hi, z)
        z = 0.5 * (lo + hi)
        inner = np.maximum(qi * ((1.0 - z[:, None]) * qi - z[:, None]), 0.0)
        p = np.sqrt(inner)
        psum = p.sum(axis=1, keepdims=True)
        ok_psum = psum[:, 0] > 1e-9
        # fallback to normalized where solver degenerated
        out_p[ok] = np.where(ok_psum[:, None], p / np.maximum(psum, 1e-12),
                             qi / np.maximum(qi.sum(axis=1, keepdims=True), 1e-12))
        out_z[ok] = z
    return out_p, out_z


def simple_norm(q):
    """M1/M3/O1/O3 style normalization."""
    q = np.asarray(q, dtype=float)
    return q / q.sum(axis=1, keepdims=True)


@dataclass
class MethodResult:
    """Result of one market method application."""
    method_id: str
    probabilities: list | None      # [p_home, p_draw, p_away] or [p_over, p_under]
    n_books: int | None
    books_used: list
    shin_z: float | None
    overround: float | None
    fallback_chain: list = field(default_factory=list)
    dropped_books: list = field(default_factory=list)


def _valid_odds(v) -> bool:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f) and f > 1.0


def _collect_books(books: dict, legs) -> tuple[dict, list]:
    """Return {book: [odds per leg]} for books having ALL legs valid, plus dropped list."""
    got, dropped = {}, []
    for code, legs_dict in (books or {}).items():
        if not isinstance(legs_dict, dict):
            dropped.append(str(code))
            continue
        vals = [legs_dict.get(leg) for leg in legs]
        if all(_valid_odds(v) for v in vals):
            got[str(code)] = [float(v) for v in vals]
        else:
            dropped.append(str(code))
    return got, dropped


def _apply(method_id: str, odds_rows: list, books_used: list, use_shin: bool,
           fallback_chain: list, dropped_books: list) -> MethodResult:
    arr = np.array(odds_rows, dtype=float)
    mean = arr.mean(axis=0)                       # multi-book mean odds (phase4a convention)
    q = (1.0 / mean)[None, :]
    overround = float(q.sum())
    if use_shin:
        p, z = shin_probs(q)
        z_val = float(z[0])
    else:
        p, z_val = simple_norm(q), 0.0
    return MethodResult(
        method_id=method_id,
        probabilities=[float(x) for x in p[0]],
        n_books=len(books_used),
        books_used=books_used,
        shin_z=z_val,
        overround=overround,
        fallback_chain=fallback_chain,
        dropped_books=dropped_books,
    )


def ftr_prediction(books: dict) -> MethodResult | None:
    """FTR baseline. M4 (multi-book + Shin) with registered fallbacks.

    Fallback chain (each step recorded, caller downgrades status):
      n>=2 books -> M4 ; n==1 -> M2 (single-book Shin) ; none -> None.
    """
    got, dropped = _collect_books(books, FTR_LEGS)
    codes = sorted(got)
    if len(codes) >= 2:
        return _apply("M4", [got[c] for c in codes], codes, True, [], dropped)
    if len(codes) == 1:
        return _apply("M2", [got[codes[0]]], codes, True, ["M4->M2: single book"], dropped)
    return None


def ou25_prediction(books: dict) -> MethodResult | None:
    """OU25 baseline. O2 (B365 + Shin) with registered fallbacks.

    Fallback chain: B365 pair -> O2 ; n>=2 books -> O4 (multi-book + Shin) ;
    single book -> single-book Shin ; none -> None.
    """
    got, dropped = _collect_books(books, OU_LEGS)
    if "B365" in got:
        return _apply("O2", [got["B365"]], ["B365"], True, [], dropped)
    codes = sorted(got)
    if len(codes) >= 2:
        return _apply("O4", [got[c] for c in codes], codes, True, ["O2->O4: B365 pair missing"], dropped)
    if len(codes) == 1:
        return _apply("O2-single-book", [got[codes[0]]], codes, True,
                      ["O2->O4->single-book Shin"], dropped)
    return None


def entropy_bits(probs) -> float:
    p = np.asarray(list(probs), dtype=float)
    p = p[p > 0]
    return float(-(p * np.log2(p)).sum())


def book_dispersion_max(books: dict, legs) -> float | None:
    """Max across legs of the per-leg spread of raw implied probabilities (1/odds)."""
    got, _ = _collect_books(books, legs)
    if len(got) < 2:
        return None
    arr = np.array([got[c] for c in sorted(got)], dtype=float)
    imp = 1.0 / arr
    return float((imp.max(axis=0) - imp.min(axis=0)).max())
