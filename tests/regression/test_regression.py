"""Regression tests: golden values for the demo fixture.

These pin the deterministic pipeline (fixtures + seed) so any change that
silently shifts the simulation behavior is caught.  Golden values were
recorded with the bundled synthetic fixtures and seed 12345 / 2000 runs.
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.helpers import make_director

GOLDEN = {
    "home_win": 0.4430,
    "draw": 0.2715,
    "away_win": 0.2855,
    "expected_goals": 3.117,
    "over25": 0.5805,
    "btts_yes": 0.6220,
    "top_score": "1-1",
    "upset_level": "medium",
    "confidence_level": "medium",
}

TOL = {
    "prob": 0.03,   # 3 percentage points for probabilities at n=2000
    "goals": 0.25,
}


class TestRegressionGolden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = make_director(runs=2000, seed=12345).analyze("match-demo-001")

    def test_result_probability(self):
        r = self.report.result_probability
        self.assertAlmostEqual(r.home_win, GOLDEN["home_win"], delta=TOL["prob"])
        self.assertAlmostEqual(r.draw, GOLDEN["draw"], delta=TOL["prob"])
        self.assertAlmostEqual(r.away_win, GOLDEN["away_win"], delta=TOL["prob"])

    def test_expected_goals(self):
        self.assertAlmostEqual(
            self.report.goals_probability.expected_total_goals,
            GOLDEN["expected_goals"], delta=TOL["goals"],
        )

    def test_over_under(self):
        self.assertAlmostEqual(
            self.report.goals_probability.over["2.5"], GOLDEN["over25"], delta=TOL["prob"])

    def test_btts(self):
        self.assertAlmostEqual(
            self.report.btts.yes, GOLDEN["btts_yes"], delta=TOL["prob"])

    def test_top_score(self):
        self.assertEqual(self.report.score_probability.top(1)[0]["score"],
                         GOLDEN["top_score"])

    def test_levels_stable(self):
        self.assertEqual(self.report.upset_risk.level.value, GOLDEN["upset_level"])
        self.assertEqual(self.report.confidence.level.value, GOLDEN["confidence_level"])


class TestRegressionReproducibility(unittest.TestCase):
    def test_same_seed_same_output(self):
        r1 = make_director(runs=500, seed=7).analyze("match-demo-001")
        r2 = make_director(runs=500, seed=7).analyze("match-demo-001")
        self.assertEqual(r1.result_probability.model_dump(), r2.result_probability.model_dump())
        self.assertEqual(r1.score_probability.model_dump(), r2.score_probability.model_dump())


if __name__ == "__main__":
    unittest.main()
