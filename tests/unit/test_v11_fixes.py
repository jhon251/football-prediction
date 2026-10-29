"""Unit tests for the V1.1 causal-chain fixes found by the audit.

Each test pins the FIXED behavior so regressions are caught:
- state-describing rules must not compound on every event (idempotency),
- own goals must swing momentum toward the beneficiary,
- match-level event caps must be enforced across minutes,
- winning streaks must actually feed confidence.
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from football_simulation.agents.momentum import MomentumAgent
from football_simulation.agents.psychology import PsychologyAgent
from football_simulation.core.rule_engine import RuleEngine
from football_simulation.core.state_machine import StateTransitionAgent
from football_simulation.knowledge import load_all_knowledge
from football_simulation.models.base import Side
from football_simulation.models.data import MatchHistory, MatchHistoryEntry
from football_simulation.models.entities import CoachState, PlayerState, TeamState
from football_simulation.models.events import EventType, MatchEvent
from football_simulation.models.world import WorldState
from datetime import datetime, timedelta, timezone


def make_world(**kwargs) -> WorldState:
    world = WorldState(match_id="m", home_team="h", away_team="a", **kwargs)
    world.home_team_state = TeamState(team_id="h", name="Home")
    world.away_team_state = TeamState(team_id="a", name="Away")
    world.home_coach = CoachState(coach_id="c1", reaction_to_leading="defensive",
                                  reaction_to_trailing="aggressive")
    world.away_coach = CoachState(coach_id="c2")
    world.home_players = {f"h{i}": PlayerState(player_id=f"h{i}", starting=True) for i in range(11)}
    world.away_players = {f"a{i}": PlayerState(player_id=f"a{i}", starting=True) for i in range(11)}
    return world


def make_sm():
    knowledge = load_all_knowledge()
    return StateTransitionAgent(RuleEngine(knowledge["rules"]), MomentumAgent())


class TestRuleIdempotency(unittest.TestCase):
    def test_red_card_rule_fires_once(self):
        sm = make_sm()
        world = make_world(red_cards_home=1)
        world.home_tactical_state.players_on_pitch = 10
        goal = MatchEvent(minute=31, second=0, side=Side.AWAY, event_type=EventType.GOAL,
                          xg=0.2, state_before_version=0, state_after_version=0)
        once = sm.apply_event(world, goal)
        twice = sm.apply_event(once, goal)
        thrice = sm.apply_event(twice, goal)
        self.assertAlmostEqual(once.home_tactical_state.chance_creation_modifier,
                               twice.home_tactical_state.chance_creation_modifier)
        self.assertAlmostEqual(twice.home_tactical_state.chance_creation_modifier,
                               thrice.home_tactical_state.chance_creation_modifier)
        self.assertLess(once.home_tactical_state.chance_creation_modifier, 1.0)

    def test_late_fatigue_rule_fires_once(self):
        sm = make_sm()
        world = make_world(score_away=1, current_minute=78, fatigue_home=0.7)
        shot = MatchEvent(minute=79, second=0, side=Side.HOME, event_type=EventType.SHOT,
                          xg=0.1, state_before_version=0, state_after_version=0)
        once = sm.apply_event(world, shot)
        twice = sm.apply_event(once, shot)
        self.assertAlmostEqual(once.home_tactical_state.chance_creation_modifier,
                               twice.home_tactical_state.chance_creation_modifier)

    def test_rule_refires_after_condition_toggles(self):
        sm = make_sm()
        world = make_world(score_home=0, score_away=1, current_minute=40)
        world = sm._sync_mentalities(world)
        # trailing -> push applies once
        w1, mods1 = sm.rule_engine.apply_state(world)
        names1 = {m.rule_name for m in mods1}
        self.assertIn("trailing_team_push", names1)
        # equalize -> condition false
        w2 = sm.apply_event(w1, MatchEvent(minute=41, second=0, side=Side.HOME,
                                           event_type=EventType.GOAL, xg=0.2,
                                           state_before_version=0, state_after_version=0))
        self.assertEqual(w2.rule_conditions.get("R_MENTALITY_TRAIL_PUSH"), False)
        # fall behind again -> rule fires AGAIN (fresh edge)
        w3, mods3 = sm.rule_engine.apply_state(w2)
        self.assertNotIn("trailing_team_push", {m.rule_name for m in mods3},
                         "level score must not fire the trailing rule")
        w4 = sm.apply_event(w3, MatchEvent(minute=42, second=0, side=Side.AWAY,
                                           event_type=EventType.GOAL, xg=0.2,
                                           state_before_version=0, state_after_version=0))
        self.assertEqual(w4.rule_conditions.get("R_MENTALITY_TRAIL_PUSH"), True)


class TestOwnGoalMomentum(unittest.TestCase):
    def test_beneficiary_gains_momentum(self):
        sm = make_sm()
        world = make_world()
        og = MatchEvent(minute=40, second=0, side=Side.HOME, event_type=EventType.OWN_GOAL,
                        xg=0.0, state_before_version=0, state_after_version=0)
        updated = sm.apply_event(world, og)
        self.assertGreater(updated.momentum_home, world.momentum_home)
        self.assertLess(updated.momentum_away, world.momentum_away)


class TestMatchLevelCaps(unittest.TestCase):
    def test_red_card_caps_enforced_across_minutes(self):
        from football_simulation.core.simulation_engine import _Run, MatchSimulationEngine
        from football_simulation.core.event_engine import EventTriggerAgent
        from football_simulation.agents.substitution import SubstitutionAgent
        from football_simulation.models.world import TacticalMatchupState
        knowledge = load_all_knowledge()
        engine = MatchSimulationEngine(
            make_world(), RuleEngine(knowledge["rules"]), MomentumAgent(),
            EventTriggerAgent(knowledge["event_defaults"]), SubstitutionAgent(),
            StateTransitionAgent(RuleEngine(knowledge["rules"]), MomentumAgent()),
            TacticalMatchupState(),
        )
        run = _Run()
        allowed = 0
        for _ in range(10):
            event = MatchEvent(minute=20, second=0, side=Side.HOME,
                               event_type=EventType.RED_CARD,
                               state_before_version=0, state_after_version=0)
            if engine._within_caps(event.event_type, event.side, run):
                engine._count_event(event, run)
                allowed += 1
        self.assertLessEqual(allowed, 2, "max_per_team=2 for red cards")

    def test_goal_caps_enforced(self):
        from football_simulation.core.simulation_engine import _Run, MatchSimulationEngine
        from football_simulation.core.event_engine import EventTriggerAgent
        from football_simulation.agents.substitution import SubstitutionAgent
        from football_simulation.models.world import TacticalMatchupState
        knowledge = load_all_knowledge()
        engine = MatchSimulationEngine(
            make_world(), RuleEngine(knowledge["rules"]), MomentumAgent(),
            EventTriggerAgent(knowledge["event_defaults"]), SubstitutionAgent(),
            StateTransitionAgent(RuleEngine(knowledge["rules"]), MomentumAgent()),
            TacticalMatchupState(),
        )
        run = _Run()
        allowed = 0
        for _ in range(15):
            event = MatchEvent(minute=20, second=0, side=Side.HOME, event_type=EventType.GOAL,
                               xg=0.1, state_before_version=0, state_after_version=0)
            if engine._within_caps(event.event_type, event.side, run):
                engine._count_event(event, run)
                allowed += 1
        self.assertLessEqual(allowed, 9, "max_per_match=9 for goals")


class TestPsychologyStreak(unittest.TestCase):
    def test_winning_streak_beats_losing_streak(self):
        now = datetime(2026, 8, 20, tzinfo=timezone.utc)
        wins = MatchHistory(team_id="t", entries=[
            MatchHistoryEntry(date=now - timedelta(days=d), opponent="x",
                              goals_for=2, goals_against=0)
            for d in (5, 12, 19, 26, 33)
        ])
        losses = MatchHistory(team_id="t", entries=[
            MatchHistoryEntry(date=now - timedelta(days=d), opponent="x",
                              goals_for=0, goals_against=2)
            for d in (5, 12, 19, 26, 33)
        ])
        agent = PsychologyAgent()
        win_state, _ = agent.build_state(Side.HOME, TeamState(team_id="t", name="T"),
                                         wins, True, [], 0.5)
        loss_state, _ = agent.build_state(Side.HOME, TeamState(team_id="t", name="T"),
                                          losses, True, [], 0.5)
        self.assertGreater(win_state.confidence, loss_state.confidence + 0.1)
        self.assertLess(win_state.pressure, loss_state.pressure)


if __name__ == "__main__":
    unittest.main()
