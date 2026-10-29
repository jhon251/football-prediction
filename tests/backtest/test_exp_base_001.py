"""EXP-REAL-EPL-BASE-001 support tests: metrics series, extended features,
no-market gates."""

import unittest
from pathlib import Path

from football_simulation.backtest.metrics import (
    per_match_series,
    phase_metrics,
    rolling_metrics,
)
from football_simulation.backtest.models import ExperimentRecord, ModelPrediction, PredictionRecord
from football_simulation.backtest.runner import WalkForwardBacktester
from football_simulation.data.historical import features as feats
from football_simulation.data.historical.etl import HistoricalDataset
from football_simulation.data.historical.provider import HistoricalDataProvider
from football_simulation.data.historical.snapshot import SnapshotBuilder

CANONICAL = Path(__file__).resolve().parents[2] / "data" / "historical" / "epl_2025_26.json"


def _record(i: int, home_p: float) -> PredictionRecord:
    from datetime import datetime, timezone
    return PredictionRecord(
        match_id=f"m{i}", kickoff=datetime(2025, 8, 15, tzinfo=timezone.utc),
        home_team="h", away_team="a",
        actual_home_goals=1 if i % 2 == 0 else 0,
        actual_away_goals=0 if i % 2 == 0 else 1,
        predictions={"m": ModelPrediction(
            model="m", home_win=home_p, draw=0.3, away_win=0.7 - home_p,
            expected_goals=2.6, over25=0.5, btts_yes=0.5,
            score_matrix={"1-0": 0.2, "1-1": 0.2, "0-1": 0.2, "2-1": 0.2, "2-0": 0.2})},
        synthetic=False)


class TestMetricSeries(unittest.TestCase):
    def test_per_match_series_lengths(self):
        records = [_record(i, 0.55) for i in range(6)]
        series = per_match_series(records, "m")
        self.assertEqual(len(series["brier"]), 6)
        self.assertEqual(len(series["log_loss"]), 6)
        self.assertEqual(len(series["correct"]), 6)
        for value in series["correct"]:
            self.assertIn(value, (0.0, 1.0))

    def test_rolling_window_growth(self):
        records = [_record(i, 0.55) for i in range(12)]
        rolling = rolling_metrics(records, "m", window=100)
        self.assertEqual(len(rolling), 12)
        self.assertEqual(rolling[0]["window_size"], 1)
        self.assertEqual(rolling[5]["window_size"], 6)

    def test_phases_split(self):
        records = [_record(i, 0.55) for i in range(30)]
        phases = phase_metrics(records, "m")
        self.assertEqual([p["phase"] for p in phases],
                         ["early_season", "mid_season", "late_season"])
        self.assertEqual(phases[0]["matches"], "1-10")
        self.assertEqual(phases[2]["matches"], "21-30")
        self.assertEqual(phases[0]["n"], 10.0)


class TestExperimentRecordMarketFlag(unittest.TestCase):
    def test_market_data_defaults_false(self):
        entry = ExperimentRecord(data_version="x", random_seed=1, train_period="t",
                                 test_period="p", models=[], matches_evaluated=0,
                                 metrics={}, synthetic_data=False)
        self.assertFalse(entry.market_data)


@unittest.skipUnless(CANONICAL.exists(), "real dataset not present")
class TestExtendedFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = HistoricalDataset.load(CANONICAL)

    def test_rolling_match_stats_walk_forward_safe(self):
        """Deleting future rows must not change the stat aggregates."""
        match = self.dataset.matches_in_season("2025-26")[50]
        full = feats.rolling_match_stats(self.dataset.matches, match.home_team, match.date)
        truncated = feats.rolling_match_stats(
            [m for m in self.dataset.matches if m.date < match.date],
            match.home_team, match.date)
        self.assertEqual(full, truncated)

    def test_rolling_match_stats_present(self):
        match = self.dataset.matches_in_season("2025-26")[60]
        stats = feats.rolling_match_stats(self.dataset.matches, match.home_team, match.date)
        self.assertGreaterEqual(stats["matches"], 5)
        self.assertGreaterEqual(stats["n_shots"], 5)
        self.assertGreaterEqual(stats["n_sot"], 5)
        self.assertGreater(stats["shots_for"], 0)

    def test_provider_odds_gate(self):
        match = self.dataset.matches_in_season("2025-26")[70]
        snapshot = SnapshotBuilder(self.dataset.matches, strict=True).build(match)
        with_odds = HistoricalDataProvider(self.dataset, snapshot, expose_odds=True)
        without_odds = HistoricalDataProvider(self.dataset, snapshot, expose_odds=False)
        self.assertIsNotNone(with_odds.get_odds(match.match_id))
        self.assertIsNone(without_odds.get_odds(match.match_id))

    def test_runner_excludes_market(self):
        runner = WalkForwardBacktester(self.dataset, runs=30, seed=1,
                                       include_system=False,
                                       exclude_models={"market_odds"})
        self.assertNotIn("market_odds", runner.baselines)
        match = self.dataset.matches_in_season("2025-26")[90]
        record = runner.predict_one(match)
        self.assertNotIn("market_odds", record.predictions)


@unittest.skipUnless(CANONICAL.exists(), "real dataset not present")
class TestExperimentSmoke(unittest.TestCase):
    def test_tiny_blind_run(self):
        """4 matches, 80 sims: the full experiment path must produce no odds."""
        dataset = HistoricalDataset.load(CANONICAL)
        targets = dataset.matches_in_season("2025-26")[120:124]
        history = [m for m in dataset.matches if m.date < targets[-1].date]
        combined = {m.match_id: m for m in history + targets}
        mini = HistoricalDataset(list(combined.values()), name="mini")
        runner = WalkForwardBacktester(
            mini, runs=80, seed=7, include_system=True,
            exclude_models={"market_odds"}, extended_features=True,
            expose_odds=False, refit_every=20,
        )
        records = runner.run_season(
            "2025-26", resume=False, match_ids={m.match_id for m in targets})
        self.assertEqual(len(records), 4)
        for record in records:
            self.assertNotIn("market_odds", record.predictions)
            self.assertIn("full_system", record.predictions)
            prediction = record.predictions["full_system"]
            self.assertEqual(prediction.validate_probabilities(), [])
            self.assertFalse(record.synthetic)


if __name__ == "__main__":
    unittest.main()
