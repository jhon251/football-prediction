"""Director pipeline, scenarios, risk, confidence, counterfactual, learning tests."""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from football_simulation.agents.fusion import OpinionFusionLayer
from football_simulation.agents.risk import ConfidenceAgent, RiskAgent, UpsetRiskAgent
from football_simulation.core.scenario_engine import MatchScriptAgent, ScenarioRankingAgent
from football_simulation.evaluation.learning import (
    LearningAgent,
    LearningStore,
    PostMatchEvaluationAgent,
)
from football_simulation.models.base import AgentOpinion, RiskLevel
from football_simulation.models.report import ResultProbability
from tests.helpers import PAST_MATCH, make_director, make_provider


class TestDirectorPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.director = make_director(runs=300, seed=42)
        cls.report = cls.director.analyze("match-demo-001")

    def test_all_report_sections_present(self):
        report = self.report
        self.assertIsNotNone(report.match)
        self.assertIsNotNone(report.result_probability)
        self.assertGreater(len(report.score_probability.matrix), 5)
        self.assertGreater(len(report.goals_probability.over), 5)
        self.assertGreater(len(report.half_time_full_time.combinations), 3)
        self.assertGreaterEqual(len(report.scenarios), 5)
        self.assertIsNotNone(report.upset_risk)
        self.assertGreater(len(report.risk.components), 8)
        self.assertIsNotNone(report.confidence)
        self.assertGreater(len(report.failure_conditions), 0)
        self.assertGreater(len(report.explanation), 200)
        self.assertGreater(len(report.trace), 8)
        self.assertEqual(report.simulation_runs, 300)

    def test_probabilities_conserved(self):
        r = self.report.result_probability
        self.assertAlmostEqual(r.home_win + r.draw + r.away_win, 1.0, places=3)
        self.assertAlmostEqual(self.report.btts.yes + self.report.btts.no, 1.0, places=3)

    def test_reproducible_pipeline(self):
        report2 = make_director(runs=300, seed=42).analyze("match-demo-001")
        self.assertEqual(self.report.result_probability.home_win,
                         report2.result_probability.home_win)

    def test_trace_is_explainable(self):
        kinds = {step["kind"] for step in self.report.trace}
        self.assertIn("agent_decision", kinds)
        self.assertIn("simulation", kinds)
        self.assertIn("probability", kinds)
        self.assertIn("fusion", kinds)


class TestScenarioEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        director = make_director(runs=2000, seed=42)
        cls.director = director
        cls.report = director.analyze("match-demo-001")

    def test_scenarios_have_required_fields(self):
        for scenario in self.report.scenarios:
            self.assertTrue(scenario.scenario_id)
            self.assertTrue(scenario.name)
            self.assertGreaterEqual(scenario.probability, 0.0)
            self.assertLessEqual(scenario.probability, 1.0)
            self.assertTrue(scenario.description)
            self.assertIn("result", scenario.final_result)
            self.assertGreaterEqual(scenario.confidence, 0.0)

    def test_scenario_mass_conserved(self):
        total = sum(s.probability for s in self.report.scenarios)
        self.assertAlmostEqual(total, 1.0, places=3)

    def test_long_tail_present(self):
        tail = self.report.scenario_ranking["long_tail_probability"]
        self.assertGreaterEqual(tail, 0.0)
        self.assertLessEqual(tail, 1.0)

    def test_candidate_scenario_count(self):
        # V1 generates many candidate scenarios (>= 12 named + long tail)
        self.assertGreaterEqual(len(self.report.scenarios), 12)

    def test_scenario_ranking_sorted(self):
        probs = [s.probability for s in self.report.scenarios
                 if s.archetype != "long_tail"]
        self.assertEqual(probs, sorted(probs, reverse=True))


class TestRiskAgents(unittest.TestCase):
    def test_upset_relative_to_probability(self):
        agent = UpsetRiskAgent()
        tight = agent.compute(ResultProbability(home_win=0.36, draw=0.30, away_win=0.34),
                              None, [])
        lopsided = agent.compute(ResultProbability(home_win=0.72, draw=0.18, away_win=0.10),
                                 None, [])
        self.assertEqual(tight.level, RiskLevel.LOW)
        self.assertGreaterEqual(lopsided.severity, tight.severity)
        self.assertEqual(lopsided.direction, "away_win")

    def test_upset_high_severity_low_prob(self):
        agent = UpsetRiskAgent()
        report = agent.compute(ResultProbability(home_win=0.85, draw=0.10, away_win=0.05),
                               None, [])
        self.assertEqual(report.probability, 0.05)
        self.assertIn(report.level, (RiskLevel.HIGH, RiskLevel.VERY_HIGH))

    def test_risk_components_complete(self):
        director = make_director(runs=100, seed=42)
        context, world, matchup, agreement, dq, lc = director.prepare_world("match-demo-001")
        report = RiskAgent().compute(world, 0.3, 0.3, dq)
        names = {c.name for c in report.components}
        for expected in ("lineup", "injury", "fatigue", "tactical", "psychological",
                         "referee", "weather", "model_uncertainty",
                         "scenario_divergence", "data_quality"):
            self.assertIn(expected, names)
        self.assertIn(report.overall_risk, RiskLevel)

    def test_confidence_reflects_dispersion(self):
        agent = ConfidenceAgent()
        dispersed = agent.compute([0.21, 0.18, 0.16, 0.13], None, 0.8, 1.0,
                                  ResultProbability(home_win=0.62, draw=0.2, away_win=0.18))
        concentrated = agent.compute([0.6, 0.15, 0.1, 0.05], None, 0.8, 1.0,
                                     ResultProbability(home_win=0.62, draw=0.2, away_win=0.18))
        self.assertGreater(concentrated.scenario_concentration,
                           dispersed.scenario_concentration)
        # high probability does NOT guarantee high confidence
        self.assertGreaterEqual(concentrated.score, dispersed.score)


