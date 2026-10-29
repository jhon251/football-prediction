"""V1.1 Ablation / Agent Contribution tests (spec V1.1 sections 8/9).

Measures which agents actually move the simulated probabilities, and asserts
the HONEST expectations: Team/Tactical matter, while Scenario/Counterfactual
cannot change 1X2 (they are post-hoc layers) - their contribution is to the
report, not to the simulation.
"""

import unittest

from football_simulation.evaluation.ablation import AblationRunner, ABLATION_ORDER
from football_simulation.models.validation import AgentContributionRow

REDUCED_ORDER = ["Team", "Coach", "Player", "Fitness", "Psychology",
                 "Tactical", "Referee", "Momentum", "Scenario", "Counterfactual"]


class TestAblation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = AblationRunner().run("match-demo-001", runs=250, seed=42,
                                        order=REDUCED_ORDER)

    def test_row_structure(self):
        self.assertEqual(len(self.rows), len(REDUCED_ORDER) + 2)  # baseline + full
        self.assertEqual(self.rows[0].config, "baseline (all agents off)")
        self.assertEqual(self.rows[-1].config, "full system")
        for row in self.rows:
            self.assertTrue(0.0 <= row.home_win <= 1.0)
            self.assertGreaterEqual(row.expected_goals, 0.0)

    def test_deltas_recorded(self):
        deltas = [r.delta_home_win for r in self.rows[1:]]
        self.assertEqual(len(deltas), len(REDUCED_ORDER) + 1)
        for delta in deltas:
            self.assertIsNotNone(delta)

    def test_team_agent_actually_matters(self):
        baseline = self.rows[0].home_win
        team_row = self.rows[1]  # first enabled agent
        self.assertNotAlmostEqual(team_row.home_win, baseline, places=3,
                                  msg="TeamAgent must move the simulation away from neutral")

    def test_full_system_differs_from_baseline(self):
        self.assertNotAlmostEqual(self.rows[-1].home_win, self.rows[0].home_win, places=3)

    def test_scenario_and_counterfactual_do_not_change_probabilities(self):
        """Honest expectation: post-hoc layers cannot alter the simulation."""
        by_config = {r.config: r for r in self.rows}
        before_scenario = by_config["+ Momentum"]
        with_scenario = by_config["+ Scenario"]
        with_counter = by_config["+ Counterfactual"]
        self.assertAlmostEqual(with_scenario.home_win, before_scenario.home_win, places=6)
        self.assertAlmostEqual(with_counter.home_win, with_scenario.home_win, places=6)

    def test_contributions_summary_meaningful(self):
        """At least one non-trivial agent contributes; nothing explodes."""
        max_abs = max(abs(r.delta_home_win or 0.0) for r in self.rows[1:])
        self.assertGreater(max_abs, 0.005, "some agent must meaningfully move 1X2")
        self.assertLess(max_abs, 0.3, "no single agent may dominate absurdly")


class TestAblationOrderComplete(unittest.TestCase):
    def test_ablation_order_covers_required_agents(self):
        for required in ("Team", "Coach", "Player", "Fitness", "Psychology",
                         "Tactical", "Environment", "Referee", "Momentum",
                         "Scenario", "Counterfactual"):
            self.assertIn(required, ABLATION_ORDER)


if __name__ == "__main__":
    unittest.main()
