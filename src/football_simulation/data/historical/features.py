"""Walk-forward feature computation with STRICT temporal cutoffs.

Every function takes a ``before`` timestamp and only ever reads matches with
``date < before``.  The time-travel test deletes post-kickoff rows and asserts
bit-identical features; any violation is a data leak.
"""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

from football_simulation.data.historical.schema import HistoricalMatch


def team_matches_before(matches: List[HistoricalMatch], team: str, before) -> List[HistoricalMatch]:
    return sorted(
        (m for m in matches if m.date < before and team in (m.home_team, m.away_team)),
        key=lambda m: m.date,
    )


def all_matches_before(matches: List[HistoricalMatch], before) -> List[HistoricalMatch]:
    return sorted((m for m in matches if m.date < before), key=lambda m: m.date)


# ---------------------------------------------------------------------------
# Elo (walk-forward, home-advantage from the training window itself)
# ---------------------------------------------------------------------------

def _expected(home_elo: float, away_elo: float, home_adv: float) -> float:
    return 1.0 / (1.0 + 10 ** (-(home_elo - away_elo + home_adv) / 400.0))


def rolling_elo(matches: List[HistoricalMatch], team: str, before, k: int = 20) -> float:
    """Convenience scalar lookup over the paired walk-forward Elo map."""
    return rolling_elo_map(matches, before, k=k).get(team, 1500.0)


def rolling_elo_map(matches: List[HistoricalMatch], before, k: int = 20,
                    home_adv: float = 60.0) -> Dict[str, float]:
    """Paired, self-consistent walk-forward Elo for every team seen before
    ``before`` (opponent ratings evolve consistently)."""
    elos: Dict[str, float] = {}

    def get(team: str) -> float:
        return elos.get(team, 1500.0)

    for match in all_matches_before(matches, before):
        rh, ra = get(match.home_team), get(match.away_team)
        expected = _expected(rh, ra, home_adv)
        actual = 1.0 if match.home_goals > match.away_goals else (
            0.5 if match.home_goals == match.away_goals else 0.0)
        delta = k * (actual - expected)
        elos[match.home_team] = rh + delta
        elos[match.away_team] = ra - delta
    return elos


# ---------------------------------------------------------------------------
# Rolling goal rates (last N matches per side, strict cutoff)
# ---------------------------------------------------------------------------

def rolling_goal_rates(matches: List[HistoricalMatch], team: str, before, n: int = 10) -> Dict[str, float]:
    """Attack (goals scored) / defense (goals conceded) per match from the
    team's last ``n`` matches before ``before``.  Missing history -> league
    neutral 1.35 baseline (documented, not fabricated per-match data)."""
    recent = team_matches_before(matches, team, before)[-n:]
    if not recent:
        return {"attack": 1.35, "defense": 1.35, "matches": 0.0}
    scored = sum(m.home_goals if m.home_team == team else m.away_goals for m in recent)
    conceded = sum(m.away_goals if m.home_team == team else m.home_goals for m in recent)
    return {
        "attack": scored / len(recent),
        "defense": conceded / len(recent),
        "matches": float(len(recent)),
    }