class TestFusion(unittest.TestCase):
    def test_weighted_by_confidence(self):
        fusion = OpinionFusionLayer()
        opinions = [
            AgentOpinion(agent_name="A", subject="s", value=1.0, confidence=0.9,
                         evidence=["e1", "e2"], impact="high"),
            AgentOpinion(agent_name="B", subject="s", value=-1.0, confidence=0.3,
                         evidence=[], impact="low"),
        ]
        fused = fusion.fuse(opinions, "s")
        self.assertGreater(fused["value"], 0.0)  # confident opinion dominates
        self.assertLess(fused["agreement"], 0.8)

    def test_agreement_one_when_identical(self):
        fusion = OpinionFusionLayer()
        opinions = [
            AgentOpinion(agent_name="A", subject="s", value=0.5, confidence=0.8),
            AgentOpinion(agent_name="B", subject="s", value=0.5, confidence=0.6),
        ]
        fused = fusion.fuse(opinions, "s")
        self.assertAlmostEqual(fused["value"], 0.5)
        self.assertAlmostEqual(fused["agreement"], 1.0)


class TestCounterfactual(unittest.TestCase):
    def test_counterfactual_reports(self):
        from football_simulation.agents.counterfactual import CounterfactualAgent
        from football_simulation.agents.momentum import MomentumAgent
        from football_simulation.core.event_engine import EventTriggerAgent
        from football_simulation.core.rule_engine import RuleEngine
        from football_simulation.core.simulation_engine import MatchSimulationEngine, SimulationConfig
        from football_simulation.core.state_machine import StateTransitionAgent
        from football_simulation.agents.substitution import SubstitutionAgent
        from football_simulation.knowledge import load_all_knowledge
        from tests.integration.test_simulation import build_engine

        engine, world = build_engine()
        single = engine.simulate_match(seed=42)
        goals = [e for e in single.events if e.event_type.value == "goal"]
        if not goals:
            self.skipTest("no goal in sampled match")
        agent = CounterfactualAgent()
        agent.set_engine(engine)
        baseline = {"home_win": 0.5, "draw": 0.3, "away_win": 0.2}
        reports = agent.run_counterfactual("m1", baseline, goals[:1], runs=60, base_seed=5)
        self.assertEqual(len(reports), 1)
        self.assertEqual(set(reports[0].probability_delta), set(baseline))
        self.assertTrue(reports[0].description)


def _workspace_tmp(name: str) -> Path:
    """Temp dir inside the workspace (mkdtemp-created dirs can be denied by
    the file sandbox on some hosts)."""
    import shutil
    import uuid
    path = Path(__file__).resolve().parents[2] / "tests" / f".tmp_{name}_{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


class TestLearningAndEvaluation(unittest.TestCase):
    def test_post_match_evaluation(self):
        provider = make_provider()
        actual = provider.get_match_result(PAST_MATCH)
        self.assertTrue(actual.available)
        director = make_director(runs=100, seed=42)
        prediction = director.analyze(PAST_MATCH)
        evaluation = PostMatchEvaluationAgent().evaluate(prediction, actual)
        self.assertIn(evaluation.result_accuracy, ("correct", "incorrect"))
        self.assertIn(evaluation.score_accuracy, ("correct", "incorrect"))
        self.assertIn(evaluation.ou_accuracy, ("correct", "incorrect"))
        self.assertGreaterEqual(evaluation.event_accuracy, 0.0)
        self.assertLessEqual(evaluation.event_accuracy, 1.0)
        self.assertEqual(evaluation.actual_total_goals, 3)
        self.assertGreater(len(evaluation.notes), 0)

    def test_learning_store_roundtrip(self):
        tmp = _workspace_tmp("learn")
        try:
            store = LearningStore(tmp / "store.json")
            provider = make_provider()
            actual = provider.get_match_result(PAST_MATCH)
            director = make_director(runs=100, seed=42)
            prediction = director.analyze(PAST_MATCH)
            record = LearningAgent().learn(
                prediction, actual, PostMatchEvaluationAgent(), store)
            self.assertIsNotNone(record.record_id)
            # reload
            store2 = LearningStore(tmp / "store.json")
            self.assertEqual(len(store2.records), 1)
            self.assertEqual(store2.records[0].match_id, PAST_MATCH)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_learning_never_modifies_core_knowledge(self):
        from football_simulation.knowledge import load_all_knowledge
        before = load_all_knowledge()
        rules_before = {r.rule_id: r.status for r in before["rules"].rules}
        provider = make_provider()
        actual = provider.get_match_result(PAST_MATCH)
        director = make_director(runs=100, seed=42)
        prediction = director.analyze(PAST_MATCH)
        import shutil
        tmp = _workspace_tmp("learn2")
        try:
            store = LearningStore(tmp / "store.json")
            LearningAgent().learn(prediction, actual, PostMatchEvaluationAgent(), store)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        after = load_all_knowledge()
        rules_after = {r.rule_id: r.status for r in after["rules"].rules}
        self.assertEqual(rules_before, rules_after)


if __name__ == "__main__":
    unittest.main()
