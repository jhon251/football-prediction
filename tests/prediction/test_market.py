# -*- coding: utf-8 -*-
"""Unit tests for the market baseline (M4/O2) — spec §5 T1-T4 + N6/N9."""
import importlib.util
import unittest
from pathlib import Path

import numpy as np

from football_prediction import market as M

ROOT = Path(__file__).resolve().parents[2]
P4A_PATH = ROOT / "backtest_output" / "experiments" / "phase4a_market_baseline" / "run_phase4a.py"


def _load_p4a():
    spec = importlib.util.spec_from_file_location("p4a_reference", P4A_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestShinSolver(unittest.TestCase):
    def test_t1_hand_example_three_way(self):
        # odds 2.0/3.5/4.5 -> q = 0.5/0.2857/0.2222, overround ~1.0079
        p, z = M.shin_probs(np.array([[1 / 2.0, 1 / 3.5, 1 / 4.5]]))
        self.assertAlmostEqual(float(p.sum()), 1.0, places=12)
        self.assertGreater(float(z[0]), 0.0)
        # favourite must keep the highest implied probability
        self.assertEqual(int(np.argmax(p[0])), 0)

    def test_t1_two_way_sums_to_one(self):
        p, z = M.shin_probs(np.array([[1 / 1.9, 1 / 1.95]]))
        self.assertAlmostEqual(float(p.sum()), 1.0, places=12)

    def test_no_overround_falls_back_to_normalization(self):
        q = np.array([[0.4, 0.35, 0.25]])  # sums to 1.0 -> z=0 branch
        p, z = M.shin_probs(q)
        self.assertAlmostEqual(float(z[0]), 0.0, places=12)
        np.testing.assert_allclose(p[0], q[0] / q[0].sum(), rtol=1e-9)

    def test_t2_equivalence_with_phase4a(self):
        """Pin: our shin_probs is bit-for-bit the Phase 4A validated solver."""
        p4a = _load_p4a()
        rng = np.random.default_rng(20260913)
        for k in (2, 3, 5):
            q = rng.uniform(0.1, 0.9, size=(256, k))
            ours_p, ours_z = M.shin_probs(q)
            ref_p, ref_z = p4a.shin_probs(q)
            np.testing.assert_array_equal(ours_p, ref_p)
            np.testing.assert_array_equal(ours_z, ref_z)

    def test_t2_end_to_end_method_equivalence_with_phase4a(self):
        """Pin: M4/O2 pipelines equal phase4a method_ftr/method_ou25 on random books."""
        p4a = _load_p4a()
        rng = np.random.default_rng(42)
        for _ in range(200):
            n_books = int(rng.integers(2, 6))
            codes = list(p4a.BOOKS_1X2)[:n_books]
            books, pre = {}, {}
            for code in codes:
                h, d, a = rng.uniform(1.3, 8.0, size=3)
                books[code] = {"H": round(float(h), 2), "D": round(float(d), 2),
                               "A": round(float(a), 2)}
                pre[f"{code}H"], pre[f"{code}D"], pre[f"{code}A"] = books[code]["H"], \
                    books[code]["D"], books[code]["A"]
            ours = M.ftr_prediction(books)
            ref = p4a.method_ftr({"odds": {"preclosing": pre}}, "M4")
            self.assertIsNotNone(ref)
            np.testing.assert_allclose(ours.probabilities, ref[0], rtol=1e-9, atol=1e-12)
            self.assertEqual(ours.n_books, ref[1])

            # OU25 multi-book (O4) — drop B365 on both sides so both take the O4 path
            ou_books, ou_pre = {}, {}
            for code in [c for c in p4a.BOOKS_OU if c != "B365"]:
                o, u = rng.uniform(1.3, 3.5, size=2)
                ou_books[code] = {">2.5": round(float(o), 2), "<2.5": round(float(u), 2)}
                ou_pre[f"{code}>2.5"], ou_pre[f"{code}<2.5"] = ou_books[code][">2.5"], \
                    ou_books[code]["<2.5"]
            ours_ou = M.ou25_prediction(ou_books)
            self.assertEqual(ours_ou.method_id, "O4")
            ref_ou = p4a.method_ou25({"odds": {"preclosing": ou_pre}}, "O4")
            np.testing.assert_allclose([ours_ou.probabilities[0]], [ref_ou[0]],
                                       rtol=1e-9, atol=1e-12)

    def test_t2_b365_single_book_o2_equivalence(self):
        p4a = _load_p4a()
        pre = {"B365>2.5": 1.85, "B365<2.5": 2.02}
        ours = M.ou25_prediction({"B365": {">2.5": 1.85, "<2.5": 2.02}})
        ref = p4a.method_ou25({"odds": {"preclosing": pre}}, "O2")
        self.assertEqual(ours.method_id, "O2")
        self.assertAlmostEqual(ours.probabilities[0], ref[0], places=12)

    def test_t3_m4_multi_book(self):
        res = M.ftr_prediction({
            "B365": {"H": 2.10, "D": 3.50, "A": 3.60},
            "VC": {"H": 2.05, "D": 3.40, "A": 3.55},
            "WH": {"H": 2.15, "D": 3.45, "A": 3.65},
        })
        self.assertEqual(res.method_id, "M4")
        self.assertEqual(res.n_books, 3)
        self.assertAlmostEqual(sum(res.probabilities), 1.0, places=9)
        self.assertGreater(res.shin_z, 0.0)
        self.assertEqual(res.fallback_chain, [])

    def test_t4_o2_b365_pair(self):
        res = M.ou25_prediction({"B365": {">2.5": 1.90, "<2.5": 1.95}})
        self.assertEqual(res.method_id, "O2")
        self.assertAlmostEqual(sum(res.probabilities), 1.0, places=9)

    def test_n6_invalid_odds_drop_book(self):
        res = M.ftr_prediction({
            "B365": {"H": 2.10, "D": 3.50, "A": 3.60},
            "BAD": {"H": 0.5, "D": 3.5, "A": 3.6},          # odds <= 1.0
            "NAN": {"H": float("nan"), "D": 3.5, "A": 3.6},  # non-finite
            "MIS": {"H": 2.0, "D": 3.5},                     # missing leg
        })
        self.assertEqual(res.method_id, "M2")  # only one clean book remains -> fallback
        self.assertEqual(res.books_used, ["B365"])
        self.assertEqual(sorted(res.dropped_books), ["BAD", "MIS", "NAN"])

    def test_n6_all_books_invalid_returns_none(self):
        self.assertIsNone(M.ftr_prediction({"BAD": {"H": 0.5, "D": 3.5, "A": 3.6}}))
        self.assertIsNone(M.ou25_prediction({}))

    def test_n9_single_book_ftr_falls_back_to_m2(self):
        res = M.ftr_prediction({"B365": {"H": 2.10, "D": 3.50, "A": 3.60}})
        self.assertEqual(res.method_id, "M2")
        self.assertEqual(res.fallback_chain, ["M4->M2: single book"])

    def test_ou25_fallback_o4_then_single(self):
        res = M.ou25_prediction({"PS": {">2.5": 1.80, "<2.5": 2.05},
                                 "GB": {">2.5": 1.85, "<2.5": 2.00}})
        self.assertEqual(res.method_id, "O4")
        self.assertEqual(res.fallback_chain, ["O2->O4: B365 pair missing"])
        single = M.ou25_prediction({"PS": {">2.5": 1.80, "<2.5": 2.05}})
        self.assertIn("single-book Shin", single.fallback_chain[-1])

    def test_dispersion_and_entropy(self):
        disp = M.book_dispersion_max({"B365": {"H": 2.0, "D": 3.5, "A": 4.0},
                                      "VC": {"H": 2.2, "D": 3.5, "A": 4.2}},
                                     M.FTR_LEGS)
        self.assertGreater(disp, 0.0)
        self.assertAlmostEqual(M.entropy_bits([1 / 3, 1 / 3, 1 / 3]),
                               np.log2(3), places=12)


if __name__ == "__main__":
    unittest.main()