def rolling_match_stats(matches: List[HistoricalMatch], team: str, before, n: int = 10) -> Dict[str, float]:
    """Walk-forward aggregates of the richer stat columns (shots / shots on
    target / corners / fouls / cards / HT goals) over the team's last ``n``
    matches before ``before``.

    Missing columns (None in the source) are skipped per match - never filled
    with guesses.  Counters use ``n_*`` denominators so callers can see how
    many matches actually contributed per statistic.
    """
    recent = team_matches_before(matches, team, before)[-n:]
    if not recent:
        return {"matches": 0.0}
    agg: Dict[str, float] = {
        "shots_for": 0.0, "shots_against": 0.0,
        "sot_for": 0.0, "sot_against": 0.0,
        "corners_for": 0.0, "corners_against": 0.0,
        "fouls_for": 0.0, "fouls_against": 0.0,
        "cards_for": 0.0, "cards_against": 0.0,
        "ht_goals_for": 0.0, "ht_goals_against": 0.0,
        "n_shots": 0.0, "n_sot": 0.0, "n_corners": 0.0, "n_fouls": 0.0,
        "n_cards": 0.0, "n_ht": 0.0,
        "matches": float(len(recent)),
    }
    for match in recent:
        home = match.home_team == team

        def pick(home_val, away_val):
            return home_val if home else away_val

        shots_for = pick(match.home_shots, match.away_shots)
        shots_against = pick(match.away_shots, match.home_shots)
        sot_for = pick(match.home_shots_on_target, match.away_shots_on_target)
        sot_against = pick(match.away_shots_on_target, match.home_shots_on_target)
        corners_for = pick(match.home_corners, match.away_corners)
        corners_against = pick(match.away_corners, match.home_corners)
        fouls_for = pick(match.home_fouls, match.away_fouls)
        fouls_against = pick(match.away_fouls, match.home_fouls)
        cards_for = pick(match.home_yellow_cards, match.away_yellow_cards)
        cards_against = pick(match.away_yellow_cards, match.home_yellow_cards)
        if match.home_red_cards is not None and match.away_red_cards is not None:
            cards_for = (cards_for or 0) + pick(match.home_red_cards, match.away_red_cards)
            cards_against = (cards_against or 0) + pick(match.away_red_cards, match.home_red_cards)
        ht_for = pick(match.half_time_home_goals, match.half_time_away_goals)
        ht_against = pick(match.half_time_away_goals, match.half_time_home_goals)

        if shots_for is not None and shots_against is not None:
            agg["shots_for"] += shots_for
            agg["shots_against"] += shots_against
            agg["n_shots"] += 1.0
        if sot_for is not None and sot_against is not None:
            agg["sot_for"] += sot_for
            agg["sot_against"] += sot_against
            agg["n_sot"] += 1.0
        if corners_for is not None and corners_against is not None:
            agg["corners_for"] += corners_for
            agg["corners_against"] += corners_against
            agg["n_corners"] += 1.0
        if fouls_for is not None and fouls_against is not None:
            agg["fouls_for"] += fouls_for
            agg["fouls_against"] += fouls_against
            agg["n_fouls"] += 1.0
        if cards_for is not None and cards_against is not None:
            agg["cards_for"] += cards_for
            agg["cards_against"] += cards_against
            agg["n_cards"] += 1.0
        if ht_for is not None and ht_against is not None:
            agg["ht_goals_for"] += ht_for
            agg["ht_goals_against"] += ht_against
            agg["n_ht"] += 1.0
    return agg


def fixture_congestion(matches: List[HistoricalMatch], team: str, before, window_days: int = 14) -> int:
    """Matches played by ``team`` in the ``window_days`` before ``before``."""
    cutoff = before - timedelta(days=window_days)
    return sum(
        1 for m in team_matches_before(matches, team, before) if m.date >= cutoff
    )


def days_since_last_match(matches: List[HistoricalMatch], team: str, before) -> Optional[int]:
    recent = team_matches_before(matches, team, before)
    if not recent:
        return None
    return max(0, (before - recent[-1].date).days)


def form_points(matches: List[HistoricalMatch], team: str, before, n: int = 5) -> Dict[str, float]:
    recent = team_matches_before(matches, team, before)[-n:]
    points = 0.0
    wins = 0
    streak = 0
    for match in recent:
        gf = match.home_goals if match.home_team == team else match.away_goals
        ga = match.away_goals if match.home_team == team else match.home_goals
        if gf > ga:
            points += 3.0
            wins += 1
            streak = streak + 1 if streak >= 0 else 1
        elif gf == ga:
            points += 1.0
            streak = 0
        else:
            streak = -1
    return {"points": points, "matches": float(len(recent)),
            "points_per_game": (points / len(recent)) if recent else 1.0,
            "wins": float(wins), "streak": float(streak)}


def league_home_rates(matches: List[HistoricalMatch], before) -> Dict[str, float]:
    """Home/draw/away outcome rates over every match before ``before``."""
    prior = all_matches_before(matches, before)
    if not prior:
        return {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3, "n": 0.0}
    home = sum(1 for m in prior if m.home_goals > m.away_goals)
    draw = sum(1 for m in prior if m.home_goals == m.away_goals)
    away = len(prior) - home - draw
    return {"home": home / len(prior), "draw": draw / len(prior),
            "away": away / len(prior), "n": float(len(prior))}


def league_goal_rate(matches: List[HistoricalMatch], before) -> float:
    prior = all_matches_before(matches, before)
    if not prior:
        return 2.7
    return sum(m.home_goals + m.away_goals for m in prior) / len(prior)


def build_team_features(matches: List[HistoricalMatch], team: str, before,
                        elos: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    """Aggregated pre-match feature bundle for one team (walk-forward only)."""
    elos = elos if elos is not None else {}
    rates = rolling_goal_rates(matches, team, before)
    form = form_points(matches, team, before)
    return {
        "elo": elos.get(team, 1500.0),
        "attack_rate": rates["attack"],
        "defense_rate": rates["defense"],
        "rate_sample_matches": rates["matches"],
        "form_ppg": form["points_per_game"],
        "form_points": form["points"],
        "streak": form["streak"],
        "congestion_14d": float(fixture_congestion(matches, team, before)),
        "days_since_last": float(days_since_last_match(matches, team, before)
                                 if days_since_last_match(matches, team, before) is not None else -1.0),
    }
