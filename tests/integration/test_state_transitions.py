"""State transition tests (spec 54-56): goal / red card / substitution / HT."""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from football_simulation.agents.momentum import MomentumAgent
from football_simulation.core.rule_engine import RuleEngine
from football_simulation.core.state_machine import StateTransitionAgent
from football_simulation.knowledge import load_all_knowledge
from football_simulation.models.base import Side
from football_simulation.models.entities import CoachState, PlayerState, TeamState
from football_simulation.models.events import EventType, MatchEvent
from football_simulation.models.world import MatchPhase, Mentality, WorldState
from tests.helpers import prepare_world


def make_world() -> WorldState:
    world = WorldState(match_id="m1", home_team="t1", away_team="t2")
    world.home_team_state = TeamState(team_id="t1", name="Home")
    world.away_team_state = TeamState(team_id="t2", name="Away")
    world.home_coach = CoachState(coach_id="c1", reaction_to_leading="defensive",
                                  reaction_to_trailing="aggressive")
    world.away_coach = CoachState(coach_id="c2", reaction_to_leading="moderate",
                                  reaction_to_trailing="aggressive")
    world.home_players = {f"h{i}": PlayerState(player_id=f"h{i}", starting=True) for i in range(11)}
    world.away_players = {f"a{i}": PlayerState(player_id=f"a{i}", starting=True) for i in range(11)}
    return world


def make_state_machine():
    knowledge = load_all_knowledge()
    rule_engine = RuleEngine(knowledge["rules"])
    return StateTransitionAgent(rule_engine, MomentumAgent())


def goal_event(side: Side, minute: int = 30) -> MatchEvent:
    return MatchEvent(minute=minute, second=0, side=side, event_type=EventType.GOAL,
                      xg=0.3, state_before_version=0, state_after_version=0)


class TestGoalTransition(unittest.TestCase):
    def setUp(self):
        self.sm = make_state_machine()

    def test_home_goal_sets_mentality_and_score(self):
        world = make_world()
        updated = self.sm.apply_event(world, goal_event(Side.HOME))
        self.assertEqual(updated.score_home, 1)
        self.assertEqual(updated.mentality(Side.HOME), Mentality.LEADING)
        self.assertEqual(updated.mentality(Side.AWAY), Mentality.TRAILING)
        self.assertEqual(updated.home_tactical_state.mentality, Mentality.LEADING)
        self.assertEqual(updated.away_tactical_state.mentality, Mentality.TRAILING)

    def test_away_goal_trailing_home_risk_up(self):
        world = make_world()
        before_risk = world.home_tactical_state.risk_level
        updated = self.sm.apply_event(world, goal_event(Side.AWAY))
        self.assertEqual(updated.score_away, 1)
        # trailing side increases risk / attacking intensity
        self.assertGreaterEqual(updated.home_tactical_state.risk_level, before_risk)

    def test_state_version_changes(self):
        world = make_world()
        updated = self.sm.apply_event(world, goal_event(Side.HOME))
        self.assertGreater(updated.state_version, world.state_version)

    def test_momentum_shifted_toward_scorer(self):
        world = make_world()
        updated = self.sm.apply_event(world, goal_event(Side.HOME))
        self.assertGreater(updated.momentum_home, world.momentum_home)


class TestRedCardTransition(unittest.TestCase):
    def setUp(self):
        self.sm = make_state_machine()

    def _red(self, side: Side):
        return MatchEvent(minute=20, second=0, side=side, event_type=EventType.RED_CARD,
                          player_id="h0" if side is Side.HOME else "a0",
                          state_before_version=0, state_after_version=0)

    def test_red_card_reduces_players_and_changes_formation(self):
        world = make_world()
        formation_before = world.home_tactical_state.formation
        updated = self.sm.apply_event(world, self._red(Side.HOME))
        self.assertEqual(updated.red_cards_home, 1)
        self.assertEqual(updated.players_on_pitch(Side.HOME), 10)
        self.assertNotEqual(updated.home_tactical_state.formation, formation_before)

    def test_red_card_reduces_attack_modifier(self):
        world = make_world()
        world = world.evolution_snapshot(red_cards_home=1)
        before = world.home_tactical_state.chance_creation_modifier
        updated = self.sm.apply_event(world, self._red(Side.HOME))
        self.assertLess(updated.home_tactical_state.chance_creation_modifier, before)

    def test_second_yellow_treated_as_red(self):
        world = make_world()
        event = MatchEvent(minute=60, second=0, side=Side.AWAY,
                           event_type=EventType.SECOND_YELLOW, player_id="a1",
                           state_before_version=0, state_after_version=0)
        updated = self.sm.apply_event(world, event)
        self.assertEqual(updated.red_cards_away, 1)
        self.assertEqual(updated.players_on_pitch(Side.AWAY), 10)


