"""Event engine & simulation engine tests (dependency rules, reproducibility, validity)."""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from football_simulation.agents.momentum import MomentumAgent
from football_simulation.core.event_engine import EventTriggerAgent
from football_simulation.core.rule_engine import RuleEngine
from football_simulation.core.rng import SeedableRNG
from football_simulation.core.simulation_engine import MatchSimulationEngine, SimulationConfig
from football_simulation.core.state_machine import StateTransitionAgent
from football_simulation.knowledge import load_all_knowledge
from football_simulation.models.base import Side
from football_simulation.models.events import EventType
from football_simulation.models.world import WorldState
from tests.helpers import prepare_world


_PREPARED = {}


def build_engine(runs: int = 50, seed: int = 42):
    if not _PREPARED:
        (context, world, matchup, agreement, dq, lc), director = prepare_world(runs, seed)
        _PREPARED["world"] = world
        _PREPARED["matchup"] = matchup
    world = _PREPARED["world"]
    matchup = _PREPARED["matchup"]
    knowledge = load_all_knowledge()
    rule_engine = RuleEngine(knowledge["rules"])
    state_machine = StateTransitionAgent(rule_engine, MomentumAgent())
    event_agent = EventTriggerAgent(knowledge["event_defaults"])
    from football_simulation.agents.substitution import SubstitutionAgent
    engine = MatchSimulationEngine(
        world, rule_engine, MomentumAgent(), event_agent,
        SubstitutionAgent(), state_machine, matchup,
        SimulationConfig(default_runs=runs),
    )
    return engine, world


class TestEventDependencyRules(unittest.TestCase):
    def test_defaults_have_dependency_rules(self):
        knowledge = load_all_knowledge()
        rules = knowledge["event_defaults"]["dependency_rules"]
        self.assertGreaterEqual(len(rules), 10)
        types = {r["event_type"] for r in rules}
        for required in ("goal", "red_card", "penalty", "injury", "substitution",
                         "own_goal", "goalkeeper_error"):
            self.assertIn(required, types)

    def test_sample_minute_caps_red_cards(self):
        engine, world = build_engine()
        rng = SeedableRNG(5)
        total = {"red": 0, "pen": 0}
        for _ in range(500):
            events = engine.event_agent.sample_minute(world, rng, {})
            reds = [e for e in events if e.event_type in (EventType.RED_CARD, EventType.SECOND_YELLOW)]
            pens = [e for e in events if e.event_type is EventType.PENALTY]
            self.assertLessEqual(len(reds), 1)
            self.assertLessEqual(len(pens), 1)
            total["red"] += len(reds)
            total["pen"] += len(pens)
        self.assertLess(total["red"], 20)  # sanity: not raining cards

    def test_events_have_valid_minutes(self):
        engine, world = build_engine()
        rng = SeedableRNG(9)
        for _ in range(50):
            for event in engine.event_agent.sample_minute(world, rng, {}):
                self.assertEqual(event.minute, world.current_minute)

    def test_no_own_goal_without_defensive_error(self):
        # own goals only arise from the defensive-error outcome path; verify
        # the outcome distribution contains the path
        engine, world = build_engine()
        outcomes = engine.event_agent.defaults["attack"]["outcomes"]
        self.assertIn("defensive_error_opponent", outcomes)


