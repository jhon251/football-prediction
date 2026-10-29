"""EXP-DIAG-EPL-001 diagnosis toolkit.

READ-ONLY w.r.t. the production model, knowledge rules, config and the frozen
baseline EXP-REAL-EPL-BASE-001 (experiment_id 7c52c6bdfa37).

The frozen records persist per-model predictions but NOT the direct per-agent
outputs (Team/Tactical/Psychology/... states).  Those are therefore reported
as DATA_UNAVAILABLE for the original run; this module additionally computes
DETERMINISTIC RECONSTRUCTIONS of the pre-match agent layer from the frozen
dataset - clearly labeled reconstructions for diagnosis only, never presented
as original experiment data.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from football_simulation.agents.base import AgentContext
from football_simulation.agents.fitness import FitnessAgent
from football_simulation.agents.psychology import PsychologyAgent
from football_simulation.agents.tactical import TacticalMatchupAgent
from football_simulation.backtest.models import ModelPrediction, PredictionRecord
from football_simulation.data.historical import features as feats
from football_simulation.data.historical.etl import HistoricalDataset
from football_simulation.data.historical.provider import HistoricalDataProvider
from football_simulation.data.historical.snapshot import SnapshotBuilder
from football_simulation.knowledge import load_all_knowledge
from football_simulation.models.base import Side

BASELINE_ID = "7c52c6bdfa37"


# ---------------------------------------------------------------------------
# 0) frozen-baseline integrity manifest
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def baseline_manifest(baseline_dir: Path) -> Dict[str, Any]:
    manifest: Dict[str, Any] = {"experiment_id": BASELINE_ID, "files": {}}
    for path in sorted(baseline_dir.rglob("*")):
        if path.is_file():
            manifest["files"][str(path.relative_to(baseline_dir))] = sha256_file(path)
    return manifest


# ---------------------------------------------------------------------------
# 1) deterministic reconstruction of the pre-match agent layer
# ---------------------------------------------------------------------------

def reconstruct_prematch_layer(
    dataset: HistoricalDataset, match_ids: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """Deterministic pre-match agent outputs (no simulation involved).

    NOTE: these are RECONSTRUCTIONS from the frozen dataset.  The original
    experiment did not persist per-agent outputs -> DATA_UNAVAILABLE for the
    original run; the values here are diagnostic reconstructions only.
    """
    knowledge = load_all_knowledge()
    builder = SnapshotBuilder(dataset.matches, strict=True)
    tactical_agent = TacticalMatchupAgent()
    psychology_agent = PsychologyAgent()
    fitness_agent = FitnessAgent()

    rows: List[Dict[str, Any]] = []
    for match in dataset.matches:
        if match_ids is not None and match.match_id not in set(match_ids):
            continue
        snapshot = builder.build(match)
        provider = HistoricalDataProvider(dataset, snapshot,
                                          use_extended_features=True, expose_odds=False)
        home_profile = provider.get_team_data(match.home_team)
        away_profile = provider.get_team_data(match.away_team)
        from football_simulation.agents.team import TeamAgent
        team_agent = TeamAgent()
        home_history = provider.get_match_history(
            match.home_team, "premier_league", "2025-26", match.date)
        away_history = provider.get_match_history(
            match.away_team, "premier_league", "2025-26", match.date)
        home_state, _ = team_agent.build_state(home_profile, home_history, is_home=True)
        away_state, _ = team_agent.build_state(away_profile, away_history, is_home=False)
        # home-advantage-free versions (the engine feeds the WITH-home states,
        # but for correlation diagnostics we need the signal without the
        # systematic home bias)
        home_state_nohome, _ = team_agent.build_state(home_profile, home_history, is_home=False)
        away_state_nohome, _ = team_agent.build_state(away_profile, away_history, is_home=False)
        matchup, _ = tactical_agent.analyze(home_state, away_state,
                                            knowledge["tactical_patterns"])
        matchup_nohome, _ = tactical_agent.analyze(home_state_nohome, away_state_nohome,
                                                   knowledge["tactical_patterns"])
        psych_home, _ = psychology_agent.build_state(Side.HOME, home_state, home_history,
                                                     True, [], 0.5, 0.5)
        psych_away, _ = psychology_agent.build_state(Side.AWAY, away_state, away_history,
                                                     False, [], 0.5, 0.5)
        from football_simulation.models.entities import PlayerState
        neutral_squad = {
            f"diag-{i}": PlayerState(player_id=f"diag-{i}", fatigue_sensitivity=0.5)
            for i in range(11)
        }
        fitness_home, _ = fitness_agent.build_state(Side.HOME, match.home_team,
                                                    neutral_squad, home_history, match.date)
        fitness_away, _ = fitness_agent.build_state(Side.AWAY, match.away_team,
                                                    neutral_squad, away_history, match.date)
        feat_home = snapshot.team_features["home"]
        feat_away = snapshot.team_features["away"]
        rows.append({
            "match_id": match.match_id,
            "date": match.date,
            "home_team": match.home_team,
            "away_team": match.away_team,
            # Elo (baseline feature)
            "elo_home": feat_home["elo"],
            "elo_away": feat_away["elo"],
            "elo_diff": feat_home["elo"] - feat_away["elo"],
            # Team Agent signals
            "team_attack_diff": home_state.attack_strength - away_state.attack_strength,
            "team_defense_diff": home_state.defense_strength - away_state.defense_strength,
            "team_strength_diff": (home_state.attack_strength + home_state.defense_strength
                                   - away_state.attack_strength - away_state.defense_strength),
            "team_strength_diff_nohome": (
                home_state_nohome.attack_strength + home_state_nohome.defense_strength
                - away_state_nohome.attack_strength - away_state_nohome.defense_strength),
            "team_home_advantage": home_state.home_advantage,
            # Tactical Matchup signals
            "tactical_advantage_home": matchup.tactical_advantage_home,
            "tactical_advantage_nohome": matchup_nohome.tactical_advantage_home,
            "tactical_cc_diff": matchup.chance_creation_home - matchup.chance_creation_away,
            "tactical_cc_diff_nohome": (matchup_nohome.chance_creation_home
                                        - matchup_nohome.chance_creation_away),
            "tactical_transition_risk_home": matchup.transition_risk_home,
            "tactical_transition_risk_away": matchup.transition_risk_away,
            # Psychology signals
            "psych_confidence_diff": psych_home.confidence - psych_away.confidence,
            "psych_pressure_diff": psych_home.pressure - psych_away.pressure,
            "psych_motivation_diff": psych_home.motivation - psych_away.motivation,
            # Fitness signals
            "fitness_fatigue_diff": fitness_home.fatigue_score - fitness_away.fatigue_score,
            "fitness_congestion_home": feat_home["congestion_14d"],
            "fitness_congestion_away": feat_away["congestion_14d"],
            "fitness_congestion_diff": feat_home["congestion_14d"] - feat_away["congestion_14d"],
            # Referee: name-only in this source -> tendencies NO_SIGNAL
            "referee_known": False,
            "referee_signal": 0.0,
            # Player: no player data in the source -> NO_SIGNAL by construction
            "player_signal": 0.0,
            "player_no_signal": True,
            # Momentum: in-match dynamic state - pre-match value is neutral
            # by engine construction; trajectories were NOT persisted.
            "momentum_prematch_home": 0.5,
            "momentum_trajectory_available": False,
        })
    return rows


def distribution_stats(values: List[float]) -> Dict[str, float]:
    arr = np.asarray([v for v in values if v is not None and not math.isnan(v)], dtype=float)
    if arr.size == 0:
        return {"n": 0.0}
    return {
        "n": float(arr.size),
        "mean": round(float(arr.mean()), 5),
        "std": round(float(arr.std()), 5),
        "min": round(float(arr.min()), 5),
        "max": round(float(arr.max()), 5),
        "p05": round(float(np.percentile(arr, 5)), 5),
        "p50": round(float(np.percentile(arr, 50)), 5),
        "p95": round(float(np.percentile(arr, 95)), 5),
        "no_signal_share": round(float(np.mean(np.abs(arr) < 1e-9)), 5),
    }


# ---------------------------------------------------------------------------
# 2) information duplication: correlations + dependency matrix
# ---------------------------------------------------------------------------

def correlations(rows: List[Dict[str, Any]], columns: List[str]) -> Dict[str, Any]:
    """Pearson + Spearman (rank) correlation for selected columns."""
    matrix = {col: np.asarray([r[col] for r in rows], dtype=float) for col in columns}
    out: Dict[str, Any] = {"pearson": {}, "spearman": {}}
    for i, a in enumerate(columns):
        for b in columns[i + 1:]:
            x, y = matrix[a], matrix[b]
            out["pearson"][f"{a}__{b}"] = round(float(np.corrcoef(x, y)[0, 1]), 4)
            out["spearman"][f"{a}__{b}"] = round(float(
                np.corrcoef(np.argsort(np.argsort(x)), np.argsort(np.argsort(y)))[0, 1]), 4)
    return out


# Agent -> input features dependency matrix (static, from code reading)
AGENT_INPUT_DEPENDENCY = {
    "Team": ["elo(walk-forward)", "attack_rate", "defense_rate", "form_ppg", "streak",
             "home_advantage(league rates)", "shots/SOT/corners rates (extended)"],
    "Tactical": ["TeamState fields only (attack/defense/midfield, styles=neutral, "
                 "defensive_line=0.5, counter=0.5)"],
    "Psychology": ["form points/streak from FT results", "importance=0.5 const",
                   "coach pressure=0.5 const", "home flag"],
    "Fitness": ["schedule: congestion_14d, days_since_last_match"],
    "Referee": ["referee NAME only (no tendency data) -> NO_SIGNAL"],
    "Player": ["no player data -> NO_SIGNAL placeholder squad"],
    "Momentum": ["in-match events only (not a pre-match feature consumer)"],
}


# ---------------------------------------------------------------------------
# 4) fusion sensitivity: per-match influence from config predictions
# ---------------------------------------------------------------------------

def _home_win(pred: Any) -> float:
    if isinstance(pred, dict):
        return float(pred["home_win"])
    return float(pred.home_win)


def influence_summary(
    preds_by_config: Dict[str, Dict[str, Any]],
    agent_name: str,
) -> Dict[str, Any]:
    """Per-match influence of one agent = |P(full)-P(full-X)| on home_win."""
    full = preds_by_config["full"]
    minus = preds_by_config.get(f"full_minus_{agent_name.lower()}")
    if minus is None:
        return {}
    deltas = []
    for match_id in full:
        if match_id in minus:
            deltas.append(_home_win(full[match_id]) - _home_win(minus[match_id]))
    arr = np.asarray(deltas, dtype=float)
    return {
        "mean_abs_delta": round(float(np.mean(np.abs(arr))), 5),
        "max_abs_delta": round(float(np.max(np.abs(arr))), 5),
        "std_delta": round(float(arr.std()), 5),
        "share_delta_gt_1pp": round(float(np.mean(np.abs(arr) > 0.01)), 5),
    }


def identify_high_influence(
    preds_by_config: Dict[str, Dict[str, ModelPrediction]],
    single_agent_brier: Dict[str, float],
    baseline_brier: float,
) -> List[Dict[str, Any]]:
    """HIGH INFLUENCE agents and LOW INFORMATION / HIGH INFLUENCE agents.

    An agent is LOW-INFORMATION/HIGH-INFLUENCE when toggling it moves the
    final probability materially (>1pp on average) while its standalone
    config does NOT beat the full system.  An agent whose standalone config
    DOES beat the full system is labeled standalone-competitive (it is
    competitive alone, without claiming its information is independent).
    """
    out: List[Dict[str, Any]] = []
    for agent in ("Team", "Tactical", "Psychology", "Momentum", "Referee", "Player"):
        influence = influence_summary(preds_by_config, agent)
        if not influence:
            continue
        single = single_agent_brier.get(agent.lower())
        if influence["mean_abs_delta"] < 0.01:
            verdict = "low_influence"
        elif single is not None and single < baseline_brier - 0.002:
            verdict = "high_influence_standalone_competitive"
        else:
            verdict = "low_information_high_influence"
        out.append({**{"agent": agent, "verdict": verdict,
                       "single_agent_brier": single,
                       "single_vs_full_brier": (round(single - baseline_brier, 4)
                                                if single is not None else None)},
                    **influence})
    return out


# ---------------------------------------------------------------------------
# 5) phase breakdown over config predictions
# ---------------------------------------------------------------------------

def phase_breakdown_from_configs(
    records: List[PredictionRecord],
    preds_by_config: Dict[str, Dict[str, ModelPrediction]],
    config_names: List[str],
) -> Dict[str, Any]:
    from football_simulation.backtest.metrics import full_metrics

    out: Dict[str, Any] = {}
    n = len(records)
    for phase, (start, end) in {"early_season": (0, n // 3),
                                 "mid_season": (n // 3, 2 * n // 3),
                                 "late_season": (2 * n // 3, n)}.items():
        out[phase] = {}
        for config in config_names:
            chunk = []
            for record in records[start:end]:
                pred = preds_by_config.get(config, {}).get(record.match_id)
                if pred is None:
                    continue
                chunk.append(PredictionRecord(
                    match_id=record.match_id, kickoff=record.kickoff,
                    home_team=record.home_team, away_team=record.away_team,
                    actual_home_goals=record.actual_home_goals,
                    actual_away_goals=record.actual_away_goals,
                    predictions={"m": pred}, synthetic=False))
            if chunk:
                one = full_metrics(chunk, "m")["one_x_two"]
                cal = full_metrics(chunk, "m")["calibration"]
                out[phase][config] = {"n": one["n"], "accuracy": one["accuracy"],
                                      "brier": one["brier"], "log_loss": one["log_loss"],
                                      "ece": cal["ece"]}
    return out


# ---------------------------------------------------------------------------
# 6) Elo information-coverage analysis
# ---------------------------------------------------------------------------

def elo_coverage(
    records: List[PredictionRecord],
    team_preds: Dict[str, ModelPrediction],
) -> Dict[str, Any]:
    elo_home = []
    team_home = []
    actuals = []
    elo_correct = 0
    team_correct = 0
    both_correct = 0
    elo_wrong_team_right = 0
    team_wrong_elo_right = 0
    both_wrong = 0
    n = 0
    for record in records:
        elo = record.predictions.get("elo")
        team = team_preds.get(record.match_id)
        if elo is None or team is None:
            continue
        n += 1
        actual = record.actual_result()
        elo_home.append(elo.home_win)
        team_home.append(team.home_win)
        actuals.append(1.0 if actual == "home_win" else (0.5 if actual == "draw" else 0.0))
        e_ok = max(elo.home_win, elo.draw, elo.away_win) == getattr(elo, actual)
        t_ok = max(team.home_win, team.draw, team.away_win) == getattr(team, actual)
        elo_correct += e_ok
        team_correct += t_ok
        both_correct += e_ok and t_ok
        elo_wrong_team_right += (not e_ok) and t_ok
        team_wrong_elo_right += e_ok and (not t_ok)
        both_wrong += (not e_ok) and (not t_ok)
    residual = []
    for e, t in zip(elo_home, team_home):
        residual.append(t - e)
    correlation = float(np.corrcoef(elo_home, team_home)[0, 1])
    residual_corr_with_outcome = float(np.corrcoef(residual, actuals)[0, 1])
    return {
        "n": n,
        "corr_team_elo_home_prob": round(correlation, 4),
        "team_elo_correct": round(team_correct / n, 4),
        "elo_correct": round(elo_correct / n, 4),
        "both_correct": round(both_correct / n, 4),
        "elo_wrong_team_right": round(elo_wrong_team_right / n, 4),
        "team_wrong_elo_right": round(team_wrong_elo_right / n, 4),
        "both_wrong": round(both_wrong / n, 4),
        "residual_team_minus_elo_corr_with_outcome": round(residual_corr_with_outcome, 4),
    }
