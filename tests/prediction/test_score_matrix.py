# -*- coding: utf-8 -*-
"""Tests for football_prediction.score_matrix (derived score probability matrix)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from football_prediction.score_matrix import derive_score_matrix  # noqa: E402

import numpy as np  # noqa: E402

CASES = [
    # (home, draw, away, over) — realistic devigged market shapes
    (0.45, 0.27, 0.28, 0.55),   # typical
    (0.65, 0.22, 0.13, 0.60),   # strong home favourite
    (0.92, 0.05, 0.03, 0.48),   # extreme favourite
    (0.23, 0.35, 0.42, 0.42),   # drawish, low scoring
    (0.34, 0.31, 0.35, None),   # no OU target (1X2-only fit)
]


class ScoreMatrixTest(unittest.TestCase):
    def test_aggregates_reproduce_targets(self):
        for ph, pd, pa, po in CASES:
            with self.subTest(targets=(ph, pd, pa, po)):
                out = derive_score_matrix(ph, pd, pa, po)
                agg = out["aggregates"]
                self.assertLess(abs(agg["home"] - ph), 1e-9)
                self.assertLess(abs(agg["draw"] - pd), 1e-9)
                self.assertLess(abs(agg["away"] - pa), 1e-9)
                if po is not None:
                    self.assertLess(abs(agg["over25"] - po), 1e-9)
                    self.assertLess(abs(agg["under25"] - (1.0 - po)), 1e-9)
                self.assertEqual(out["status"], "VALID")

    def test_matrix_is_a_distribution(self):
        for ph, pd, pa, po in CASES:
            with self.subTest(targets=(ph, pd, pa, po)):
                out = derive_score_matrix(ph, pd, pa, po)
                m = np.array(out["matrix"])
                self.assertEqual(m.shape, (out["max_goals"] + 1,) * 2)
                self.assertTrue((m >= 0).all())
                # cells are rounded to 8 dp in the payload -> tolerate 1e-6 drift
                self.assertAlmostEqual(m.sum(), 1.0, places=6)
                self.assertAlmostEqual(float(np.tril(m, -1).sum()),
                                       out["aggregates"]["home"], places=6)

    def test_shape_and_payload(self):
        out = derive_score_matrix(0.45, 0.27, 0.28, 0.55)
        self.assertGreater(out["expected_goals"]["home"], 0.1)
        self.assertGreater(out["expected_goals"]["total"], 1.0)
        self.assertLess(out["expected_goals"]["total"], 6.0)
        self.assertTrue(0.0 < out["aggregates"]["btts_yes"] < 1.0)
        top = out["top_scorelines"]
        self.assertEqual(len(top), 10)
        probs = [t["probability"] for t in top]
        self.assertEqual(probs, sorted(probs, reverse=True))
        self.assertLessEqual(sum(probs), 1.0 + 1e-9)
        # strong favourite -> lambda_home exceeds lambda_away
        fav = derive_score_matrix(0.92, 0.05, 0.03, 0.48)
        self.assertGreater(fav["method"]["lambda_home"], fav["method"]["lambda_away"])

    def test_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            derive_score_matrix(0.5, 0.2, 0.1)          # sums to 0.8
        with self.assertRaises(ValueError):
            derive_score_matrix(0.0, 0.5, 0.5)          # zero probability
        with self.assertRaises(ValueError):
            derive_score_matrix(0.6, 0.2, 0.2, p_over=0.0)


if __name__ == "__main__":
    unittest.main()