class TestSubstitutionTransition(unittest.TestCase):
    def setUp(self):
        self.sm = make_state_machine()

    def _sub(self, side: Side, sub_type: str = "defensive"):
        return MatchEvent(
            minute=65, second=0, side=side, event_type=EventType.SUBSTITUTION,
            detail=f"h9:h11:{sub_type}" if side is Side.HOME else f"a9:a11:{sub_type}",
            player_id="h9" if side is Side.HOME else "a9",
            state_before_version=0, state_after_version=0,
        )

    def test_defensive_sub_reduces_attack_and_risk(self):
        world = make_world()
        world.home_players["h11"] = PlayerState(player_id="h11", starting=False)
        before_attack = world.home_tactical_state.attacking_intensity
        updated = self.sm.apply_event(world, self._sub(Side.HOME, "defensive"))
        self.assertLess(updated.home_tactical_state.attacking_intensity, before_attack)
        self.assertEqual(updated.substitution_state.home.subs_made, 1)

    def test_attacking_sub_raises_attack(self):
        world = make_world()
        world.home_players["h11"] = PlayerState(player_id="h11", starting=False)
        before = world.home_tactical_state.attacking_intensity
        updated = self.sm.apply_event(world, self._sub(Side.HOME, "attacking"))
        self.assertGreater(updated.home_tactical_state.attacking_intensity, before)

    def test_incoming_player_fatigue_reset(self):
        world = make_world()
        world.home_players["h11"] = PlayerState(player_id="h11", starting=False,
                                                current_fatigue=0.3)
        updated = self.sm.apply_event(world, self._sub(Side.HOME, "fatigue"))
        self.assertEqual(updated.home_players["h11"].current_fatigue, 0.0)


class TestHalfTimeTransition(unittest.TestCase):
    def test_halftime_reset(self):
        sm = make_state_machine()
        world = make_world()
        world = world.evolution_snapshot(
            current_minute=45, momentum_home=0.8, momentum_away=0.2,
            fatigue_home=0.3, fatigue_away=0.3,
            score_home=0, score_away=1,
        )
        updated = sm.half_time(world)
        self.assertEqual(updated.phase, MatchPhase.HALF_TIME)
        self.assertAlmostEqual(updated.momentum_home, 0.5)
        self.assertAlmostEqual(updated.momentum_away, 0.5)
        self.assertLess(updated.fatigue_home, 0.3)

    def test_halftime_trailing_coach_pushes(self):
        sm = make_state_machine()
        world = make_world()
        world = world.evolution_snapshot(current_minute=45, score_away=1)
        before = world.home_tactical_state.attacking_intensity
        updated = sm.half_time(world)
        self.assertGreater(updated.home_tactical_state.attacking_intensity, before)


class TestInjuryTransition(unittest.TestCase):
    def test_injury_recorded(self):
        sm = make_state_machine()
        world = make_world()
        event = MatchEvent(minute=40, second=0, side=Side.HOME, event_type=EventType.INJURY,
                           player_id="h2", detail="0.80", state_before_version=0,
                           state_after_version=0)
        updated = sm.apply_event(world, event)
        self.assertEqual(len(updated.injury_state.injuries), 1)
        self.assertEqual(updated.injury_state.injuries[0].player_id, "h2")


if __name__ == "__main__":
    unittest.main()
