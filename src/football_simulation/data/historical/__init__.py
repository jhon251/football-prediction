"""Historical data layer package (V1.2)."""

from football_simulation.data.historical.etl import HistoricalDataset
from football_simulation.data.historical.features import (
    build_team_features,
    fixture_congestion,
    form_points,
    league_goal_rate,
    league_home_rates,
    rolling_elo,
    rolling_elo_map,
    rolling_goal_rates,
)
from football_simulation.data.historical.provider import HistoricalDataProvider
from football_simulation.data.historical.schema import (
    HistoricalEvents,
    HistoricalGoal,
    HistoricalMatch,
    HistoricalOdds,
    HistoricalPreMatchSnapshot,
    LineupTriState,
)
from football_simulation.data.historical.snapshot import SnapshotBuilder, TemporalViolation
from football_simulation.data.historical.source import (
    CsvFootballDataCoUkSource,
    SyntheticPremierLeagueSource,
)

__all__ = [
    "CsvFootballDataCoUkSource",
    "HistoricalDataProvider",
    "HistoricalDataset",
    "HistoricalEvents",
    "HistoricalGoal",
    "HistoricalMatch",
    "HistoricalOdds",
    "HistoricalPreMatchSnapshot",
    "LineupTriState",
    "SnapshotBuilder",
    "SyntheticPremierLeagueSource",
    "TemporalViolation",
    "build_team_features",
    "fixture_congestion",
    "form_points",
    "league_goal_rate",
    "league_home_rates",
    "rolling_elo",
    "rolling_elo_map",
    "rolling_goal_rates",
]
