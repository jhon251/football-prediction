"""Shared helpers for backtest tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from football_simulation.data.historical.etl import HistoricalDataset  # noqa: E402
from football_simulation.data.historical.source import SyntheticPremierLeagueSource  # noqa: E402

_DATASET = None


def get_dataset() -> HistoricalDataset:
    """Small cached synthetic dataset (clearly-labeled development stand-in)."""
    global _DATASET
    if _DATASET is None:
        matches = SyntheticPremierLeagueSource(
            seasons=("2021-22", "2022-23", "2023-24"), matches_per_season=380
        ).generate(seed=20240101)
        _DATASET = HistoricalDataset(matches, name="test_standin")
    return _DATASET


def slice_season(dataset: HistoricalDataset, season: str, n: int):
    """First n matches of a season (they still have prior-season history)."""
    return dataset.matches_in_season(season)[:n]
