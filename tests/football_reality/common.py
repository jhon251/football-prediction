"""Shared helpers for the football-reality test package."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from football_simulation.evaluation.reality import RealityHarness  # noqa: E402

_HARNESS = None


def get_harness() -> RealityHarness:
    """Cached harness (module-level reuse keeps the suite fast)."""
    global _HARNESS
    if _HARNESS is None:
        _HARNESS = RealityHarness()
    return _HARNESS
