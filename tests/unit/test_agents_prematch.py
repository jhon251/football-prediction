"""Unit tests: pre-match agents (Team/Coach/Player/Lineup/Fitness/Psych/Env/Referee/Tactical/Opening)."""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from football_simulation.agents.base import AgentContext
from football_simulation.agents.coach import CoachAgent
from football_simulation.agents.environment import EnvironmentAgent
from football_simulation.agents.fitness import FitnessAgent
from football_simulation.agents.lineup import LineupAgent
from football_simulation.agents.opening import OpeningAgent
from football_simulation.agents.player import PlayerAgent
from football_simulation.agents.psychology import PsychologyAgent
from football_simulation.agents.referee import RefereeAgent
from football_simulation.agents.tactical import TacticalMatchupAgent
from football_simulation.agents.team import TeamAgent
from football_simulation.data import MockDataProvider
from football_simulation.knowledge import load_all_knowledge
from football_simulation.models.base import Side
from football_simulation.models.data import WeatherData
from football_simulation.models.entities import (
    CoachProfile,
    FixtureLineup,
    MatchRequest,
    PlayerProfile,
    PlayerState,
    Position,
    RefereeProfile,
    TeamProfile,
)
from tests.helpers import DEMO_MATCH, make_director, make_provider, prepare_world


class TestTeamAgent(unittest.TestCase):
    def test_state_built_with_style(self):
        profile = TeamProfile(team_id="t1", name="Team A", pressing_style="high_press",
                              attack_strength=0.8, elo_rating=1700)
        agent = TeamAgent()
        state, evidence = agent.build_state(profile, None, is_home=True)
        self.assertEqual(state.pressing_style, "high_press")
        self.assertGreater(state.attack_strength, 0.7)
        self.assertGreaterEqual(len(evidence), 2)

    def test_home_vs_away_adjustment(self):
        profile = TeamProfile(team_id="t1", name="A")
        agent = TeamAgent()
        home_state, _ = agent.build_state(profile, None, True)
        away_state, _ = agent.build_state(profile, None, False)
        self.assertGreater(home_state.attack_strength, away_state.attack_strength)


class TestCoachAgent(unittest.TestCase):
    def test_different_coaches_different_gameplans(self):
        own = TeamProfile(team_id="t1", name="A", attack_strength=0.7, defense_strength=0.6).model_copy()
        opp = TeamProfile(team_id="t2", name="B", attack_strength=0.7, defense_strength=0.6).model_copy()
        from football_simulation.agents.team import TeamAgent
        team_agent = TeamAgent()
        own_state, _ = team_agent.build_state(own, None, True)
        opp_state, _ = team_agent.build_state(opp, None, False)

        coach = CoachAgent()
        cautious, _ = coach.build_state(
            CoachProfile(coach_id="c1", name="Cautious", risk_tolerance=0.3,
                         aggressiveness=0.3), own_state, opp_state, True)
        risky, _ = coach.build_state(
            CoachProfile(coach_id="c2", name="Risky", risk_tolerance=0.8,
                         aggressiveness=0.8), own_state, opp_state, True)
        self.assertGreater(risky.gameplan_risk_level, cautious.gameplan_risk_level)
        self.assertGreater(risky.gameplan_pressing_intensity, cautious.gameplan_pressing_intensity)


