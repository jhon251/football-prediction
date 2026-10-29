"""V1.2 temporal-integrity / time-travel tests (spec section 6).

The strongest test: deleting every row at/after a match's kickoff must leave
the pre-match snapshot bit-identical.  Any difference proves future leakage.
"""

import unittest
from datetime import timedelta

from football_simulation.data.historical.schema import LineupTriState
from football_simulation.data.historical.snapshot import SnapshotBuilder, TemporalViolation
from tests.backtest.helpers import get_dataset


class TestTimeTravel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = get_dataset()

    def test_deleting_future_rows_leaves_snapshots_identical(self):
        builder = SnapshotBuilder(self.dataset.matches, strict=True)
        result = builder.verify_time_travel()
        self.assertTrue(result["passed"], f"violations: {result['violations'][:5]}")

    def test_snapshot_contains_no_post_kickoff_observations(self):
        builder = SnapshotBuilder(self.dataset.matches, strict=True)
        for match in self.dataset.matches[:40]:
            snapshot = builder.build(match)
            self.assertEqual(snapshot.rejected_observations, [])
            for entry in snapshot.team_features.get("home", {}).values():
                pass  # features are scalars by construction

    def test_late_odds_rejected(self):
        from football_simulation.data.historical.schema import HistoricalMatch, HistoricalOdds
        match = self.dataset.matches[100]
        late_odds = HistoricalOdds(home=2.0, draw=3.4, away=3.8,
                                   odds_timestamp=match.date + timedelta(hours=2))
        poisoned = match.model_copy(update={"closing_odds": late_odds})
        builder = SnapshotBuilder(self.dataset.matches, strict=True)
        with self.assertRaises(TemporalViolation):
            builder.build(poisoned)

    def test_late_lineup_rejected(self):
        match = self.dataset.matches[100]
        poisoned = match.model_copy(
            update={"home_lineup_status": LineupTriState.CONFIRMED,
                    "home_lineup": ["p1"] * 11,
                    "lineup_observed_at": match.date + timedelta(minutes=5)})
        builder = SnapshotBuilder(self.dataset.matches, strict=True)
        with self.assertRaises(TemporalViolation):
            builder.build(poisoned)

    def test_lineup_tri_state_respected(self):
        builder = SnapshotBuilder(self.dataset.matches, strict=True)
        match = self.dataset.matches[50]
        snapshot = builder.build(match)
        # the stand-in dataset never publishes lineups -> UNKNOWN, preserved
        self.assertEqual(snapshot.home_lineup_status, LineupTriState.UNKNOWN)
        self.assertEqual(snapshot.away_lineup_status, LineupTriState.UNKNOWN)
        self.assertIn("home_lineup", snapshot.unknowns)

    def test_predicted_lineup_never_confirmed(self):
        from football_simulation.data.historical.schema import HistoricalMatch
        match = self.dataset.matches[60]
        predicted = match.model_copy(
            update={"home_lineup_status": LineupTriState.PREDICTED,
                    "home_lineup": [f"p{i}" for i in range(11)],
                    "lineup_observed_at": match.date - timedelta(days=1)})
        builder = SnapshotBuilder(self.dataset.matches, strict=True)
        snapshot = builder.build(predicted)
        self.assertEqual(snapshot.home_lineup_status, LineupTriState.PREDICTED)

    def test_odds_timestamp_strictly_before_kickoff(self):
        for match in self.dataset.matches[:50]:
            if match.closing_odds is None:
                continue
            self.assertIsNotNone(match.closing_odds.odds_timestamp)
            self.assertLess(match.closing_odds.odds_timestamp, match.date)


if __name__ == "__main__":
    unittest.main()
