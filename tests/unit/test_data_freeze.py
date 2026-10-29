"""Data layer & freeze tests: no future information leakage (spec 41/42/67/68)."""

import unittest
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from football_simulation.data import MockDataProvider, PreMatchFreeze, FutureDataError
from football_simulation.data.registry import load_registry_from_package
from tests.helpers import DEMO_MATCH, PAST_MATCH


class TestProviderInterface(unittest.TestCase):
    def setUp(self):
        self.provider = MockDataProvider()

    def test_all_interface_methods_exist(self):
        for method in ("get_team_data", "get_player_data", "get_coach_data",
                       "get_match_history", "get_lineup", "get_injury",
                       "get_referee_data", "get_weather", "get_odds", "get_event_data"):
            self.assertTrue(callable(getattr(self.provider, method)))

    def test_team_player_coach_consistency(self):
        request = self.provider.get_match_request(DEMO_MATCH)
        team = self.provider.get_team_data(request.home_team_id)
        self.assertEqual(len(self.provider.get_player_data(team.team_id)), 22)
        coach = self.provider.get_coach_data(team.coach_id)
        self.assertEqual(coach.team_id, team.team_id)

    def test_missing_team_raises(self):
        with self.assertRaises(KeyError):
            self.provider.get_team_data("team-nope")

    def test_history_respects_before(self):
        request = self.provider.get_match_request(DEMO_MATCH)
        history = self.provider.get_match_history(
            request.home_team_id, request.competition_id, request.season,
            request.kickoff - timedelta(days=30),
        )
        self.assertLess(len(history.entries), 10)

    def test_registry_not_hardcoded_five(self):
        registry = load_registry_from_package()
        comps = {c.competition_id for c in registry.list_competitions()}
        for league in ("premier_league", "la_liga", "bundesliga", "serie_a", "ligue_1"):
            self.assertIn(league, comps)
        # extension competitions present as data
        for extra in ("primeira_liga", "eredivisie", "champions_league"):
            self.assertIn(extra, comps)


class TestPreMatchFreeze(unittest.TestCase):
    def setUp(self):
        self.provider = MockDataProvider()
        self.request = self.provider.get_match_request(DEMO_MATCH)
        self.frozen = PreMatchFreeze(self.provider)
        self.frozen.freeze(self.request.kickoff)

    def test_frozen_blocks_post_match_data(self):
        with self.assertRaises(FutureDataError):
            self.frozen.get_match_result(PAST_MATCH)
        with self.assertRaises(FutureDataError):
            self.frozen.get_event_data(PAST_MATCH)

    def test_unfrozen_can_read_post_match(self):
        result = self.provider.get_match_result(PAST_MATCH)
        self.assertIsNotNone(result)
        self.assertTrue(result.available)

    def test_frozen_filters_late_lineups(self):
        from football_simulation.models.entities import FixtureLineup
        # a lineup reported AFTER kickoff must be invisible after freezing
        late = FixtureLineup(
            match_id=DEMO_MATCH, team_id=self.request.home_team_id,
            starters=["p1"], bench=[], confirmed=True,
            reported_at=self.request.kickoff + timedelta(hours=1),
        )
        provider = MockDataProvider()
        provider._lineups[DEMO_MATCH][late.team_id] = late
        frozen = PreMatchFreeze(provider)
        frozen.freeze(self.request.kickoff)
        lineup = frozen.get_lineup(late.team_id, DEMO_MATCH)
        self.assertFalse(lineup.confirmed)
        self.assertEqual(lineup.starters, [])

    def test_frozen_filters_late_injuries(self):
        provider = MockDataProvider()
        from football_simulation.models.entities import InjuryRecord
        late_injury = InjuryRecord(
            player_id="x", team_id=self.request.home_team_id, severity=0.5,
            known_at=self.request.kickoff + timedelta(hours=2),
        )
        provider._injuries[self.request.home_team_id].append(late_injury)
        frozen = PreMatchFreeze(provider)
        frozen.freeze(self.request.kickoff)
        injuries = frozen.get_injury(self.request.home_team_id, self.request.kickoff)
        self.assertNotIn("x", [i.player_id for i in injuries])

    def test_data_quality_reports_unknowns(self):
        dq = self.provider.data_quality(self.request)
        self.assertGreaterEqual(dq.completeness, 0.0)
        self.assertLessEqual(dq.completeness, 1.0)
        self.assertIn("team-ars", dq.lineup_confirmed)


if __name__ == "__main__":
    unittest.main()
