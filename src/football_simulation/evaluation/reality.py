"""V1.1 Reality Harness.

Builds FULLY CONTROLLED synthetic worlds (two teams whose strength/style
knobs are explicit), runs paired simulation batches with identical seeds, and
computes football metrics.  This is the measurement instrument for the
common-sense scenario tests, causal-direction tests and the anomaly detector.

Nothing here touches real data and nothing here hardcodes expected results:
it only measures what the existing causal chain (strength -> chance creation
-> xG -> goals -> score -> result) produces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from football_simulation.agents.momentum import MomentumAgent
from football_simulation.agents.substitution import SubstitutionAgent
from football_simulation.agents.tactical import TacticalMatchupAgent
from football_simulation.core.event_engine import EventTriggerAgent
from football_simulation.core.rng import SeedableRNG
from football_simulation.core.rule_engine import RuleEngine
from football_simulation.core.simulation_engine import MatchSimulationEngine, SimulationConfig
from football_simulation.core.state_machine import StateTransitionAgent
from football_simulation.knowledge import load_all_knowledge
from football_simulation.models.base import Side
from football_simulation.models.entities import (
    CoachState,
    PlayerProfile,
    PlayerState,
    Position,
    TeamProfile,
    TeamState,
)
from football_simulation.models.events import EventType, MatchEvent
from football_simulation.models.simulation import SimulationBatch
from football_simulation.models.world import (
    LineupState,
    PsychologicalState,
    RefereeMatchState,
    TacticalMatchupState,
    WeatherState,
    WorldState,
)

_POSITIONS = [
    Position.GK, Position.CB, Position.CB, Position.LB, Position.RB,
    Position.DM, Position.CM, Position.CM, Position.AM, Position.LW, Position.RW,
    Position.ST, Position.GK, Position.CB, Position.DM, Position.CM,
    Position.AM, Position.LW, Position.RW, Position.ST, Position.CB, Position.ST,
]

_BOOST = {
    Position.ST: {"finishing": 0.10, "pace": 0.05},
    Position.LW: {"pace": 0.07, "dribbling": 0.08},
    Position.RW: {"pace": 0.07, "dribbling": 0.08},
    Position.CB: {"tackling": 0.10, "marking": 0.10},
    Position.LB: {"tackling": 0.05, "pace": 0.07},
    Position.RB: {"tackling": 0.05, "pace": 0.07},
    Position.DM: {"tackling": 0.08, "interceptions": 0.10},
    Position.CM: {"passing": 0.08, "vision": 0.06},
    Position.AM: {"vision": 0.08, "finishing": 0.05},
}


def _stable_hash(text: str) -> int:
    value = 2166136261
    for ch in text:
        value = ((value ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return value


@dataclass
class TeamSpec:
    """Explicit, controllable knobs for one controlled team."""

    team_id: str
    name: str = ""
    attack: float = 0.5
    defense: float = 0.5
    midfield: float = 0.5
    goalkeeper: float = 0.5
    depth: float = 0.5
    counter_strength: float = 0.5
    defensive_line: float = 0.5
    pressing_style: str = "mid_block"
    build_up_style: str = "mixed"
    possession_preference: float = 0.5
    wing_attack_preference: float = 0.4
    central_attack_preference: float = 0.4
    set_piece_strength: float = 0.5
    set_piece_defense: float = 0.5
    home_advantage: float = 0.04
    elo_rating: float = 1500.0


def balanced_pair(home_id: str = "home", away_id: str = "away", value: float = 0.5) -> Tuple[TeamSpec, TeamSpec]:
    """Two identical teams - the control condition for causality tests."""
    kwargs = dict(attack=value, defense=value, midfield=value, goalkeeper=value, depth=value)
    return TeamSpec(team_id=home_id, name=home_id, **kwargs), TeamSpec(
        team_id=away_id, name=away_id, **kwargs)


class RealityHarness:
    def __init__(self):
        self.knowledge = load_all_knowledge()
        self.rule_engine = RuleEngine(self.knowledge["rules"])
        self.momentum = MomentumAgent()
        self.event_agent = EventTriggerAgent(self.knowledge["event_defaults"])
        self.sub_agent = SubstitutionAgent()

    # ------------------------------------------------------------------
    def build_world(
        self,
        home: TeamSpec,
        away: TeamSpec,
        score_home: int = 0,
        score_away: int = 0,
        minute: int = 0,
        red_home: int = 0,
        red_away: int = 0,
        fatigue_home: float = 0.0,
        fatigue_away: float = 0.0,
        weather: Optional[WeatherState] = None,
        referee: Optional[RefereeMatchState] = None,
        coach_home: Optional[CoachState] = None,
        coach_away: Optional[CoachState] = None,
        psych_home: Optional[PsychologicalState] = None,
        psych_away: Optional[PsychologicalState] = None,
    ) -> Tuple[WorldState, TacticalMatchupState]:
        home_state = self._team_state(home)
        away_state = self._team_state(away)
        home_players = self._squad(home, home_state)
        away_players = self._squad(away, away_state)

        world = WorldState(
            match_id=f"reality-{home.team_id}-vs-{away.team_id}",
            home_team=home.team_id,
            away_team=away.team_id,
            home_team_state=home_state,
            away_team_state=away_state,
            home_coach=coach_home or CoachState(coach_id=f"c-{home.team_id}"),
            away_coach=coach_away or CoachState(coach_id=f"c-{away.team_id}"),
            home_players=home_players,
            away_players=away_players,
            home_lineup=self._lineup(home.team_id, home_state, home_players),
            away_lineup=self._lineup(away.team_id, away_state, away_players),
            home_psychological_state=psych_home or PsychologicalState(side=Side.HOME),
            away_psychological_state=psych_away or PsychologicalState(side=Side.AWAY),
            weather_state=weather or WeatherState(known=False),
            referee_state=referee or RefereeMatchState(known=False),
            score_home=score_home,
            score_away=score_away,
            current_minute=minute,
            # red cards are injected below through the REAL state machine
            fatigue_home=fatigue_home,
            fatigue_away=fatigue_away,
        )

        matchup = TacticalMatchupAgent().analyze(
            home_state, away_state, self.knowledge["tactical_patterns"]
        )[0]
        world = world.evolution_snapshot(matchup_state=matchup)
        # player counts are adjusted by the red-card events below (through the
        # real state machine), so tactics start from a full XI
        world = self._apply_matchup_to_tactics(world, matchup, 0, 0)
        world = self._apply_pregame_fatigue(world, fatigue_home, fatigue_away)
        sm = StateTransitionAgent(self.rule_engine, self.momentum)
        world = sm._sync_mentalities(world)
        # apply the knowledge rules ONCE at build time (mirrors what the
        # engine does on the first event) so injected mid-match states carry
        # the same rule effects as engine-evolved states
        world, _ = self.rule_engine.apply_state(world)
        world = sm._sync_mentalities(world)
        # red cards are injected through the REAL state machine so formation
        # changes and rule effects match an evolved state
        for side, count in ((Side.HOME, red_home), (Side.AWAY, red_away)):
            for _ in range(count):
                red = MatchEvent(
                    minute=world.current_minute, second=0, side=side,
                    event_type=EventType.RED_CARD, player_id=f"{world.team_id(side)}-p03",
                    state_before_version=world.state_version,
                    state_after_version=world.state_version,
                )
                world = sm.apply_event(world, red)
        return world, matchup

    def _team_state(self, spec: TeamSpec) -> TeamState:
        return TeamState(
            team_id=spec.team_id,
            name=spec.name or spec.team_id,
            preferred_formation="4-3-3",
            build_up_style=spec.build_up_style,
            pressing_style=spec.pressing_style,
            defensive_line=spec.defensive_line,
            counter_attack_strength=spec.counter_strength,
            possession_preference=spec.possession_preference,
            wing_attack_preference=spec.wing_attack_preference,
            central_attack_preference=spec.central_attack_preference,
            set_piece_strength=spec.set_piece_strength,
            set_piece_defense=spec.set_piece_defense,
            attack_strength=spec.attack,
            defense_strength=spec.defense,
            midfield_strength=spec.midfield,
            goalkeeper_strength=spec.goalkeeper,
            squad_depth=spec.depth,
            home_advantage=spec.home_advantage,
            elo_rating=spec.elo_rating,
        )

    def _squad(self, spec: TeamSpec, team_state: TeamState) -> Dict[str, PlayerState]:
        rng = SeedableRNG(_stable_hash(spec.team_id))
        base = 0.3 * spec.attack + 0.3 * spec.midfield + 0.2 * spec.defense + 0.2 * spec.goalkeeper
        players: Dict[str, PlayerState] = {}
        for i, position in enumerate(_POSITIONS):
            pid = f"{spec.team_id}-p{i:02d}"
            quality = max(0.25, min(0.92, base + rng.normal(0, 0.07)))
            boost = _BOOST.get(position, {})
            technical = {
                key: max(0.2, min(0.95, quality + rng.normal(0, 0.06) + boost.get(key, 0.0)))
                for key in ("finishing", "long_shots", "passing", "vision", "dribbling",
                            "first_touch", "crossing", "set_pieces", "heading",
                            "tackling", "marking", "interceptions")
            }
            physical = {
                key: max(0.2, min(0.95, quality + rng.normal(0, 0.06) + boost.get(key, 0.0)))
                for key in ("pace", "acceleration", "stamina", "strength",
                            "agility", "balance", "jumping")
            }
            mental = {
                key: max(0.2, min(0.95, quality + rng.normal(0, 0.06)))
                for key in ("composure", "concentration", "decisions", "positioning",
                            "aggression", "bravery", "work_rate", "leadership")
            }
            players[pid] = PlayerState(
                player_id=pid,
                name=f"{spec.team_id} #{i}",
                team_id=spec.team_id,
                position=position,
                technical=technical,
                physical=physical,
                mental=mental,
                behaviors={
                    "pressing_behavior": 0.5 + (0.25 if spec.pressing_style == "high_press" else 0.0),
                    "progression_behavior": 0.5,
                    "passing_behavior": 0.5,
                    "shooting_behavior": 0.5,
                    "defensive_behavior": 0.5,
                    "transition_behavior": 0.5,
                },
                fatigue_sensitivity=0.5,
                injury_risk=0.2,
                form=0.5,
                confidence=0.5,
                discipline=0.5,
                tactical_fit=0.6,
                starting=i < 11,
                current_fatigue=0.0,
            )
        return players

    def _lineup(self, team_id: str, team_state: TeamState, players: Dict[str, PlayerState]) -> LineupState:
        starters = [p.player_id for p in players.values() if p.starting][:11]
        bench = [p.player_id for p in players.values() if not p.starting][:11]
        return LineupState(team_id=team_id, formation=team_state.preferred_formation,
                           starters=starters, bench=bench, confirmed=True)

    def _apply_matchup_to_tactics(
        self, world: WorldState, matchup: TacticalMatchupState, red_home: int, red_away: int
    ) -> WorldState:
        home_tac = world.home_tactical_state.model_copy(
            update={
                "chance_creation_modifier": matchup.chance_creation_home,
                "counter_strength_current": world.home_team_state.counter_attack_strength,
                "transition_risk": matchup.transition_risk_home,
                "pressing_success_probability": matchup.pressing_success_home,
                "pressing_intensity": 0.5 + (0.15 if world.home_team_state.pressing_style == "high_press" else 0.0),
                "players_on_pitch": 11 - red_home,
            }
        )
        away_tac = world.away_tactical_state.model_copy(
            update={
                "chance_creation_modifier": matchup.chance_creation_away,
                "counter_strength_current": world.away_team_state.counter_attack_strength,
                "transition_risk": matchup.transition_risk_away,
                "pressing_success_probability": matchup.pressing_success_away,
                "pressing_intensity": 0.5 + (0.15 if world.away_team_state.pressing_style == "high_press" else 0.0),
                "players_on_pitch": 11 - red_away,
            }
        )
        return world.evolution_snapshot(
            home_tactical_state=home_tac, away_tactical_state=away_tac)

    def _apply_pregame_fatigue(self, world: WorldState, f_home: float, f_away: float) -> WorldState:
        home_players = {
            pid: p.model_copy(update={"current_fatigue": min(0.95, f_home)})
            for pid, p in world.home_players.items() if p.starting
        }
        away_players = {
            pid: p.model_copy(update={"current_fatigue": min(0.95, f_away)})
            for pid, p in world.away_players.items() if p.starting
        }
        return world.evolution_snapshot(
            home_players={**world.home_players, **home_players},
            away_players={**world.away_players, **away_players},
        )

    # ------------------------------------------------------------------
    def build_engine(self, world: WorldState, matchup: TacticalMatchupState,
                     enable_momentum: bool = True, start_minute: int = 0) -> MatchSimulationEngine:
        sm = StateTransitionAgent(self.rule_engine, self.momentum)
        return MatchSimulationEngine(
            world, self.rule_engine, self.momentum, self.event_agent,
            self.sub_agent, sm, matchup,
            SimulationConfig(default_runs=500, keep_events=True, enable_momentum=enable_momentum,
                             start_minute=start_minute),
        )

    def run_pair(
        self,
        worlds: Dict[str, WorldState],
        matchups: Dict[str, TacticalMatchupState],
        n: int = 600,
        seed: int = 11,
    ) -> Dict[str, SimulationBatch]:
        """Run the SAME seeds over every world so batches are paired."""
        out: Dict[str, SimulationBatch] = {}
        for key, world in worlds.items():
            engine = self.build_engine(
                world, matchups[key], start_minute=world.current_minute)
            batch = engine.simulate_n_matches(n=n, base_seed=seed, keep_events=True)
            out[key] = batch
        return out


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def batch_metrics(batch: SimulationBatch) -> Dict[str, float]:
    n = max(1, batch.runs)
    m: Dict[str, float] = {}
    wins = {"home": 0, "draw": 0, "away": 0}
    goals = shots_h = shots_a = xg_h = xg_a = 0.0
    goals_home = goals_away = 0.0
    goals_first = goals_second = goals_late = 0.0
    goals_home_late = goals_away_late = 0.0
    shots_h_late = shots_a_late = 0.0
    counter_goals_h_late = counter_goals_a_late = 0.0
    counter_shots_h = counter_shots_a = 0.0
    yellows = reds = pens = 0.0
    tags: Dict[str, int] = {}
    for match in batch.results:
        if match.score_home > match.score_away:
            wins["home"] += 1
        elif match.score_away > match.score_home:
            wins["away"] += 1
        else:
            wins["draw"] += 1
        goals += match.score_home + match.score_away
        goals_home += match.score_home
        goals_away += match.score_away
        shots_h += match.home_stats.shots
        shots_a += match.away_stats.shots
        xg_h += match.home_stats.xg
        xg_a += match.away_stats.xg
        yellows += match.home_stats.yellow_cards + match.away_stats.yellow_cards
        reds += match.home_stats.red_cards + match.away_stats.red_cards
        tags[match.scenario_tag] = tags.get(match.scenario_tag, 0) + 1
        for event in match.events:
            is_goal = event.event_type in (EventType.GOAL, EventType.OWN_GOAL)
            is_shot = event.event_type in (EventType.SHOT, EventType.SHOT_ON_TARGET,
                                           EventType.MISS, EventType.GOAL)
            if is_goal:
                if event.minute < 45:
                    goals_first += 1
                elif event.minute < 75:
                    goals_second += 1
                else:
                    goals_late += 1
                    if event.side is Side.HOME:
                        goals_home_late += 1
                    else:
                        goals_away_late += 1
                if event.minute >= 70 and "counter" in event.detail:
                    if event.side is Side.HOME:
                        counter_goals_h_late += 1
                    else:
                        counter_goals_a_late += 1
            if is_shot:
                if event.minute >= 75:
                    if event.side is Side.HOME:
                        shots_h_late += 1
                    else:
                        shots_a_late += 1
                if "counter" in event.detail:
                    if event.side is Side.HOME:
                        counter_shots_h += 1
                    else:
                        counter_shots_a += 1
            if event.event_type is EventType.PENALTY:
                pens += 1

    m["home_win"] = wins["home"] / n
    m["draw"] = wins["draw"] / n
    m["away_win"] = wins["away"] / n
    m["exp_goals"] = goals / n
    m["goals_home"] = goals_home / n
    m["goals_away"] = goals_away / n
    m["xg_home"] = xg_h / n
    m["xg_away"] = xg_a / n
    m["shots_home"] = shots_h / n
    m["shots_away"] = shots_a / n
    m["shots_home_share"] = shots_h / max(1.0, shots_h + shots_a)
    m["goals_per_90"] = goals / n
    m["goals_first"] = goals_first / n
    m["goals_second"] = goals_second / n
    m["goals_late"] = goals_late / n
    m["goals_home_late"] = goals_home_late / n
    m["goals_away_late"] = goals_away_late / n
    m["shots_home_late"] = shots_h_late / n
    m["shots_away_late"] = shots_a_late / n
    m["counter_shots_home"] = counter_shots_h / n
    m["counter_shots_away"] = counter_shots_a / n
    m["counter_goals_home_late"] = counter_goals_h_late / n
    m["counter_goals_away_late"] = counter_goals_a_late / n
    m["yellows"] = yellows / n
    m["reds"] = reds / n
    m["pens"] = pens / n
    m["scenario_count"] = float(len(tags))
    m["top_scenario_share"] = (max(tags.values()) / n) if tags else 0.0
    return m


def paired_deltas(metrics: Dict[str, Dict[str, float]], treatment: str, control: str) -> Dict[str, float]:
    """treatment - control per metric."""
    out: Dict[str, float] = {}
    for key, value in metrics[treatment].items():
        out[key] = round(value - metrics[control].get(key, 0.0), 5)
    return out
