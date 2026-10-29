"""P0-1 tests: ESPN adapter empty-XI protection (no network)."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lineup_capture.adapters import ESPNAdapter  # noqa: E402


def _summary(rosters):
    kickoff = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
    return {
        "header": {"competitions": [{"date": kickoff,
                                     "competitors": [
                                         {"homeAway": "home", "team": {"displayName": "TeamA"}},
                                         {"homeAway": "away", "team": {"displayName": "TeamB"}}]}],
                   "season": {"year": "2026-27"}},
        "rosters": rosters,
    }


class FakeAdapter(ESPNAdapter):
    def __init__(self, payload):
        super().__init__(league="esp.1")
        self._payload = payload

    def _get(self, url):
        return self._payload


def _player(name):
    return {"starter": True, "athlete": {"id": name, "displayName": name},
            "position": {"abbreviation": "G"}}


class TestEmptyXIProtection(unittest.TestCase):

    def test_no_rosters_key_returns_none(self):
        adapter = FakeAdapter({"header": {"competitions": [{"date": "2026-08-22T14:00:00Z",
                                                            "competitors": []}]}})
        self.assertIsNone(adapter.get_lineup("E1"))

    def test_rosters_structure_with_zero_starters_returns_none(self):
        # P0-1 regression: ESPN rosters structure present but starters=0
        adapter = FakeAdapter(_summary([
            {"homeAway": "home", "team": {"displayName": "TeamA"}, "roster": [],
             "formation": "4-3-3"},
            {"homeAway": "away", "team": {"displayName": "TeamB"}, "roster": [],
             "formation": "4-4-2"},
        ]))
        self.assertIsNone(adapter.get_lineup("E1"))

    def test_full_xi_returns_state(self):
        adapter = FakeAdapter(_summary([
            {"homeAway": "home", "team": {"displayName": "TeamA"},
             "roster": [_player(f"A{i}") for i in range(11)], "formation": "4-3-3"},
            {"homeAway": "away", "team": {"displayName": "TeamB"},
             "roster": [_player(f"B{i}") for i in range(11)], "formation": "4-4-2"},
        ]))
        state = adapter.get_lineup("E1")
        self.assertIsNotNone(state)
        self.assertEqual(len(state.home_xi), 11)
        self.assertEqual(len(state.away_xi), 11)

    def test_one_sided_empty_returns_none(self):
        adapter = FakeAdapter(_summary([
            {"homeAway": "home", "team": {"displayName": "TeamA"},
             "roster": [_player(f"A{i}") for i in range(11)]},
            {"homeAway": "away", "team": {"displayName": "TeamB"}, "roster": []},
        ]))
        self.assertIsNone(adapter.get_lineup("E1"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