class TestSimulationEngine(unittest.TestCase):
    def test_single_match_valid(self):
        engine, world = build_engine()
        match = engine.simulate_match(seed=123)
        self.assertEqual(match.match_id, world.match_id)
        self.assertGreaterEqual(match.score_home, 0)
        self.assertGreaterEqual(match.score_away, 0)
        stats = match.home_stats
        self.assertGreaterEqual(stats.shots, stats.shots_on_target)
        self.assertGreaterEqual(stats.shots_on_target, stats.goals)
        self.assertAlmostEqual(stats.possession_avg + match.away_stats.possession_avg, 1.0, places=2)
        self.assertNotEqual(match.scenario_tag, "")

    def test_reproducible(self):
        engine, world = build_engine()
        m1 = engine.simulate_match(seed=77)
        m2 = engine.simulate_match(seed=77)
        self.assertEqual(m1.score_home, m2.score_home)
        self.assertEqual(m1.score_away, m2.score_away)
        self.assertEqual([e.event_type for e in m1.events], [e.event_type for e in m2.events])

    def test_different_seeds_differ(self):
        engine, world = build_engine()
        m1 = engine.simulate_match(seed=1)
        m2 = engine.simulate_match(seed=2)
        self.assertNotEqual((m1.score_home, m1.score_away, len(m1.events)),
                            (m2.score_home, m2.score_away, len(m2.events)))

    def test_batch_conservation(self):
        engine, world = build_engine()
        batch = engine.simulate_n_matches(n=400, base_seed=11)
        counts = batch.result_counts()
        total = sum(counts.values())
        self.assertEqual(total, 400)
        for key, value in counts.items():
            self.assertGreaterEqual(value, 0)

    def test_realistic_averages(self):
        engine, world = build_engine()
        batch = engine.simulate_n_matches(n=600, base_seed=21)
        total_goals = [m.score_home + m.score_away for m in batch.results]
        avg = sum(total_goals) / len(total_goals)
        self.assertGreater(avg, 1.8)
        self.assertLess(avg, 4.2)
        # shots average sane
        avg_shots = sum(m.home_stats.shots + m.away_stats.shots for m in batch.results) / 600
        self.assertGreater(avg_shots, 12)
        self.assertLess(avg_shots, 36)

    def test_red_card_rate_sane(self):
        engine, world = build_engine()
        batch = engine.simulate_n_matches(n=600, base_seed=31)
        reds = sum(m.home_stats.red_cards + m.away_stats.red_cards for m in batch.results)
        rate = reds / 600
        self.assertGreater(rate, 0.02)
        self.assertLess(rate, 0.5)

    def test_long_tail_present(self):
        engine, world = build_engine()
        batch = engine.simulate_n_matches(n=2000, base_seed=41)
        tags = set(m.scenario_tag for m in batch.results)
        self.assertGreater(len(tags), 10)

    def test_convergence_analysis(self):
        engine, world = build_engine()
        report = engine.convergence_analysis(runs=[300, 600], base_seed=51)
        self.assertEqual(len(report.samples), 2)
        self.assertGreaterEqual(report.max_delta, 0.0)
        self.assertIn(report.converged, (True, False))


class TestExtremeCases(unittest.TestCase):
    """Spec section 57: extreme situations must not crash the simulation."""

    def _engine_with(self, mutate):
        engine, world = build_engine()
        world = mutate(world)
        engine.template = world
        return engine

    def test_early_home_goal(self):
        engine, world = build_engine()
        world = world.evolution_snapshot(score_home=1, current_minute=5)
        engine.template = world
        match = engine.simulate_match(seed=3)
        self.assertGreaterEqual(match.score_home, 1)

    def test_early_away_goal(self):
        engine, world = build_engine()
        world = world.evolution_snapshot(score_away=1, current_minute=3)
        engine.template = world
        match = engine.simulate_match(seed=4)
        self.assertGreaterEqual(match.score_away, 1)

    def test_red_card_from_kickoff(self):
        engine, world = build_engine()
        world = world.evolution_snapshot(red_cards_home=1)
        world.home_tactical_state = world.home_tactical_state.model_copy(
            update={"players_on_pitch": 10, "formation": "4-4-1"})
        engine.template = world
        match = engine.simulate_match(seed=5)
        self.assertGreaterEqual(match.score_home, 0)

    def test_heavy_rain(self):
        engine, world = build_engine()
        world = world.evolution_snapshot(
            weather_state=world.weather_state.model_copy(
                update={"rain": 0.9, "impact": "high", "known": True}))
        engine.template = world
        match = engine.simulate_match(seed=6)
        self.assertGreaterEqual(match.score_home, 0)

    def test_very_high_fatigue(self):
        engine, world = build_engine()
        world = world.evolution_snapshot(fatigue_home=0.9, fatigue_away=0.9)
        engine.template = world
        match = engine.simulate_match(seed=7)
        self.assertGreaterEqual(match.score_home, 0)

    def test_unexpected_lineup(self):
        engine, world = build_engine()
        world.home_lineup = world.home_lineup.model_copy(update={"confirmed": False})
        engine.template = world
        match = engine.simulate_match(seed=8)
        self.assertGreaterEqual(match.score_home, 0)

    def test_goalless_draw_possible(self):
        engine, world = build_engine()
        batch = engine.simulate_n_matches(n=300, base_seed=9)
        scoreless = sum(1 for m in batch.results if m.score_home == 0 and m.score_away == 0)
        self.assertGreater(scoreless, 0)


if __name__ == "__main__":
    unittest.main()
