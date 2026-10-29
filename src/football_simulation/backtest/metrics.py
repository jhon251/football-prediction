"""V1.2 evaluation metrics: 1X2 / score / O-U / BTTS / calibration."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from football_simulation.backtest.models import ModelPrediction, PredictionRecord

BINS = [(0.0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.4), (0.4, 0.5),
        (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0)]


def _safe_log(p: float) -> float:
    return math.log(max(p, 1e-12))


def one_x_two_metrics(records: List[PredictionRecord], model: str) -> Dict[str, float]:
    n = len(records)
    correct = 0
    top1 = 0
    top2 = 0
    brier = 0.0
    logloss = 0.0
    for record in records:
        pred = record.predictions[model]
        probs = {"home_win": pred.home_win, "draw": pred.draw, "away_win": pred.away_win}
        actual = record.actual_result()
        ranked = sorted(probs.items(), key=lambda kv: -kv[1])
        if ranked[0][0] == actual:
            correct += 1
        if actual in {ranked[0][0], ranked[1][0]}:
            top2 += 1
        top1 += 1 if ranked[0][0] == actual else 0
        for outcome in ("home_win", "draw", "away_win"):
            y = 1.0 if actual == outcome else 0.0
            brier += (probs[outcome] - y) ** 2
            logloss -= y * _safe_log(probs[outcome])
    return {
        "n": float(n),
        "accuracy": correct / n,
        "top1_accuracy": top1 / n,
        "top2_accuracy": top2 / n,
        "brier": brier / n,
        "log_loss": logloss / n,
    }


def calibration_curve(records: List[PredictionRecord], model: str) -> Dict[str, Any]:
    """Reliability diagram data + ECE + over/under-confidence stats."""
    buckets: List[Dict[str, Any]] = []
    per_bin: Dict[int, Dict[str, float]] = {}
    for record in records:
        pred = record.predictions[model]
        actual = record.actual_result()
        probs = {"home_win": pred.home_win, "draw": pred.draw, "away_win": pred.away_win}
        for outcome, p in probs.items():
            y = 1.0 if actual == outcome else 0.0
            for i, (low, high) in enumerate(BINS):
                if low <= p < high or (high == 1.0 and p == 1.0):
                    bucket = per_bin.setdefault(
                        i, {"sum_p": 0.0, "sum_y": 0.0, "count": 0.0, "range": f"{low:.1f}-{high:.1f}"})
                    bucket["sum_p"] += p
                    bucket["sum_y"] += y
                    bucket["count"] += 1.0
                    break
    ece = 0.0
    total = float(len(records) * 3)
    max_overconfidence = 0.0
    for i in range(len(BINS)):
        bucket = per_bin.get(i)
        if bucket is None or bucket["count"] == 0:
            continue
        mean_p = bucket["sum_p"] / bucket["count"]
        emp = bucket["sum_y"] / bucket["count"]
        gap = abs(mean_p - emp)
        ece += (bucket["count"] / total) * gap
        max_overconfidence = max(max_overconfidence, mean_p - emp)
        buckets.append({
            "bin": bucket["range"], "count": int(bucket["count"]),
            "mean_predicted": round(mean_p, 4), "empirical": round(emp, 4),
        })
    return {
        "ece": round(ece, 4),
        "max_overconfidence": round(max_overconfidence, 4),
        "bins": buckets,
    }


def score_metrics(records: List[PredictionRecord], model: str, top_n: List[int] = (3, 5)) -> Dict[str, float]:
    n = len(records)
    exact = 0
    coverage = {k: 0 for k in top_n}
    for record in records:
        actual_score = f"{record.actual_home_goals}-{record.actual_away_goals}"
        matrix = record.predictions[model].score_matrix
        ranked = sorted(matrix.items(), key=lambda kv: -kv[1])
        if ranked and ranked[0][0] == actual_score:
            exact += 1
        for k in top_n:
            if actual_score in {key for key, _ in ranked[:k]}:
                coverage[k] += 1
    out = {"n": float(n), "exact_score_accuracy": exact / n}
    for k in top_n:
        out[f"top{k}_score_coverage"] = coverage[k] / n
    return out


def binary_metrics(records: List[PredictionRecord], model: str,
                   kind: str) -> Optional[Dict[str, float]]:
    """kind in {'ou25', 'ou35', 'btts'}: accuracy/brier/logloss."""
    n = len(records)
    used = 0
    correct = 0
    brier = 0.0
    logloss = 0.0
    for record in records:
        pred = record.predictions[model]
        if kind == "ou25":
            p = pred.over25
            y = 1.0 if record.actual_home_goals + record.actual_away_goals > 2.5 else 0.0
        elif kind == "ou35":
            p = pred.over35
            y = 1.0 if record.actual_home_goals + record.actual_away_goals > 3.5 else 0.0
        else:
            p = pred.btts_yes
            y = 1.0 if (record.actual_home_goals > 0 and record.actual_away_goals > 0) else 0.0
        if p is None:
            continue
        used += 1
        correct += 1 if (p >= 0.5) == bool(y) else 0
        brier += (p - y) ** 2
        logloss -= y * _safe_log(p) + (1 - y) * _safe_log(1 - p)
    if used == 0:
        return None
    return {"n": float(used), "accuracy": correct / used,
            "brier": brier / used, "log_loss": logloss / used}


def full_metrics(records: List[PredictionRecord], model: str) -> Dict[str, Any]:
    """Every metric section for one model."""
    metrics: Dict[str, Any] = {"one_x_two": one_x_two_metrics(records, model)}
    metrics["calibration"] = calibration_curve(records, model)
    metrics["score"] = score_metrics(records, model)
    metrics["ou25"] = binary_metrics(records, model, "ou25")
    metrics["ou35"] = binary_metrics(records, model, "ou35")
    metrics["btts"] = binary_metrics(records, model, "btts")
    return metrics


def model_comparison(records: List[PredictionRecord]) -> Dict[str, Dict[str, Any]]:
    return {model: full_metrics(records, model) for model in sorted(records[0].predictions)}


# ---------------------------------------------------------------------------
# EXP-REAL-EPL-BASE-001 additions: per-match series, rolling windows,
# season-phase breakdowns.
# ---------------------------------------------------------------------------

def per_match_series(records: List[PredictionRecord], model: str) -> Dict[str, List[float]]:
    """Per-match 1X2 brier / logloss / correct(0/1) in DATE order."""
    brier: List[float] = []
    logloss: List[float] = []
    correct: List[float] = []
    for record in records:
        pred = record.predictions[model]
        probs = {"home_win": pred.home_win, "draw": pred.draw, "away_win": pred.away_win}
        actual = record.actual_result()
        b = 0.0
        ll = 0.0
        for outcome, p in probs.items():
            y = 1.0 if actual == outcome else 0.0
            b += (p - y) ** 2
            ll -= y * _safe_log(p)
        brier.append(b)
        logloss.append(ll)
        correct.append(1.0 if max(probs, key=probs.get) == actual else 0.0)
    return {"brier": brier, "log_loss": logloss, "correct": correct}


def rolling_metrics(records: List[PredictionRecord], model: str,
                    window: int = 100) -> List[Dict[str, float]]:
    """Rolling (window ending at each match) metrics over the ordered records."""
    series = per_match_series(records, model)
    out: List[Dict[str, float]] = []
    n = len(records)
    for end in range(1, n + 1):
        start = max(0, end - window)
        b = series["brier"][start:end]
        ll = series["log_loss"][start:end]
        acc = series["correct"][start:end]
        out.append({
            "match_index": end - 1,
            "window_size": len(b),
            "brier": round(sum(b) / len(b), 4),
            "log_loss": round(sum(ll) / len(ll), 4),
            "accuracy": round(sum(acc) / len(acc), 4),
        })
    return out


def phase_metrics(records: List[PredictionRecord], model: str,
                  n_phases: int = 3) -> List[Dict[str, Any]]:
    """Early/Mid/Late season 1X2 metrics over equal thirds of the ordered list."""
    n = len(records)
    phases: List[Dict[str, Any]] = []
    names = ["early_season", "mid_season", "late_season"][:n_phases]
    for i in range(n_phases):
        start = (i * n) // n_phases
        end = ((i + 1) * n) // n_phases
        chunk = records[start:end]
        phases.append({
            "phase": names[i],
            "matches": f"{start + 1}-{end}",
            **one_x_two_metrics(chunk, model),
        })
    return phases
