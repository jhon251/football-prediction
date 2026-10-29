"""Unit tests: domain models & world state."""

import unittest

from football_simulation.models.base import (
    AgentOpinion,
    AgentResult,
    ConfidenceLevel,
    KnowledgeStatus,
    Side,
)
from football_simulation.models.entities import PlayerProfile, PlayerState, Position
from football_simulation.models.world import MatchPhase, Mentality, WorldState


class TestWorldState(unittest.TestCase):
    def test_evolution_bumps_version(self):
        world = WorldState(match_id="m1")
        self.assertEqual(world.state_version, 0)
        world2 = world.evolution_snapshot(score_home=1)
        self.assertEqual(world2.state_version, 1)
        self.assertEqual(world.state_version, 0)
        self.assertEqual(world.score_home, 0)
        self.assertEqual(world2.score_home, 1)

    def test_mentality(self):
        world = WorldState(match_id="m1", score_home=1, score_away=0)
        self.assertEqual(world.mentality(Side.HOME), Mentality.LEADING)
        self.assertEqual(world.mentality(Side.AWAY), Mentality.TRAILING)
        world2 = WorldState(match_id="m2", score_home=0, score_away=2)
        self.assertEqual(world2.mentality(Side.HOME), Mentality.TRAILING)
        self.assertEqual(world2.mentality(Side.AWAY), Mentality.LEADING)
        world3 = WorldState(match_id="m3", score_home=1, score_away=1)
        self.assertEqual(world3.mentality(Side.HOME), Mentality.LEVEL)

    def test_players_on_pitch(self):
        world = WorldState(match_id="m1")
        self.assertEqual(world.players_on_pitch(Side.HOME), 11)
        world = world.evolution_snapshot(red_cards_home=1)
        self.assertEqual(world.players_on_pitch(Side.HOME), 10)

    def test_possession_and_momentum_bounds(self):
        world = WorldState(match_id="m1")
        for field in ("possession_home", "momentum_home", "fatigue_home"):
            value = getattr(world, field)
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

    def test_minute_float(self):
        world = WorldState(match_id="m1", current_minute=23, current_second=30)
        self.assertAlmostEqual(world.minute_float(), 23.5)

    def test_default_phase(self):
        world = WorldState(match_id="m1")
        self.assertEqual(world.phase, MatchPhase.PRE_MATCH)


class TestAgentResult(unittest.TestCase):
    def test_result_envelope(self):
        result = AgentResult(
            agent_name="TestAgent", match_id="m1", input_version=0,
            output={"a": 1}, confidence=0.5, evidence=["e1"], reasoning="r",
            warnings=[], impact="medium",
        )
        self.assertEqual(result.agent_name, "TestAgent")
        self.assertEqual(result.confidence, 0.5)

    def test_opinion(self):
        opinion = AgentOpinion(
            agent_name="X", subject="home_attack", value=0.2, confidence=0.9,
            evidence=["e"], reasoning="r",
        )
        self.assertEqual(opinion.subject, "home_attack")


class TestPlayerState(unittest.TestCase):
    def test_quality_affected_by_fatigue(self):
        player = PlayerState(player_id="p1", position=Position.ST)
        fresh = player.overall_quality()
        tired = player.model_copy(update={"current_fatigue": 0.8}).overall_quality()
        self.assertLess(tired, fresh)

    def test_profile_defaults_valid(self):
        profile = PlayerProfile(player_id="p1")
        state = PlayerState(player_id="p1")
        self.assertTrue(0.0 <= state.injury_risk <= 1.0)


class TestKnowledgeStatus(unittest.TestCase):
    def test_enum_values(self):
        self.assertEqual(KnowledgeStatus.UNVERIFIED.value, "unverified")
        self.assertEqual(ConfidenceLevel.HIGH.value, "high")


if __name__ == "__main__":
    unittest.main()
