"""Generate the SYNTHETIC mock fixture set used by MockDataProvider.

Everything here is fake development data (seeded, deterministic): no real
football statistics, no fabricated "unknown" values - unknowns stay unknown.

Usage:
    python scripts/generate_fixtures.py
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "src" / "football_simulation" / "data" / "fixtures"

KICKOFF = datetime(2026, 8, 20, 18, 30, tzinfo=timezone.utc)
PAST_KICKOFF = datetime(2026, 8, 13, 18, 30, tzinfo=timezone.utc)

FIRST_NAMES = [
    "Alex", "Bruno", "Carlo", "Diego", "Elias", "Felix", "Gustavo", "Hugo",
    "Iker", "Jonas", "Kai", "Leon", "Marco", "Nico", "Oscar", "Paulo",
    "Rafa", "Sam", "Timo", "Viktor", "Yann", "Zack",
]
LAST_NAMES = [
    "Alder", "Becker", "Costa", "Drake", "Evers", "Fischer", "Gomes", "Hart",
    "Ibanez", "Jansen", "Keller", "Lopez", "Meyer", "Novak", "Olsen", "Perez",
    "Quinn", "Rossi", "Silva", "Tanner",
]

# team_id -> (name, short, competition, coach data, style data)
TEAMS = {
    "team-ars": ("Arsenal", "ARS", "premier_league", "coach-ars",
                 dict(preferred_formation="4-3-3", build_up_style="positional",
                      pressing_style="high_press", defensive_line=0.62,
                      transition_style="counter_press", counter_attack_strength=0.45,
                      possession_preference=0.66, crossing_preference=0.35,
                      central_attack_preference=0.55, wing_attack_preference=0.55,
                      set_piece_strength=0.55, set_piece_defense=0.55,
                      attack_strength=0.78, defense_strength=0.72, goalkeeper_strength=0.74,
                      midfield_strength=0.80, squad_depth=0.62, elo_rating=1750)),
    "team-che": ("Chelsea", "CHE", "premier_league", "coach-che",
                 dict(preferred_formation="4-2-3-1", build_up_style="mixed",
                      pressing_style="mid_block", defensive_line=0.50,
                      transition_style="balanced", counter_attack_strength=0.55,
                      possession_preference=0.54, crossing_preference=0.45,
                      central_attack_preference=0.45, wing_attack_preference=0.50,
                      set_piece_strength=0.50, set_piece_defense=0.58,
                      attack_strength=0.68, defense_strength=0.70, goalkeeper_strength=0.70,
                      midfield_strength=0.72, squad_depth=0.66, elo_rating=1680)),
    "team-rma": ("Real Madrid", "RMA", "la_liga", "coach-rma",
                 dict(preferred_formation="4-3-3", build_up_style="mixed",
                      pressing_style="high_press", defensive_line=0.58,
                      transition_style="direct", counter_attack_strength=0.72,
                      possession_preference=0.58, crossing_preference=0.40,
                      central_attack_preference=0.55, wing_attack_preference=0.50,
                      set_piece_strength=0.62, set_piece_defense=0.55,
                      attack_strength=0.82, defense_strength=0.76, goalkeeper_strength=0.80,
                      midfield_strength=0.80, squad_depth=0.62, elo_rating=1780)),
    "team-bar": ("Barcelona", "BAR", "la_liga", "coach-bar",
                 dict(preferred_formation="4-3-3", build_up_style="positional",
                      pressing_style="high_press", defensive_line=0.66,
                      transition_style="counter_press", counter_attack_strength=0.40,
                      possession_preference=0.70, crossing_preference=0.30,
                      central_attack_preference=0.62, wing_attack_preference=0.45,
                      set_piece_strength=0.50, set_piece_defense=0.48,
                      attack_strength=0.80, defense_strength=0.68, goalkeeper_strength=0.74,
                      midfield_strength=0.82, squad_depth=0.60, elo_rating=1760)),
    "team-bay": ("Bayern Munich", "BAY", "bundesliga", "coach-bay",
                 dict(preferred_formation="4-2-3-1", build_up_style="direct",
                      pressing_style="high_press", defensive_line=0.60,
                      transition_style="direct", counter_attack_strength=0.55,
                      possession_preference=0.62, crossing_preference=0.45,
                      central_attack_preference=0.50, wing_attack_preference=0.52,
                      set_piece_strength=0.60, set_piece_defense=0.60,
                      attack_strength=0.82, defense_strength=0.74, goalkeeper_strength=0.78,
                      midfield_strength=0.80, squad_depth=0.70, elo_rating=1770)),
    "team-bvb": ("Borussia Dortmund", "BVB", "bundesliga", "coach-bvb",
                 dict(preferred_formation="4-3-3", build_up_style="mixed",
                      pressing_style="high_press", defensive_line=0.56,
                      transition_style="direct", counter_attack_strength=0.70,
                      possession_preference=0.56, crossing_preference=0.40,
                      central_attack_preference=0.48, wing_attack_preference=0.54,
                      set_piece_strength=0.48, set_piece_defense=0.46,
                      attack_strength=0.74, defense_strength=0.64, goalkeeper_strength=0.66,
                      midfield_strength=0.70, squad_depth=0.55, elo_rating=1650)),
    "team-int": ("Inter", "INT", "serie_a", "coach-int",
                 dict(preferred_formation="3-5-2", build_up_style="mixed",
                      pressing_style="mid_block", defensive_line=0.42,
                      transition_style="balanced", counter_attack_strength=0.50,
                      possession_preference=0.55, crossing_preference=0.42,
                      central_attack_preference=0.50, wing_attack_preference=0.42,
                      set_piece_strength=0.64, set_piece_defense=0.66,
                      attack_strength=0.70, defense_strength=0.80, goalkeeper_strength=0.78,
                      midfield_strength=0.74, squad_depth=0.62, elo_rating=1700)),
    "team-mil": ("AC Milan", "MIL", "serie_a", "coach-mil",
                 dict(preferred_formation="4-2-3-1", build_up_style="direct",
                      pressing_style="low_block", defensive_line=0.38,
                      transition_style="direct", counter_attack_strength=0.60,
                      possession_preference=0.48, crossing_preference=0.45,
                      central_attack_preference=0.42, wing_attack_preference=0.48,
                      set_piece_strength=0.52, set_piece_defense=0.58,
                      attack_strength=0.66, defense_strength=0.72, goalkeeper_strength=0.72,
                      midfield_strength=0.68, squad_depth=0.55, elo_rating=1630)),
    "team-psg": ("Paris Saint-Germain", "PSG", "ligue_1", "coach-psg",
                 dict(preferred_formation="4-3-3", build_up_style="positional",
                      pressing_style="high_press", defensive_line=0.60,
                      transition_style="balanced", counter_attack_strength=0.50,
                      possession_preference=0.68, crossing_preference=0.35,
                      central_attack_preference=0.60, wing_attack_preference=0.48,
                      set_piece_strength=0.58, set_piece_defense=0.52,
                      attack_strength=0.84, defense_strength=0.70, goalkeeper_strength=0.76,
                      midfield_strength=0.78, squad_depth=0.60, elo_rating=1740)),
    "team-om": ("Marseille", "OM", "ligue_1", "coach-om",
                dict(preferred_formation="4-2-3-1", build_up_style="mixed",
                     pressing_style="mid_block", defensive_line=0.46,
                     transition_style="direct", counter_attack_strength=0.58,
                     possession_preference=0.52, crossing_preference=0.48,
                     central_attack_preference=0.42, wing_attack_preference=0.50,
                     set_piece_strength=0.48, set_piece_defense=0.46,
                     attack_strength=0.66, defense_strength=0.62, goalkeeper_strength=0.64,
                     midfield_strength=0.64, squad_depth=0.50, elo_rating=1580)),
}

COACH_BEHAVIORS = {
    "coach-ars": dict(name="Viktor Hale", preferred_formations=["4-3-3", "4-2-3-1"],
                      tactical_flexibility=0.55, substitution_timing={"early": 0.15, "mid": 0.55, "late": 0.30},
                      substitution_patterns=["attacking_replacement", "fatigue_rotation"],
                      reaction_to_leading="moderate", reaction_to_trailing="aggressive",
                      reaction_to_red_card="balanced", reaction_to_conceding="aggressive",
                      reaction_to_scoring="moderate", rotation_tendency=0.35, risk_tolerance=0.62,
                      big_match_behavior="cautious", late_game_behavior="game_management",
                      aggressiveness=0.70),
    "coach-che": dict(name="Nils Brandt", preferred_formations=["4-2-3-1", "4-3-3"],
                      tactical_flexibility=0.62, substitution_timing={"early": 0.20, "mid": 0.50, "late": 0.30},
                      substitution_patterns=["tactical_switch", "fatigue_rotation"],
                      reaction_to_leading="defensive", reaction_to_trailing="moderate",
                      reaction_to_red_card="defensive", reaction_to_conceding="moderate",
                      reaction_to_scoring="moderate", rotation_tendency=0.55, risk_tolerance=0.50,
                      big_match_behavior="pragmatic", late_game_behavior="game_management",
                      aggressiveness=0.55),
    "coach-rma": dict(name="Diego Alvaro", preferred_formations=["4-3-3", "4-4-2"],
                      tactical_flexibility=0.58, substitution_timing={"early": 0.15, "mid": 0.55, "late": 0.30},
                      substitution_patterns=["attacking_replacement", "tactical_switch"],
                      reaction_to_leading="moderate", reaction_to_trailing="aggressive",
                      reaction_to_red_card="balanced", reaction_to_conceding="aggressive",
                      reaction_to_scoring="moderate", rotation_tendency=0.40, risk_tolerance=0.68,
                      big_match_behavior="cautious", late_game_behavior="push_for_winner",
                      aggressiveness=0.72),
    "coach-bar": dict(name="Pau Segura", preferred_formations=["4-3-3", "3-4-3"],
                      tactical_flexibility=0.50, substitution_timing={"early": 0.15, "mid": 0.60, "late": 0.25},
                      substitution_patterns=["attacking_replacement", "young_player_introduction"],
                      reaction_to_leading="moderate", reaction_to_trailing="aggressive",
                      reaction_to_red_card="balanced", reaction_to_conceding="moderate",
                      reaction_to_scoring="moderate", rotation_tendency=0.45, risk_tolerance=0.60,
                      big_match_behavior="cautious", late_game_behavior="game_management",
                      aggressiveness=0.68),
    "coach-bay": dict(name="Lukas Steiner", preferred_formations=["4-2-3-1", "4-3-3"],
                      tactical_flexibility=0.55, substitution_timing={"early": 0.15, "mid": 0.55, "late": 0.30},
                      substitution_patterns=["fatigue_rotation", "attacking_replacement"],
                      reaction_to_leading="moderate", reaction_to_trailing="aggressive",
                      reaction_to_red_card="defensive", reaction_to_conceding="moderate",
                      reaction_to_scoring="moderate", rotation_tendency=0.40, risk_tolerance=0.64,
                      big_match_behavior="pragmatic", late_game_behavior="push_for_winner",
                      aggressiveness=0.70),
    "coach-bvb": dict(name="Felix Krüger", preferred_formations=["4-3-3", "4-2-3-1"],
                      tactical_flexibility=0.60, substitution_timing={"early": 0.25, "mid": 0.50, "late": 0.25},
                      substitution_patterns=["young_player_introduction", "fatigue_rotation"],
                      reaction_to_leading="moderate", reaction_to_trailing="aggressive",
                      reaction_to_red_card="balanced", reaction_to_conceding="aggressive",
                      reaction_to_scoring="moderate", rotation_tendency=0.60, risk_tolerance=0.70,
                      big_match_behavior="pragmatic", late_game_behavior="push_for_winner",
                      aggressiveness=0.75),
    "coach-int": dict(name="Marco Vitale", preferred_formations=["3-5-2", "5-3-2"],
                      tactical_flexibility=0.55, substitution_timing={"early": 0.10, "mid": 0.55, "late": 0.35},
                      substitution_patterns=["defensive_reinforcement", "tactical_switch"],
                      reaction_to_leading="defensive", reaction_to_trailing="moderate",
                      reaction_to_red_card="defensive", reaction_to_conceding="moderate",
                      reaction_to_scoring="defensive", rotation_tendency=0.50, risk_tolerance=0.45,
                      big_match_behavior="cautious", late_game_behavior="game_management",
                      aggressiveness=0.55),
    "coach-mil": dict(name="Stefano Riva", preferred_formations=["4-2-3-1", "4-4-2"],
                      tactical_flexibility=0.55, substitution_timing={"early": 0.15, "mid": 0.55, "late": 0.30},
                      substitution_patterns=["defensive_reinforcement", "tactical_switch"],
                      reaction_to_leading="defensive", reaction_to_trailing="moderate",
                      reaction_to_red_card="defensive", reaction_to_conceding="moderate",
                      reaction_to_scoring="moderate", rotation_tendency=0.45, risk_tolerance=0.48,
                      big_match_behavior="cautious", late_game_behavior="game_management",
                      aggressiveness=0.58),
    "coach-psg": dict(name="Antoine Mercier", preferred_formations=["4-3-3", "4-2-3-1"],
                      tactical_flexibility=0.52, substitution_timing={"early": 0.15, "mid": 0.55, "late": 0.30},
                      substitution_patterns=["attacking_replacement", "fatigue_rotation"],
                      reaction_to_leading="moderate", reaction_to_trailing="aggressive",
                      reaction_to_red_card="balanced", reaction_to_conceding="aggressive",
                      reaction_to_scoring="moderate", rotation_tendency=0.35, risk_tolerance=0.62,
                      big_match_behavior="pragmatic", late_game_behavior="push_for_winner",
                      aggressiveness=0.68),
    "coach-om": dict(name="Karim Benaissa", preferred_formations=["4-2-3-1", "4-3-3"],
                     tactical_flexibility=0.58, substitution_timing={"early": 0.20, "mid": 0.55, "late": 0.25},
                     substitution_patterns=["tactical_switch", "young_player_introduction"],
                     reaction_to_leading="defensive", reaction_to_trailing="aggressive",
                     reaction_to_red_card="defensive", reaction_to_conceding="moderate",
                     reaction_to_scoring="moderate", rotation_tendency=0.50, risk_tolerance=0.55,
                     big_match_behavior="pragmatic", late_game_behavior="push_for_winner",
                     aggressiveness=0.62),
}

POSITION_TEMPLATE = [
    "GK", "GK", "CB", "CB", "CB", "CB", "LB", "RB", "DM", "DM",
    "CM", "CM", "CM", "AM", "AM", "LW", "LW", "RW", "RW", "ST", "ST", "ST",
]

POSITION_BOOST = {
    "ST": dict(finishing=0.12, heading=0.06, pace=0.05),
    "LW": dict(pace=0.08, dribbling=0.10, crossing=0.06),
    "RW": dict(pace=0.08, dribbling=0.10, crossing=0.06),
    "CB": dict(tackling=0.12, marking=0.12, heading=0.08, interceptions=0.06),
    "LB": dict(tackling=0.06, pace=0.08, crossing=0.08, marking=0.04),
    "RB": dict(tackling=0.06, pace=0.08, crossing=0.08, marking=0.04),
    "DM": dict(tackling=0.10, interceptions=0.12, positioning=0.06),
    "CM": dict(passing=0.10, vision=0.08, decisions=0.06),
    "AM": dict(vision=0.10, dribbling=0.08, finishing=0.06, long_shots=0.06),
}

TECHNICAL_KEYS = ["finishing", "long_shots", "passing", "vision", "dribbling", "first_touch",
                  "crossing", "set_pieces", "heading", "tackling", "marking", "interceptions"]
PHYSICAL_KEYS = ["pace", "acceleration", "stamina", "strength", "agility", "balance", "jumping"]
MENTAL_KEYS = ["composure", "concentration", "decisions", "positioning", "aggression",
               "bravery", "work_rate", "leadership"]
BEHAVIOR_KEYS = ["pressing_behavior", "progression_behavior", "passing_behavior",
                 "shooting_behavior", "defensive_behavior", "transition_behavior"]


def clip(x, lo=0.05, hi=0.95):
    return max(lo, min(hi, float(x)))


def make_players(rng: np.random.Generator, team_id: str, style: dict, base_q: float):
    players = []
    names = set()
    for i, position in enumerate(POSITION_TEMPLATE):
        while True:
            name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
            if name not in names:
                names.add(name)
                break
        q = clip(rng.normal(base_q, 0.10), 0.35, 0.92)
        tech = {}
        for key in TECHNICAL_KEYS:
            tech[key] = clip(q + rng.normal(0, 0.07) + POSITION_BOOST.get(position, {}).get(key, 0))
        phys = {}
        for key in PHYSICAL_KEYS:
            phys[key] = clip(q + rng.normal(0, 0.07) + POSITION_BOOST.get(position, {}).get(key, 0))
        ment = {}
        for key in MENTAL_KEYS:
            ment[key] = clip(q + rng.normal(0, 0.07) + POSITION_BOOST.get(position, {}).get(key, 0))
        behaviors = {}
        for key in BEHAVIOR_KEYS:
            behaviors[key] = clip(rng.normal(0.5, 0.15))
        players.append(dict(
            player_id=f"{team_id}-p{i:02d}", name=name, team_id=team_id,
            age=int(rng.integers(18, 34)), position=position,
            role="balanced", preferred_side=rng.choice(["left", "right", "both", "none"]),
            technical=tech, physical=phys, mental=ment, behaviors=behaviors,
            fatigue_sensitivity=clip(rng.normal(0.5, 0.15), 0.2, 0.9),
            injury_risk=clip(rng.normal(0.18, 0.10), 0.03, 0.55),
            form=clip(rng.normal(0.55, 0.12), 0.2, 0.95),
            confidence=clip(rng.normal(0.55, 0.12), 0.2, 0.95),
            discipline=clip(rng.normal(0.55, 0.15), 0.2, 0.9),
            tactical_fit=clip(rng.normal(0.6, 0.15), 0.2, 0.95),
        ))
    return players


def player_quality(p: dict) -> float:
    tech = (p["technical"]["passing"] + p["technical"]["finishing"]
            + p["technical"]["first_touch"] + p["technical"]["dribbling"]) / 4
    phys = (p["physical"]["pace"] + p["physical"]["stamina"] + p["physical"]["strength"]) / 3
    ment = (p["mental"]["composure"] + p["mental"]["decisions"] + p["mental"]["concentration"]) / 3
    return 0.4 * tech + 0.25 * phys + 0.25 * ment + 0.1 * p["form"]


def make_history(rng: np.random.Generator, team_id: str, team_name: str, style: dict,
                 opponents: list, start: datetime) -> list:
    entries = []
    attack = style["attack_strength"]
    defense = style["defense_strength"]
    date = start - timedelta(days=7)
    for i in range(10):
        opp = opponents[rng.integers(len(opponents))]
        home = rng.random() < 0.5
        opp_atk = 0.68
        opp_def = 0.68
        lam_for = 1.45 * (0.55 + attack - opp_def)
        lam_against = 1.45 * (0.55 + opp_atk - defense)
        gf = int(rng.poisson(lam_for))
        ga = int(rng.poisson(lam_against))
        entries.append(dict(
            date=date.isoformat(), opponent=opp, home=home,
            goals_for=gf, goals_against=ga,
            xg_for=round(gf + rng.normal(0, 0.5), 2),
            xg_against=round(ga + rng.normal(0, 0.5), 2),
            competition="league",
        ))
        date -= timedelta(days=7)
    return entries


def elo_to_prob(home_elo: float, away_elo: float) -> tuple:
    diff = home_elo - away_elo + 55  # home advantage
    p_home_raw = 1 / (1 + 10 ** (-diff / 400))
    p_draw = 0.24 + 0.04 * (1 - abs(diff) / 400)
    remaining = 1 - p_draw
    p_home = p_home_raw * remaining
    p_away = (1 - p_home_raw) * remaining
    return p_home, p_draw, p_away


def main() -> None:
    rng = np.random.default_rng(20260820)
    FIXTURES.mkdir(parents=True, exist_ok=True)

    teams_payload, players_payload, coaches_payload = [], [], []
    team_names = {tid: info[0] for tid, info in TEAMS.items()}
    all_team_ids = list(TEAMS.keys())

    for team_id, (name, short, comp, coach_id, style) in TEAMS.items():
        teams_payload.append(dict(team_id=team_id, name=name, short_name=short,
                                  competition_id=comp, coach_id=coach_id, **style))
        coaches_payload.append(dict(coach_id=coach_id, team_id=team_id, **COACH_BEHAVIORS[coach_id]))
        base_q = 0.5 * style["attack_strength"] + 0.3 * style["midfield_strength"] + 0.2 * style["defense_strength"]
        for p in make_players(rng, team_id, style, base_q):
            players_payload.append(p)

    referees_payload = []
    referee_names = ["R. Keller", "M. Dupont", "A. Rossi", "J. Van Dijk", "P. García",
                     "S. Weber", "L. Fontaine", "G. Moretti"]
    for i, name in enumerate(referee_names):
        referees_payload.append(dict(
            referee_id=f"ref-{i:02d}", name=name, competition_id="premier_league",
            yellow_card_tendency=round(float(rng.uniform(0.38, 0.62)), 3),
            red_card_tendency=round(float(rng.uniform(0.38, 0.62)), 3),
            penalty_tendency=round(float(rng.uniform(0.38, 0.62)), 3),
            foul_tolerance=round(float(rng.uniform(0.38, 0.62)), 3),
            advantage_play=round(float(rng.uniform(0.40, 0.70)), 3),
            var_interaction=round(float(rng.uniform(0.40, 0.70)), 3),
            matches_officiated=int(rng.integers(60, 260)),
        ))

    # ----- demo (future) match & past match --------------------------------
    demo_match = "match-demo-001"
    past_match = "match-demo-000"

    # Lineups: best available 11 start; drop injured players.
    injuries_payload = []
    lineups_payload = []
    for team_id, (name, short, comp, coach_id, style) in TEAMS.items():
        squad = [p for p in players_payload if p["team_id"] == team_id]
        squad_sorted = sorted(squad, key=lambda p: -player_quality(p))
        injured = []
        n_inj = 2 if team_id in ("team-ars", "team-che") else int(rng.integers(1, 3))
        for _ in range(n_inj):
            target = squad_sorted[int(rng.integers(1, 6))]  # can hit regulars
            injured.append(target["player_id"])
            injuries_payload.append(dict(
                player_id=target["player_id"], team_id=team_id,
                injury_type=rng.choice(["muscle", "ankle", "knee", "illness", "hamstring"]),
                severity=round(float(rng.uniform(0.3, 0.85)), 3),
                expected_return=(KICKOFF + timedelta(days=10)).isoformat(),
                known_at=(KICKOFF - timedelta(days=3)).isoformat(),
            ))
        available = [p for p in squad_sorted if p["player_id"] not in injured]
        starters = [p["player_id"] for p in available[:11]]
        bench = [p["player_id"] for p in available[11:22]]
        captain = starters[4]
        lineups_payload.append(dict(
            match_id=demo_match, team_id=team_id,
            formation=style["preferred_formation"], starters=starters, bench=bench,
            captain=captain, confirmed=True,
            reported_at=(KICKOFF - timedelta(hours=1)).isoformat(),
        ))

    histories_payload = []
    for team_id, (name, short, comp, coach_id, style) in TEAMS.items():
        opponents = [team_names[t] for t in all_team_ids if t != team_id]
        entries = make_history(rng, team_id, name, style, opponents, KICKOFF)
        histories_payload.append(dict(
            team_id=team_id, competition_id=comp, season="2026-27", entries=entries, complete=True
        ))

    ph, pd, pa = elo_to_prob(TEAMS["team-ars"][4]["elo_rating"], TEAMS["team-che"][4]["elo_rating"])
    matches_payload = [
        dict(
            request=dict(
                match_id=demo_match, home_team_id="team-ars", away_team_id="team-che",
                competition_id="premier_league", season="2026-27",
                kickoff=KICKOFF.isoformat(), venue="Emirates Stadium",
                as_of=(KICKOFF - timedelta(hours=2)).isoformat(),
            ),
            referee_id="ref-03",
        ),
        dict(
            request=dict(
                match_id=past_match, home_team_id="team-ars", away_team_id="team-che",
                competition_id="premier_league", season="2026-27",
                kickoff=PAST_KICKOFF.isoformat(), venue="Emirates Stadium",
                as_of=(PAST_KICKOFF - timedelta(hours=2)).isoformat(),
            ),
            referee_id="ref-01",
        ),
    ]

    weather_payload = [dict(
        match_id=demo_match, venue="Emirates Stadium", temperature_c=21.0,
        humidity=0.55, rain=0.10, wind=0.20, pitch_condition=0.90, altitude_m=35,
        forecast_at=(KICKOFF - timedelta(hours=6)).isoformat(), known=True,
    )]

    odds_payload = [dict(
        match_id=demo_match, home_win=round(1 / ph, 2), draw=round(1 / pd, 2),
        away_win=round(1 / pa, 2), over_under_line=2.5,
        as_of=(KICKOFF - timedelta(hours=2)).isoformat(), bookmaker="mockbook",
    )]

    results_payload = [dict(
        match_id=past_match, kickoff=PAST_KICKOFF.isoformat(),
        score_home=2, score_away=1, ht_score_home=1, ht_score_away=0,
        xg_home=1.9, xg_away=1.1, possession_home=0.58,
        shots_home=14, shots_away=9, shots_on_target_home=6, shots_on_target_away=3,
        corners_home=7, corners_away=4, fouls_home=10, fouls_away=13,
        yellow_cards_home=2, yellow_cards_away=3, red_cards_home=0, red_cards_away=1,
        home_formation="4-3-3", away_formation="4-2-3-1",
        home_pressing_style="high_press", away_pressing_style="mid_block",
        home_starters=[p["player_id"] for p in players_payload if p["team_id"] == "team-ars"][:11],
        away_starters=[p["player_id"] for p in players_payload if p["team_id"] == "team-che"][:11],
        available=True,
        events=[
            dict(event_id="e-1", match_id=past_match, minute=14, second=0, side="home",
                 event_type="shot", player_id="team-ars-p10", detail="off_target", xg=0.12,
                 probability=0.0, state_before_version=0, state_after_version=0, scenario_tag=""),
            dict(event_id="e-2", match_id=past_match, minute=23, second=0, side="home",
                 event_type="goal", player_id="team-ars-p09", detail="open_play",
                 xg=0.31, probability=0.0, state_before_version=0, state_after_version=0, scenario_tag=""),
            dict(event_id="e-3", match_id=past_match, minute=41, second=0, side="away",
                 event_type="yellow_card", player_id="team-che-p06", detail="tactical_foul",
                 xg=0.0, probability=0.0, state_before_version=0, state_after_version=0, scenario_tag=""),
            dict(event_id="e-4", match_id=past_match, minute=54, second=0, side="home",
                 event_type="penalty", player_id="team-ars-p09", detail="foul_in_box",
                 xg=0.76, probability=0.0, state_before_version=0, state_after_version=0, scenario_tag=""),
            dict(event_id="e-5", match_id=past_match, minute=55, second=0, side="home",
                 event_type="goal", player_id="team-ars-p09", detail="penalty",
                 xg=0.76, probability=0.0, state_before_version=0, state_after_version=0, scenario_tag=""),
            dict(event_id="e-6", match_id=past_match, minute=67, second=0, side="away",
                 event_type="goal", player_id="team-che-p10", detail="counter_attack",
                 xg=0.22, probability=0.0, state_before_version=0, state_after_version=0, scenario_tag=""),
            dict(event_id="e-7", match_id=past_match, minute=81, second=0, side="away",
                 event_type="red_card", player_id="team-che-p06", detail="second_yellow",
                 xg=0.0, probability=0.0, state_before_version=0, state_after_version=0, scenario_tag=""),
        ],
    )]

    def dump(name, payload_obj):
        (FIXTURES / name).write_text(json.dumps(payload_obj, indent=2), encoding="utf-8")

    dump("teams.json", {"note": "SYNTHETIC MOCK DATA", "teams": teams_payload})
    dump("players.json", {"note": "SYNTHETIC MOCK DATA", "players": players_payload})
    dump("coaches.json", {"note": "SYNTHETIC MOCK DATA", "coaches": coaches_payload})
    dump("referees.json", {"note": "SYNTHETIC MOCK DATA", "referees": referees_payload})
    dump("lineups.json", {"note": "SYNTHETIC MOCK DATA", "lineups": lineups_payload})
    dump("injuries.json", {"note": "SYNTHETIC MOCK DATA", "injuries": injuries_payload})
    dump("history.json", {"note": "SYNTHETIC MOCK DATA", "histories": histories_payload})
    dump("weather.json", {"note": "SYNTHETIC MOCK DATA", "weather": weather_payload})
    dump("odds.json", {"note": "SYNTHETIC MOCK DATA", "odds": odds_payload})
    dump("matches.json", {"note": "SYNTHETIC MOCK DATA", "matches": matches_payload})
    dump("results.json", {"note": "SYNTHETIC MOCK DATA", "results": results_payload})

    print(f"Fixtures written to {FIXTURES}")
    print(f"  teams={len(teams_payload)} players={len(players_payload)} coaches={len(coaches_payload)}")
    print(f"  referees={len(referees_payload)} injuries={len(injuries_payload)}")
    print(f"  demo match={demo_match} (Arsenal vs Chelsea, {KICKOFF.isoformat()})")
    print(f"  past match={past_match} with result for learning/evaluation demos")


if __name__ == "__main__":
    main()
