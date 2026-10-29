"""V1.2 schema/ETL, baselines, and metrics tests."""

import unittest

from football_simulation.backtest.baselines import (
    EloBaseline,
    HistoricalGoalRateBaseline,
    HomeAdvantageBaseline,
    MarketBaseline,
    PoissonBaseline,
    RandomBaseline,
    make_baselines,
)
from football_simulation.backtest.metrics import (
    binary_metrics,
    calibration_curve,
    full_metrics,
    one_x_two_metrics,
    score_metrics,
)
from football_simulation.backtest.models import ModelPrediction, PredictionRecord
from football_simulation.data.historical.etl import HistoricalDataset
from football_simulation.data.historical.features import rolling_elo_map
from tests.backtest.helpers import get_dataset, slice_season


class TestSchemaEtl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = get_dataset()

    def test_dataset_validates_clean(self):
        self.assertEqual(self.dataset.validate(), [])

    def test_all_rows_labeled_synthetic(self):
        self.assertTrue(all(m.is_synthetic for m in self.dataset.matches))
        self.assertTrue(all("synthetic" in m.source for m in self.dataset.matches))

    def test_result_consistency(self):
        for match in self.dataset.matches[:100]:
            self.assertGreaterEqual(match.home_goals, match.half_time_home_goals)
            self.assertGreaterEqual(match.away_goals, match.half_time_away_goals)

    def test_seasons_and_teams(self):
        summary = self.dataset.summary()
        self.assertGreaterEqual(len(summary["seasons"]), 3)
        self.assertEqual(summary["teams"], 20)


class TestFeaturesWalkForward(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = get_dataset()

    def test_elo_only_uses_past(self):
        match = self.dataset.matches_in_season("2023-24")[0]
        before = rolling_elo_map(self.dataset.matches, match.date)
        # deleting future rows must not change the ratings
        truncated = [m for m in self.dataset.matches if m.date < match.date]
        before_truncated = rolling_elo_map(truncated, match.date)
        self.assertEqual(before, before_truncated)

    def test_elo_orders_teams_sensibly(self):
        match = self.dataset.matches_in_season("2023-24")[10]
        elos = rolling_elo_map(self.dataset.matches, match.date)
        values = sorted(elos.values())
        self.assertGreater(values[-1] - values[0], 50)  # spread exists


class TestBaselines(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = get_dataset()
        cls.matches = slice_season(cls.dataset, "2023-24", 12)

    def test_all_baselines_present(self):
        baselines = make_baselines()
        for name in ("random", "home_advantage", "elo", "historical_goal_rate",
                     "poisson", "market_odds"):
            self.assertIn(name, baselines)

    def test_probabilities_sum_to_one(self):
        baselines = make_baselines()
        poisson_params = baselines["poisson"].fit(self.dataset, self.matches[0].date)
        for match in self.matches:
            for name, baseline in baselines.items():
                if name == "poisson":
                    pred = baseline.predict(self.dataset, match, poisson_params)
                else:
                    pred = baseline.predict(self.dataset, match)
                if pred is None:
                    continue
                self.assertEqual(pred.validate_probabilities(), [],
                                 f"{name} @ {match.match_id}: {pred.validate_probabilities()}")

    def test_odds_implied_normalized(self):
        for match in self.matches[:6]:
            implied = match.closing_odds.implied_probabilities()
            self.assertAlmostEqual(sum(implied.values()), 1.0, places=5)

    def test_market_baseline_matches_implied_direction(self):
        baseline = MarketBaseline()
        for match in self.matches[:6]:
            pred = baseline.predict(self.dataset, match)
            implied = match.closing_odds.implied_probabilities()
            self.assertAlmostEqual(pred.home_win, implied["home"], delta=0.03)
            self.assertAlmostEqual(pred.away_win, implied["away"], delta=0.03)

    def test_poisson_fit_uses_training_window_only(self):
        baselines = make_baselines()
        first = self.matches[0]
        params = baselines["poisson"].fit(self.dataset, first.date)
        # no test-season match may influence the fitted params
        refit = baselines["poisson"].fit(
            HistoricalDataset([m for m in self.dataset.matches if m.date < first.date]),
            first.date)
        self.assertEqual(sorted(params["attack"]), sorted(refit["attack"]))


class TestMetrics(unittest.TestCase):
    def _records(self):
        records = []
        for i, (result, pred) in enumerate([
                ("home_win", (0.7, 0.2, 0.1)),
                ("draw", (0.3, 0.4, 0.3)),
                ("away_win", (0.2, 0.3, 0.5)),
                ("home_win", (0.4, 0.3, 0.3)),
        ]):
            from datetime import datetime, timezone
            p = ModelPrediction(model="m", home_win=pred[0], draw=pred[1],
                                away_win=pred[2], expected_goals=2.6,
                                over25=0.5, over35=0.25, btts_yes=0.5,
                                score_matrix={"1-0": 0.2, "1-1": 0.2, "0-1": 0.2, "2-1": 0.2, "2-0": 0.2})
            records.append(PredictionRecord(
                match_id=f"m{i}", kickoff=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
                home_team="h", away_team="a",
                actual_home_goals=1 if result == "home_win" else 0,
                actual_away_goals=1 if result == "away_win" else 0,
                predictions={"m": p}, synthetic=True))
        return records

    def test_brier_known_value(self):
        records = self._records()
        metrics = one_x_two_metrics(records, "m")
        # match1 home (0.7,0.2,0.1)->0.14; match2 draw (0.3,0.4,0.3)->0.54;
        # match3 away (0.2,0.3,0.5)->0.38; match4 home (0.4,0.3,0.3)->0.54
        self.assertAlmostEqual(metrics["brier"], (0.14 + 0.54 + 0.38 + 0.54) / 4, places=4)

    def test_accuracy_and_top2(self):
        records = self._records()
        metrics = one_x_two_metrics(records, "m")
        self.assertEqual(metrics["accuracy"], 1.0)  # every record's top-1 hits
        self.assertEqual(metrics["top2_accuracy"], 1.0)

    def test_calibration_bins(self):
        records = self._records()
        calibration = calibration_curve(records, "m")
        self.assertGreaterEqual(len(calibration["bins"]), 3)
        self.assertGreaterEqual(calibration["ece"], 0.0)

    def test_score_metrics(self):
        records = self._records()
        metrics = score_metrics(records, "m")
        self.assertGreaterEqual(metrics["exact_score_accuracy"], 0.0)
        self.assertGreaterEqual(metrics["top5_score_coverage"], 0.0)

    def test_binary_metrics(self):
        records = self._records()
        ou = binary_metrics(records, "m", "ou25")
        self.assertIsNotNone(ou)
        self.assertIn("brier", ou)
        btts = binary_metrics(records, "m", "btts")
        self.assertIsNotNone(btts)


if __name__ == "__main__":
    unittest.main()
