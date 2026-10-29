"""V1.1 audit probes: concrete evidence for suspected causal-logic bugs.

Each probe constructs a controlled world, runs the relevant machinery, and
prints observed behavior.  These probes DO NOT assert anything - they exist
to find the truth before any fix is made.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from football_simulation.agents.momentum import MomentumAgent
from football_simulation.core.rule_engine import RuleEngine
from football_simulation.core.state_machine import StateTransitionAgent
from football_simulation.knowledge import load_all_knowledge
from football_simulation.models.base import Side
from football_simulation.models.entities import CoachState, PlayerState, TeamState
from football_simulation.models.events import EventType, MatchEvent
from football_simulation.models.world import WorldState


def make_world(score_home=0, score_away=0, minute=30, red_home=0, fatigue_home=0.0):
    world = WorldState(
        match_id="probe", home_team="h", away_team="a",
        current_minute=minute, score_home=score_home, score_away=score_away,
        red_cards_home=red_home, fatigue_home=fatigue_home,
    )
    world.home_team_state = TeamState(team_id="h", name="Home", reaction_to_leading="defensive")
    world.away_team_state = TeamState(team_id="a", name="Away")
    world.home_coach = CoachState(coach_id="c1", reaction_to_leading="defensive",
                                  reaction_to_trailing="aggressive")
    world.away_coach = CoachState(coach_id="c2")
    world.home_players = {f"h{i}": PlayerState(player_id=f"h{i}", starting=True) for i in range(11)}
    world.away_players = {f"a{i}": PlayerState(player_id=f"a{i}", starting=True) for i in range(11)}
    return world


def probe_rule_compounding():
    print("=== PROBE 1: multiplicative rule compounding after red card ===")
    knowledge = load_all_knowledge()
    sm = StateTransitionAgent(RuleEngine(knowledge["rules"]), MomentumAgent())
    world = make_world(red_home=1)
    world.home_tactical_state.players_on_pitch = 10
    print(f"initial chance_creation_modifier (home): {world.home_tactical_state.chance_creation_modifier}")
    event = MatchEvent(minute=31, second=0, side=Side.AWAY, event_type=EventType.GOAL, xg=0.2,
                       state_before_version=0, state_after_version=0)
    for i in range(4):
        world = sm.apply_event(world, event)
        print(f"  after away-goal event #{i+1}: home chance_creation = {world.home_tactical_state.chance_creation_modifier:.3f}")
    world2 = make_world(score_home=0, score_away=2, minute=78, fatigue_home=0.7)
    sm2 = StateTransitionAgent(RuleEngine(knowledge["rules"]), MomentumAgent())
    print(f"late+fatigue initial chance_creation (home): {world2.home_tactical_state.chance_creation_modifier}")
    ev = MatchEvent(minute=79, second=0, side=Side.HOME, event_type=EventType.SHOT, xg=0.1,
                    state_before_version=0, state_after_version=0)
    for i in range(4):
        world2 = sm2.apply_event(world2, ev)
        print(f"  after event #{i+1} (late game, fatigue 0.7): home chance_creation = {world2.home_tactical_state.chance_creation_modifier:.3f}")


def probe_own_goal_momentum():
    print("\n=== PROBE 2: own goal momentum direction ===")
    sm = StateTransitionAgent(RuleEngine(load_all_knowledge()["rules"]), MomentumAgent())
    world = make_world()
    print(f"momentum before: home {world.momentum_home:.2f} / away {world.momentum_away:.2f}")
    # own-goal event side = BENEFICIARY (home scored an own-goal gift)
    event = MatchEvent(minute=40, second=0, side=Side.HOME, event_type=EventType.OWN_GOAL, xg=0.0,
                       state_before_version=0, state_after_version=0)
    updated = sm.apply_event(world, event)
    print(f"momentum after home BENEFITS from own goal: home {updated.momentum_home:.2f} / away {updated.momentum_away:.2f}")
    print(f"  -> home momentum moved {'UP' if updated.momentum_home > world.momentum_home else 'DOWN'}")


def probe_xg_calibration():
    print("\n=== PROBE 3: xG vs realized goals ===")
    from football_simulation.core.simulation_engine import MatchSimulationEngine, SimulationConfig
    from football_simulation.core.event_engine import EventTriggerAgent
    from football_simulation.agents.substitution import SubstitutionAgent
    from football_simulation.agents.director import DirectorAgent, DirectorConfig
    from football_simulation.data import MockDataProvider
    director = DirectorAgent(MockDataProvider(), DirectorConfig(simulation_runs=500, seed=7))
    context, world, matchup, agreement, dq, lc = director.prepare_world("match-demo-001")
    knowledge = load_all_knowledge()
    rule_engine = RuleEngine(knowledge["rules"])
    sm = StateTransitionAgent(rule_engine, MomentumAgent())
    event_agent = EventTriggerAgent(knowledge["event_defaults"])
    engine = MatchSimulationEngine(world, rule_engine, MomentumAgent(), event_agent,
                                   SubstitutionAgent(), sm, matchup,
                                   SimulationConfig(default_runs=500))
    batch = engine.simulate_n_matches(n=500, base_seed=7)
    goals = sum(m.score_home + m.score_away for m in batch.results) / 500
    xg = sum(m.home_stats.xg + m.away_stats.xg for m in batch.results) / 500
    shots = sum(m.home_stats.shots + m.away_stats.shots for m in batch.results) / 500
    print(f"avg goals/match {goals:.2f} | avg team xG sum/match {xg:.2f} | avg shots/match {shots:.1f}")
    print(f"  -> xG/ goals ratio: {xg / max(goals, 1e-9):.2f} (should be ~1.0 by definition of xG)")


def probe_match_level_caps():
    print("\n=== PROBE 4: match-level event caps ===")
    from football_simulation.core.event_engine import EventTriggerAgent
    knowledge = load_all_knowledge()
    event_agent = EventTriggerAgent(knowledge["event_defaults"])
    rule = event_agent.dependency_rules[EventType.RED_CARD]
    print(f"red card rule: max_per_match={rule.max_per_match}, max_per_team={rule.max_per_team}, max_per_minute={rule.max_per_minute}")
    from football_simulation.core.simulation_engine import _Run
    run = _Run()
    from football_simulation.core.simulation_engine import MatchSimulationEngine
    from football_simulation.agents.substitution import SubstitutionAgent
    from football_simulation.core.state_machine import StateTransitionAgent
    from football_simulation.core.rule_engine import RuleEngine
    from football_simulation.models.world import TacticalMatchupState
    engine = MatchSimulationEngine(
        WorldState(match_id="p"), RuleEngine(knowledge["rules"]), MomentumAgent(),
        event_agent, SubstitutionAgent(), StateTransitionAgent(RuleEngine(knowledge["rules"]), MomentumAgent()),
        TacticalMatchupState(),
    )
    for _ in range(6):
        ev = MatchEvent(minute=20, second=0, side=Side.HOME, event_type=EventType.RED_CARD,
                        state_before_version=0, state_after_version=0)
        allowed = engine._within_caps(ev.event_type, ev.side, run)
        if allowed:
            engine._count_event(ev, run)
        print(f"  red card #{run.match_totals.get(EventType.RED_CARD, 0)} allowed={allowed}")
    print("  -> match-level max_per_match now enforced across minutes")


def probe_psych_streak():
    print("\n=== PROBE 5: PsychologyAgent winning-streak logic ===")
    from football_simulation.agents.psychology import PsychologyAgent
    from football_simulation.models.data import MatchHistory, MatchHistoryEntry
    from football_simulation.models.entities import TeamState
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 8, 20, tzinfo=timezone.utc)
    wins = MatchHistory(team_id="t", entries=[
        MatchHistoryEntry(date=now - timedelta(days=d), opponent="x", goals_for=2, goals_against=0)
        for d in (5, 12, 19, 26, 33)
    ])
    agent = PsychologyAgent()
    state, evidence = agent.build_state(Side.HOME, TeamState(team_id="t", name="T"), wins, True, [], 0.5)
    print(f"5-game winning streak -> confidence {state.confidence:.2f}, evidence: {evidence}")
    losses = MatchHistory(team_id="t", entries=[
        MatchHistoryEntry(date=now - timedelta(days=d), opponent="x", goals_for=0, goals_against=2)
        for d in (5, 12, 19, 26, 33)
    ])
    state2, _ = agent.build_state(Side.HOME, TeamState(team_id="t", name="T"), losses, True, [], 0.5)
    print(f"5-game losing streak -> confidence {state2.confidence:.2f} (should be clearly lower than streak above)")


if __name__ == "__main__":
    probe_rule_compounding()
    probe_own_goal_momentum()
    probe_xg_calibration()
    probe_match_level_caps()
    probe_psych_streak()
