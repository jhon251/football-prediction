"""Seedable, reproducible RNG built on numpy's PCG64.

Every random draw in the system goes through this class so that
``WorldState + seed`` yields a reproducible match (spec section 46).
"""

from __future__ import annotations

from typing import List, Optional, Sequence

import numpy as np


class SeedableRNG:
    """Deterministic random stream.

    Supports bulk draws (``random(n)``) to keep the per-minute simulation
    loop fast, plus named child streams so independent subsystems never share
    a sequence.
    """

    def __init__(self, seed: int = 0):
        self._seed = int(seed)
        self._rng = np.random.default_rng(self._seed)

    @property
    def seed(self) -> int:
        return self._seed

    # -- bulk draws ------------------------------------------------------
    def random(self, n: Optional[int] = None) -> float:
        if n is None:
            return float(self._rng.random())
        return self._rng.random(n)

    def uniform(self, low: float, high: float, n: Optional[int] = None) -> float:
        if n is None:
            return float(self._rng.uniform(low, high))
        return self._rng.uniform(low, high, n)

    def normal(self, mu: float, sigma: float, low: Optional[float] = None, high: Optional[float] = None) -> float:
        v = float(self._rng.normal(mu, sigma))
        if low is not None:
            v = max(low, v)
        if high is not None:
            v = min(high, v)
        return v

    def poisson(self, lam: float) -> int:
        return int(self._rng.poisson(lam))

    def choice(self, items, p: Optional[Sequence[float]] = None):
        """``items`` may be a sequence (returns an item) or an int n
        (returns an index in [0, n))."""
        if isinstance(items, int):
            return int(self._rng.choice(items, p=p))
        return items[int(self._rng.choice(len(items), p=p))]

    def choices(self, items: Sequence, size: int, p: Optional[Sequence[float]] = None) -> List:
        return [items[i] for i in self._rng.choice(len(items), size=size, p=p)]

    def randint(self, low: int, high: int) -> int:
        return int(self._rng.integers(low, high))

    def bernoulli(self, p: float) -> bool:
        return bool(self._rng.random() < p)

    # -- child streams ----------------------------------------------------
    def spawn(self, tag: str) -> "SeedableRNG":
        """Deterministically derive an independent child stream.

        Uses a stable string hash (not ``hash()``, which is randomized per
        process) so results are reproducible across runs and machines.
        """
        stable = 2166136261
        for ch in tag:
            stable = ((stable ^ ord(ch)) * 16777619) & 0xFFFFFFFF
        child_seed = int((self._seed * 1000003 + stable) & 0xFFFFFFFF)
        return SeedableRNG(child_seed)

    def derive_seed(self, index: int) -> int:
        """Deterministic seed for the i-th simulation of a batch."""
        return int((self._seed * 1000003 + index * 7919) & 0xFFFFFFFF)
