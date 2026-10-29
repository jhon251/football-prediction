"""V1.2 failure analysis (spec section 20).

Samples failed predictions (highest-confidence top-1 misses first), records
prediction/actual/top-scenario/reasoning context, and classifies WHERE the
error most plausibly came from using deterministic, documented rules:

  data_error     - the snapshot had unknown inputs (lineups/odds/etc.)
  randomness     - the actual outcome was still within the model's top-3 or
                   carried >= 15% probability
  world_model_error - realized goals far from the model's expectation
                   (|actual - expected| > 2)
  simulation_error - model 1X2 distribution extreme vs calibration bins
                   (predicted > 0.6 while season calibration at that bin < 0.5)
  unknown        - none of the above applies (never force an explanation)
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

from football_simulation.backtest.metrics import calibration_curve
from football_simulation.backtest.models import FailureCase, PredictionRecord


def sample_failures(
    records: List[PredictionRecord],
    model: str = "full_system",
    n: int = 20,
    seed: int = 7,
) -> List[FailureCase]:
    failures = [r for r in records if r.predictions.get(model) is not None]
    missed = []
    for record in failures:
        pred = record.predictions[model]
        probs = {"home_win": pred.home_win, "draw": pred.draw, "away_win": pred.away_win}
        top = max(probs, key=probs.get)
        if top != record.actual_result():
            missed.append((record, probs[top]))
    missed.sort(key=lambda item: -item[1])
    if n:
        missed = missed[:n]
    return [analyze_failure(record, model, records) for record, _ in missed]


def analyze_failure(
    record: PredictionRecord,
    model: str,
    all_records: Optional[List[PredictionRecord]] = None,
) -> FailureCase:
    pred = record.predictions[model]
    probs = {"home_win": pred.home_win, "draw": pred.draw, "away_win": pred.away_win}
    top = max(probs, key=probs.get)
    actual = record.actual_result()
    actual_prob = probs[actual]
    total_goals = record.actual_home_goals + record.actual_away_goals

    # Deterministic priority order: outcome variance first (the model DID
    # consider the result), then structural goal-rate error, then calibration
    # over-confidence, then data gaps, else unknown.  Data gaps exist in
    # EVERY historical record, so they must not shadow real explanations.
    location = "unknown"
    reason = "no deterministic explanation applies"
    if actual_prob >= 0.15:
        location = "randomness"
        reason = (f"actual outcome carried {actual_prob:.2%} model probability "
                  f"- outcome variance")
    elif abs(total_goals - pred.expected_goals) > 2.0:
        location = "world_model_error"
        reason = (f"realized goals {total_goals} far from expected "
                  f"{pred.expected_goals:.2f} - goal-rate structure error")
    else:
        if all_records is not None and len(all_records) > 40:
            calibration = calibration_curve(all_records, model)
            for bucket in calibration["bins"]:
                if (bucket["mean_predicted"] >= 0.6 and bucket["empirical"] < 0.5
                        and bucket["mean_predicted"] - 0.1 <= probs[top]):
                    location = "simulation_error"
                    reason = ("season calibration at this probability band is below "
                              "the predicted level (over-confidence)")
                    break
        if location == "unknown" and record.unknowns:
            location = "data_error"
            reason = ("unknown pre-match inputs (lineups/weather/injuries) with no "
                      "better explanation available: " + ", ".join(record.unknowns[:4]))

    return FailureCase(
        match_id=record.match_id,
        prediction={
            "model": model,
            "home_win": pred.home_win, "draw": pred.draw, "away_win": pred.away_win,
            "top_outcome": top,
            "expected_goals": pred.expected_goals,
        },
        actual_result={
            "result": actual,
            "score": f"{record.actual_home_goals}-{record.actual_away_goals}",
            "probability_assigned": round(actual_prob, 4),
        },
        pre_match_summary={
            "unknowns": record.unknowns,
            "no_signal": record.no_signal,
            "home_team": record.home_team,
            "away_team": record.away_team,
        },
        top_scenario=record.top_scenario,
        probability=round(probs[top], 4),
        error_location=location,
        error_reason=reason,
    )


def failure_summary(cases: List[FailureCase]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for case in cases:
        counts[case.error_location] = counts.get(case.error_location, 0) + 1
    return counts
