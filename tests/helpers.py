"""Shared test helpers (unittest-based, no pytest dependency)."""

from __future__ import annotations

import sys
from pathlib import Path

# make the src layout importable when running tests directly
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from football_simulation.agents.director import DirectorAgent, DirectorConfig  # noqa: E402
from football_simulation.data import MockDataProvider  # noqa: E402

DEMO_MATCH = "match-demo-001"
PAST_MATCH = "match-demo-000"


def make_provider() -> MockDataProvider:
    return MockDataProvider()


def make_director(runs: int = 200, seed: int = 42, **kwargs) -> DirectorAgent:
    return DirectorAgent(
        make_provider(),
        DirectorConfig(simulation_runs=runs, seed=seed, **kwargs),
    )


def prepare_world(runs: int = 50, seed: int = 42):
    """Run the pre-match agent chain and return (context, world, matchup, ...)."""
    director = make_director(runs, seed)
    return director.prepare_world(DEMO_MATCH), director