class TestLineupAgent(unittest.TestCase):
    def _squad(self, size: int = 12):
        players = {}
        positions = [Position.GK, Position.GK, Position.CB, Position.CB, Position.LB,
                     Position.RB, Position.DM, Position.CM, Position.AM, Position.LW,
                     Position.RW, Position.ST, Position.CB, Position.CM, Position.ST,
                     Position.DM, Position.AM, Position.LW]
        for i in range(size):
            position = positions[i % len(positions)]
            pid = f"p{i}"
            quality = 0.9 if i == 0 else max(0.35, 0.75 - 0.05 * i)
            players[pid] = PlayerState(
                player_id=pid, position=position, age=24,
                technical={"finishing": quality, "passing": quality},
                physical={"pace": quality, "stamina": quality, "strength": quality},
                mental={"composure": quality, "decisions": quality, "concentration": quality},
                form=quality,
            )
        return players

    def test_expected_xi_when_unconfirmed(self):
        from football_simulation.models.entities import TeamState, CoachState
        agent = LineupAgent()
        lineup, impact, evidence = agent.build_lineup(
            "t1", TeamState(team_id="t1"), CoachState(coach_id="c1"),
            self._squad(), None, [],
        )
        self.assertFalse(lineup.confirmed)
        self.assertEqual(len(lineup.starters), 11)
        self.assertTrue(any("NOT confirmed" in e for e in evidence))

    def test_key_absence_detected(self):
        from football_simulation.models.entities import TeamState, CoachState, InjuryRecord
        squad = self._squad()
        # injure the best player
        injuries = [InjuryRecord(player_id="p0", severity=0.8)]
        agent = LineupAgent()
        lineup, impact, evidence = agent.build_lineup(
            "t1", TeamState(team_id="t1"), CoachState(coach_id="c1"),
            squad, None, injuries,
        )
        self.assertIn("p0", lineup.missing_players)
        self.assertGreaterEqual(len(lineup.key_absences), 1)
        self.assertLess(impact["starting_quality"], 0.95)

    def test_backup_gk_detected(self):
        from football_simulation.models.entities import TeamState, CoachState
        squad = self._squad()
        starters = [pid for pid, p in squad.items() if p.position is not Position.GK][:10]
        starters.insert(0, "p1")  # second GK starts
        raw = FixtureLineup(team_id="t1", starters=starters, bench=["p0"], confirmed=True)
        agent = LineupAgent()
        lineup, _, _ = agent.build_lineup(
            "t1", TeamState(team_id="t1"), CoachState(coach_id="c1"),
            squad, raw, [],
        )
        self.assertTrue(lineup.backup_goalkeeper)

    def test_rotation_detection(self):
        from football_simulation.models.entities import TeamState, CoachState
        squad = self._squad(size=16)
        # pick weak starters: a clear rotation away from the best XI
        weak = sorted(squad, key=lambda pid: (
            squad[pid].technical.finishing + squad[pid].form
        ))[-11:]
        raw = FixtureLineup(team_id="t1", starters=weak, bench=[], confirmed=True)
        agent = LineupAgent()
        lineup, _, _ = agent.build_lineup(
            "t1", TeamState(team_id="t1"), CoachState(coach_id="c1", rotation_tendency=0.8),
            squad, raw, [],
        )
        self.assertGreater(lineup.rotation_level, 0.3)


class TestFitnessAgent(unittest.TestCase):
    def test_fatigue_curve_monotonic(self):
        from football_simulation.agents.fitness import FitnessAgent
        agent = FitnessAgent()
        players = {
            f"p{i}": PlayerState(player_id=f"p{i}", fatigue_sensitivity=0.5)
            for i in range(11)
        }
        state, _ = agent.build_state(Side.HOME, "t1", players, None, None)
        curve = state.expected_fatigue_curve
        self.assertEqual(len(curve), 7)
        self.assertTrue(all(curve[i] <= curve[i + 1] for i in range(len(curve) - 1)))

    def test_individual_sensitivity(self):
        from football_simulation.agents.fitness import FitnessAgent
        agent = FitnessAgent()
        players = {
            "a": PlayerState(player_id="a", fatigue_sensitivity=0.9),
            "b": PlayerState(player_id="b", fatigue_sensitivity=0.1),
        }
        # travel burden flows through individual sensitivity
        state, _ = agent.build_state(Side.HOME, "t1", players, None, None,
                                     travel_burden=0.5)
        self.assertGreater(state.per_player_fatigue["a"], state.per_player_fatigue["b"])


