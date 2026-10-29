"""EXP-DIAG-EPL-001 diagnosis-module tests (read-only vs production)."""

import unittest
from pathlib import Path

from football_simulation.backtest.diagnosis import (
    baseline_manifest,
    correlations,
    distribution_stats,
    elo_coverage,
    influence_summary,
    reconstruct_prematch_layer,
)
from football_simulation.backtest.models import ModelPrediction, PredictionRecord
from football_simulation.data.historical.etl import HistoricalDataset

BASELINE_DIR = Path(__file__).resolve().parents[2] / "backtest_output" / "real_epl_base_001"
DATASET = Path(__file__).resolve().parents[2] / "data" / "historical" / "epl_2025_26.json"


@unittest.skipUnless(BASELINE_DIR.exists(), "baseline dir missing")
class TestBaselineIntegrity(unittest.TestCase):
    def test_manifest_covers_baseline_files(self):
        manifest = baseline_manifest(BASELINE_DIR)
        self.assertEqual(manifest["experiment_id"], "7c52c6bdfa37")
        self.assertGreaterEqual(len(manifest["files"]), 8)
        # every frozen artifact has a recorded hash
        for name in ("records.json", "metrics.json", "ablation.json",
                     "calibration.json", "phases.json", "rolling.json"):
            self.assertIn(name, manifest["files"])


@unittest.skipUnless(DATASET.exists(), "real dataset missing")
class TestDiagnosisReconstruction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = HistoricalDataset.load(DATASET)

    def test_reconstruction_size_and_shape(self):
        rows = reconstruct_prematch_layer(self.dataset)
        self.assertEqual(len(rows), 380)
        for row in rows:
            self.assertIn("elo_diff", row)
            self.assertIn("team_strength_diff", row)
            self.assertTrue(row["player_no_signal"])
            self.assertFalse(row["momentum_trajectory_available"])
            self.assertEqual(row["referee_signal"], 0.0)

    def test_stats(self):
        rows = reconstruct_prematch_layer(self.dataset)
        stats = distribution_stats([r["elo_diff"] for r in rows])
        self.assertEqual(stats["n"], 380.0)
        self.assertGreater(stats["std"], 20.0)

    def test_correlations_shape(self):
        rows = reconstruct_prematch_layer(self.dataset)
        corr = correlations(rows, ["elo_diff", "team_strength_diff",
                                   "psych_confidence_diff"])
        self.assertEqual(len(corr["pearson"]), 3)  # 3 pairs
        for key in corr["pearson"]:
            self.assertTrue(-1.0 <= corr["pearson"][key] <= 1.0)
            self.assertTrue(-1.0 <= corr["spearman"][key] <= 1.0)


class TestDiagnosisMetricsHelpers(unittest.TestCase):
    def _pred(self, home: float) -> ModelPrediction:
        return ModelPrediction(model="x", home_win=home, draw=(1 - home) / 2,
                               away_win=(1 - home) / 2, expected_goals=2.6,
                               over25=0.5, btts_yes=0.5, score_matrix={"1-0": 0.2})

    def test_influence_summary(self):
        preds = {
            "full": {"m1": self._pred(0.6), "m2": self._pred(0.4)},
            "full_minus_team": {"m1": self._pred(0.5), "m2": self._pred(0.5)},
        }
        summary = influence_summary(preds, "Team")
        # deltas: +0.1 and -0.1 -> mean abs 0.1, max abs 0.1
        self.assertAlmostEqual(summary["mean_abs_delta"], 0.1)
        self.assertAlmostEqual(summary["max_abs_delta"], 0.1)
        self.assertAlmostEqual(summary["share_delta_gt_1pp"], 1.0)

    def test_elo_coverage_shape(self):
        from datetime import datetime, timezone
        record = PredictionRecord(
            match_id="m1", kickoff=datetime(2025, 9, 1, tzinfo=timezone.utc),
            home_team="h", away_team="a", actual_home_goals=1, actual_away_goals=0,
            predictions={"elo": self._pred(0.7)}, synthetic=False)
        team = {"m1": self._pred(0.6)}
        coverage = elo_coverage([record], team)
        self.assertEqual(coverage["n"], 1)
        self.assertIn("corr_team_elo_home_prob", coverage)


if __name__ == "__main__":
    unittest.main()
