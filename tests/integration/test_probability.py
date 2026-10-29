"""Probability conservation tests (spec section 53)."""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from football_simulation.agents.probability import (
    GoalsOUProbabilityAgent,
    HTFTProbabilityAgent,
    ResultProbabilityAgent,
    ScoreProbabilityAgent,
)
from tests.helpers import make_director
from tests.integration.test_simulation import build_engine


class TestProbabilityConservation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine, world = build_engine()
        cls.batch = engine.simulate_n_matches(n=1000, base_seed=2024)

    def test_result_probability_sums_to_one(self):
        result = ResultProbabilityAgent().compute(self.batch)
        total = result.home_win + result.draw + result.away_win
        self.assertAlmostEqual(total, 1.0, places=4)

    def test_score_matrix_sums_to_one(self):
        matrix = ScoreProbabilityAgent().compute(self.batch)
        self.assertAlmostEqual(matrix.total(), 1.0, places=4)
        # covers 0..6 cap
        for key in matrix.matrix:
            h, a = key.split("-")
            self.assertLessEqual(int(h), 6)
            self.assertLessEqual(int(a), 6)

    def test_ou_complementary(self):
        goals, btts = GoalsOUProbabilityAgent().compute(self.batch)
        for line in goals.over:
            self.assertAlmostEqual(goals.over[line] + goals.under[line], 1.0, places=6)
        for line in ("0.5", "1.5", "2.5", "3.5", "4.5", "5.5"):
            self.assertIn(line, goals.over)

    def test_btts_complementary(self):
        goals, btts = GoalsOUProbabilityAgent().compute(self.batch)
        self.assertAlmostEqual(btts.yes + btts.no, 1.0, places=6)

    def test_htft_sums_to_one(self):
        htft = HTFTProbabilityAgent().compute(self.batch)
        total = sum(htft.combinations.values())
        self.assertAlmostEqual(total, 1.0, places=4)
        self.assertAlmostEqual(
            htft.ht_home_win + htft.ht_draw + htft.ht_away_win, 1.0, places=4
        )
        for combo in htft.combinations:
            self.assertIn(combo.count("/"), (1,))

    def test_expected_goals_positive(self):
        goals, btts = GoalsOUProbabilityAgent().compute(self.batch)
        self.assertGreater(goals.expected_total_goals, 0.0)
        dist_total = sum(goals.total_goals_distribution.values())
        self.assertAlmostEqual(dist_total, 1.0, places=4)

    def test_monotonic_over_lines(self):
        goals, btts = GoalsOUProbabilityAgent().compute(self.batch)
        for low, high in (("0.5", "1.5"), ("1.5", "2.5"), ("2.5", "3.5"),
                          ("3.5", "4.5"), ("4.5", "5.5")):
            self.assertGreaterEqual(goals.over[low], goals.over[high])


class TestProbabilityConsistencyWithBatch(unittest.TestCase):
    def test_counts_match_batch(self):
        engine, world = build_engine()
        batch = engine.simulate_n_matches(n=500, base_seed=77)
        result = ResultProbabilityAgent().compute(batch)
        counts = batch.result_counts()
        self.assertAlmostEqual(result.home_win, counts["home_win"] / 500, places=6)


if __name__ == "__main__":
    unittest.main()