class TestPsychologyAgent(unittest.TestCase):
    def test_bounds_and_side(self):
        from football_simulation.models.entities import TeamState
        agent = PsychologyAgent()
        state, _ = agent.build_state(
            Side.HOME, TeamState(team_id="t1", name="A"), None, True,
            ["derby"], importance=0.8, coach_pressure=0.6,
        )
        for field in ("confidence", "pressure", "motivation", "composure",
                      "risk_appetite", "decision_quality"):
            value = getattr(state, field)
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)
        self.assertIn("derby", state.context_tags)


class TestEnvironmentAgent(unittest.TestCase):
    def test_impact_levels(self):
        agent = EnvironmentAgent()
        benign, _ = agent.build_state(
            WeatherData(match_id="m", temperature_c=18, rain=0.0, wind=0.1, known=True), 0.04)
        storm, _ = agent.build_state(
            WeatherData(match_id="m", rain=0.9, wind=0.85, pitch_condition=0.4, known=True), 0.04)
        self.assertEqual(benign.impact, "low")
        self.assertEqual(storm.impact, "high")

    def test_unknown_weather(self):
        agent = EnvironmentAgent()
        state, _ = agent.build_state(WeatherData(match_id="m", known=False), 0.04)
        self.assertFalse(state.known)
        self.assertEqual(state.impact, "low")


class TestRefereeAgent(unittest.TestCase):
    def test_state_from_profile(self):
        agent = RefereeAgent()
        state, evidence = agent.build_state(
            RefereeProfile(referee_id="r1", name="R", yellow_card_tendency=0.7,
                           matches_officiated=120))
        self.assertTrue(state.known)
        self.assertAlmostEqual(state.yellow_card_tendency, 0.7)


class TestTacticalMatchupAgent(unittest.TestCase):
    def test_high_press_vs_direct_fires_pattern(self):
        knowledge = load_all_knowledge()
        home = TeamProfile(team_id="h", pressing_style="high_press", build_up_style="positional")
        away = TeamProfile(team_id="a", build_up_style="long_ball")
        from football_simulation.agents.team import TeamAgent
        team_agent = TeamAgent()
        home_state, _ = team_agent.build_state(home, None, True)
        away_state, _ = team_agent.build_state(away, None, False)
        agent = TacticalMatchupAgent()
        state, evidence = agent.analyze(home_state, away_state, knowledge["tactical_patterns"])
        self.assertIn("high_press_vs_weak_buildup", state.pattern_names)
        self.assertGreater(state.pressing_success_home, 0.55)

    def test_advantage_antisymmetric(self):
        knowledge = load_all_knowledge()
        from football_simulation.agents.team import TeamAgent
        team_agent = TeamAgent()
        h, _ = team_agent.build_state(TeamProfile(team_id="h"), None, True)
        a, _ = team_agent.build_state(TeamProfile(team_id="a"), None, False)
        state, _ = TacticalMatchupAgent().analyze(h, a, knowledge["tactical_patterns"])
        self.assertAlmostEqual(state.tactical_advantage_home, -state.tactical_advantage_away)


class TestOpeningAgent(unittest.TestCase):
    def test_opening_analysis(self):
        (context, world, matchup, agreement, dq, lc), director = prepare_world()
        agent = OpeningAgent()
        state, _ = agent.analyze(world, matchup)
        self.assertIn(state.aggressive_side, (Side.HOME, Side.AWAY, None))
        self.assertGreaterEqual(state.early_goal_risk_home, 0.0)
        self.assertLessEqual(state.early_goal_risk_home, 1.0)


class TestEndToEndPreMatchAgents(unittest.TestCase):
    def test_full_chain(self):
        (context, world, matchup, agreement, dq, lc), director = prepare_world()
        self.assertIsNotNone(world.home_team_state)
        self.assertIsNotNone(world.away_team_state)
        self.assertIsNotNone(world.home_coach)
        self.assertIsNotNone(world.away_coach)
        self.assertEqual(len(world.home_players), 22)
        self.assertEqual(len(world.home_lineup.starters), 11)
        self.assertGreater(matchup.chance_creation_home, 0.0)
        self.assertGreaterEqual(dq.completeness, 0.0)


if __name__ == "__main__":
    unittest.main()
