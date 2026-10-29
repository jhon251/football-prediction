"""V1.2 baselines.

Random / Home-Advantage / Elo / Historical Goal Rate / Poisson / Market.

ALL baselines are strictly walk-forward: parameters come only from matches
with date < the predicted match's kickoff (the Poisson baseline fits on the
training window that ends BEFORE the test season starts).  Poisson models are
baselines here - they are NOT the sandbox and are not treated as football
truth.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from football_simulation.backtest.models import ModelPrediction
from football_simulation.data.historical import features as feats
from football_simulation.data.historical.etl import HistoricalDataset
from football_simulation.data.historical.schema import HistoricalMatch

MAX_GOALS = 10


def _poisson_pmf(lam: float, k: int) -> float:
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def _score_matrix(lam_home: float, lam_away: float, cap: int = 6) -> Dict[str, float]:
    matrix: Dict[str, float] = {}
    for h in range(0, MAX_GOALS + 1):
        for a in range(0, MAX_GOALS + 1):
            key = f"{min(h, cap)}-{min(a, cap)}"
            matrix[key] = matrix.get(key, 0.0) + _poisson_pmf(lam_home, h) * _poisson_pmf(lam_away, a)
    return {k: round(v, 8) for k, v in matrix.items()}


def _probs_from_matrix(matrix: Dict[str, float]) -> tuple:
    p_home = sum(p for k, p in matrix.items() if int(k.split("-")[0]) > int(k.split("-")[1]))
    p_draw = sum(p for k, p in matrix.items() if k.split("-")[0] == k.split("-")[1])
    p_away = 1.0 - p_home - p_draw
    return p_home, p_draw, p_away


def _ou_from_matrix(matrix: Dict[str, float], line: float) -> float:
    return sum(p for k, p in matrix.items()
               if int(k.split("-")[0]) + int(k.split("-")[1]) > line)


def _btts_from_matrix(matrix: Dict[str, float]) -> float:
    return sum(p for k, p in matrix.items()
               if int(k.split("-")[0]) > 0 and int(k.split("-")[1]) > 0)


def _build_prediction(model: str, matrix: Dict[str, float],
                      lam_home: float, lam_away: float) -> ModelPrediction:
    p_home, p_draw, p_away = _probs_from_matrix(matrix)
    return ModelPrediction(
        model=model,
        home_win=round(p_home, 6), draw=round(p_draw, 6), away_win=round(p_away, 6),
        expected_goals=round(lam_home + lam_away, 4),
        over25=round(_ou_from_matrix(matrix, 2.5), 6),
        over35=round(_ou_from_matrix(matrix, 3.5), 6),
        btts_yes=round(_btts_from_matrix(matrix), 6),
        score_matrix=matrix,
    )


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------

class RandomBaseline:
    name = "random"

    def predict(self, dataset: HistoricalDataset, match: HistoricalMatch) -> ModelPrediction:
        base = feats.league_goal_rate(dataset.matches, match.date)
        matrix = _score_matrix(base / 2, base / 2)
        return ModelPrediction(
            model=self.name,
            home_win=1 / 3, draw=1 / 3, away_win=1 / 3,
            expected_goals=round(base, 4),
            over25=round(_ou_from_matrix(matrix, 2.5), 6),
            over35=round(_ou_from_matrix(matrix, 3.5), 6),
            btts_yes=round(_btts_from_matrix(matrix), 6),
            score_matrix=matrix,
        )


class HomeAdvantageBaseline:
    name = "home_advantage"

    def predict(self, dataset: HistoricalDataset, match: HistoricalMatch) -> ModelPrediction:
        rates = feats.league_home_rates(dataset.matches, match.date)
        base = feats.league_goal_rate(dataset.matches, match.date)
        # split total goals by the training-window home/away scoring share
        prior = dataset.matches_before(match.date)
        home_goals = sum(m.home_goals for m in prior) or 1.0
        away_goals = sum(m.away_goals for m in prior) or 1.0
        share = home_goals / (home_goals + away_goals)
        lam_home = base * share
        lam_away = base * (1 - share)
        matrix = _score_matrix(lam_home, lam_away)
        return ModelPrediction(
            model=self.name,
            home_win=round(rates["home"], 6), draw=round(rates["draw"], 6),
            away_win=round(rates["away"], 6),
            expected_goals=round(base, 4),
            over25=round(_ou_from_matrix(matrix, 2.5), 6),
            over35=round(_ou_from_matrix(matrix, 3.5), 6),
            btts_yes=round(_btts_from_matrix(matrix), 6),
            score_matrix=matrix,
        )


class EloBaseline:
    name = "elo"

    def predict(self, dataset: HistoricalDataset, match: HistoricalMatch) -> ModelPrediction:
        elos = feats.rolling_elo_map(dataset.matches, match.date)
        home_elo = elos.get(match.home_team, 1500.0)
        away_elo = elos.get(match.away_team, 1500.0)
        diff = home_elo - away_elo + 60.0
        p_home_raw = 1.0 / (1.0 + 10 ** (-diff / 400.0))
        base = feats.league_goal_rate(dataset.matches, match.date)
        # documented mapping: Elo edge shifts the goal expectation
        lam_home = base / 2 + 0.85 * (p_home_raw - 0.5) * base
        lam_away = base / 2 - 0.85 * (p_home_raw - 0.5) * base
        lam_home = max(0.25, lam_home)
        lam_away = max(0.25, lam_away)
        return _build_prediction(self.name, _score_matrix(lam_home, lam_away),
                                 lam_home, lam_away)


class HistoricalGoalRateBaseline:
    name = "historical_goal_rate"

    def predict(self, dataset: HistoricalDataset, match: HistoricalMatch) -> ModelPrediction:
        home = feats.rolling_goal_rates(dataset.matches, match.home_team, match.date, n=10)
        away = feats.rolling_goal_rates(dataset.matches, match.away_team, match.date, n=10)
        base = feats.league_goal_rate(dataset.matches, match.date)
        lam_home = home["attack"] * away["defense"] / max(0.5, base / 1.15)
        lam_away = away["attack"] * home["defense"] / max(0.5, base / 1.15)
        return _build_prediction(self.name, _score_matrix(lam_home, lam_away),
                                 lam_home, lam_away)


class PoissonBaseline:
    """Attack/defense Poisson fitted on the pre-test-season training window.

    Fitted ONCE per season - strictly before the test season starts - so no
    in-season information can leak into the parameters.
    """

    name = "poisson"

    def __init__(self, training_window_end=None):
        self._training_window_end = training_window_end

    def fit(self, dataset: HistoricalDataset, before) -> Dict[str, Dict[str, float]]:
        try:
            import numpy as np
            from scipy.optimize import minimize
        except ImportError:  # pragma: no cover
            return {}
        prior = dataset.matches_before(before)
        if len(prior) < 60:
            return {}
        teams = sorted({t for m in prior for t in (m.home_team, m.away_team)})
        index = {t: i for i, t in enumerate(teams)}
        avg = (sum(m.home_goals + m.away_goals for m in prior) / len(prior) / 2) or 1.3
        n_teams = len(teams)

        def neg_log_likelihood(x: np.ndarray) -> float:
            attack = {teams[i]: max(0.05, x[i]) for i in range(n_teams)}
            defense = {teams[i]: max(0.05, x[n_teams + i]) for i in range(n_teams)}
            total = 0.0
            for m in prior:
                lam_h = avg * attack[m.home_team] * defense[m.away_team]
                lam_a = avg * attack[m.away_team] * defense[m.home_team]
                total -= (m.home_goals * math.log(lam_h) - lam_h
                          + m.away_goals * math.log(lam_a) - lam_a)
            return total

        x0 = np.ones(2 * n_teams)
        result = minimize(neg_log_likelihood, x0, method="Nelder-Mead",
                          options={"maxiter": 4000, "xatol": 1e-4, "fatol": 1e-6})
        x = result.x
        attack = {teams[i]: max(0.05, x[i]) for i in range(n_teams)}
        defense = {teams[i]: max(0.05, x[n_teams + i]) for i in range(n_teams)}
        return {"attack": attack, "defense": defense, "avg": avg}

    def predict(self, dataset: HistoricalDataset, match: HistoricalMatch,
                params: Optional[Dict] = None) -> ModelPrediction:
        params = params or self.fit(dataset, match.date)
        if not params:
            # fall back to the historical goal-rate baseline when the window
            # is too small to fit (documented degradation)
            return HistoricalGoalRateBaseline().predict(dataset, match)
        avg = params["avg"]
        lam_home = avg * params["attack"].get(match.home_team, 1.0) * params["defense"].get(match.away_team, 1.0)
        lam_away = avg * params["attack"].get(match.away_team, 1.0) * params["defense"].get(match.home_team, 1.0)
        return _build_prediction(self.name, _score_matrix(lam_home, lam_away),
                                 lam_home, lam_away)


class MarketBaseline:
    name = "market_odds"

    def predict(self, dataset: HistoricalDataset, match: HistoricalMatch) -> Optional[ModelPrediction]:
        odds = match.closing_odds or match.opening_odds
        if odds is None:
            return None
        implied = odds.implied_probabilities()
        if not implied:
            return None
        base = feats.league_goal_rate(dataset.matches, match.date)
        target_h, target_d = implied["home"], implied["draw"]

        def error(x):
            lam_home, lam_away = max(0.05, x[0]), max(0.05, x[1])
            matrix = _score_matrix(lam_home, lam_away)
            p_h, p_d, _ = _probs_from_matrix(matrix)
            return (p_h - target_h) ** 2 + (p_d - target_d) ** 2

        best = None
        try:
            from scipy.optimize import minimize
            result = minimize(error, [base / 2 + 0.3, base / 2 - 0.3],
                              method="Nelder-Mead",
                              options={"xatol": 1e-5, "fatol": 1e-9, "maxiter": 2000})
            lam_home, lam_away = max(0.05, result.x[0]), max(0.05, result.x[1])
            best = (lam_home, lam_away)
        except ImportError:  # pragma: no cover
            best = None
        if best is None:
            return HistoricalGoalRateBaseline().predict(dataset, match)
        lam_home, lam_away = best
        return _build_prediction(self.name, _score_matrix(lam_home, lam_away),
                                 lam_home, lam_away)


BASELINE_NAMES = ["random", "home_advantage", "elo", "historical_goal_rate",
                  "poisson", "market_odds"]


def make_baselines() -> Dict[str, object]:
    return {
        "random": RandomBaseline(),
        "home_advantage": HomeAdvantageBaseline(),
        "elo": EloBaseline(),
        "historical_goal_rate": HistoricalGoalRateBaseline(),
        "poisson": PoissonBaseline(),
        "market_odds": MarketBaseline(),
    }
