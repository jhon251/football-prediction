# -*- coding: utf-8 -*-
"""End-to-end predictor tests — spec §5 T5 + N1-N6, N9, N10."""
import json
import tempfile
import unittest
from pathlib import Path

from football_prediction.predictor import predict_match

KICKOFF = "2026-09-20T14:00:00+00:00"
RETRIEVED = "2026-09-19T10:00:00+00:00"


def _inp(books=None, kickoff=KICKOFF, retrieved=RETRIEVED, context="preclosing",
         signals=None, **extra):
    raw = {
        "schema_version": "prediction_input.v1",
        "match": {"home_team": "Arsenal", "away_team": "Chelsea",
                  "league": "E0", "kickoff_utc": kickoff},
        "odds": {"context": context, "source": "test-feed",
                 "retrieved_at": retrieved,
                 "books": books if books is not None else {
                     "B365": {"H": 2.10, "D": 3.50, "A": 3.60, ">2.5": 1.90, "<2.5": 1.95},
                     "VC": {"H": 2.05, "D": 3.40, "A": 3.55, ">2.5": 1.88, "<2.5": 1.97},
                     "WH": {"H": 2.15, "D": 3.45, "A": 3.65, ">2.5": 1.92, "<2.5": 1.93},
                     "PS": {"H": 2.08, "D": 3.42, "A": 3.58, ">2.5": 1.89, "<2.5": 1.96}}},
        "external_signals": signals or [],
    }
    raw.update(extra)
    return raw


class TestHappyPath(unittest.TestCase):
    def test_t5_full_valid_prediction(self):
        out = predict_match(_inp())
        self.assertEqual(out["overall_status"], "VALID")
        self.assertEqual(out["ftr"]["status"], "VALID")
        self.assertEqual(out["ou25"]["status"], "VALID")
        self.assertEqual(out["ftr"]["method"]["method_id"], "M4")
        self.assertEqual(out["ou25"]["method"]["method_id"], "O2")
        self.assertAlmostEqual(sum(out["ftr"]["probabilities"].values()), 1.0, places=9)
        self.assertAlmostEqual(sum(out["ou25"]["probabilities"].values()), 1.0, places=9)
        self.assertEqual(out["data_quality"]["time_safe_status"], "TIME_SAFE")
        self.assertEqual(out["external_signals"]["overall_status"], "NOT_AVAILABLE")
        self.assertFalse(out["external_signals"]["signals_used_in_prediction"])
        self.assertIn("prediction_utc", out)
        self.assertIn("model_version", out)
        self.assertEqual(out["forbidden_use"][:22], "research prediction on")

    def test_candidate_signal_does_not_change_probabilities(self):
        """Invariant P3: signals change status fields, never probability fields."""
        sig = [{"source": "understat", "namespace": "forward", "dq_status": "time_safe",
                "retrieved_at": "2026-09-18T20:30:00+00:00",
                "generated_at": None, "published_at": None}]
        base = predict_match(_inp())
        with_sig = predict_match(_inp(signals=sig))
        self.assertEqual(base["ftr"]["probabilities"], with_sig["ftr"]["probabilities"])
        self.assertEqual(base["ou25"]["probabilities"], with_sig["ou25"]["probabilities"])
        self.assertEqual(with_sig["external_signals"]["overall_status"],
                         "AVAILABLE_NOT_VALIDATED")

    def test_schema_shape(self):
        out = predict_match(_inp())
        self.assertEqual(out["schema_version"], "prediction_output.v1")
        for key in ("ftr", "ou25", "market_data", "external_signals", "data_quality",
                    "uncertainty", "confidence", "frozen_dataset_provenance"):
            self.assertIn(key, out)


class TestNegativePaths(unittest.TestCase):
    def test_n1_no_odds_insufficient_data_no_probabilities(self):
        out = predict_match(_inp(books={}))
        self.assertEqual(out["overall_status"], "INSUFFICIENT_DATA")
        self.assertIsNone(out["ftr"]["probabilities"])
        self.assertIsNone(out["ou25"]["probabilities"])
        self.assertEqual(out["ftr"]["status"], "INSUFFICIENT_DATA")

    def test_n2_closing_context_rejected(self):
        out = predict_match(_inp(context="closing"))
        self.assertEqual(out["overall_status"], "REJECTED")

    def test_n3_csuffix_keys_dropped_not_used(self):
        books = {"B365C": {"H": 2.05, "D": 3.40, "A": 3.50},   # closing book family (B365+C)
                 "B365": {"H": 2.10, "D": 3.50, "A": 3.60, "CH": 1.95},  # closing leg
                 "VC": {"H": 2.05, "D": 3.40, "A": 3.55}}     # legitimate book ending in C
        out = predict_match(_inp(books=books))
        self.assertNotIn("B365C", out["ftr"]["method"]["books_used"])
        self.assertIn("VC", out["ftr"]["method"]["books_used"])  # VC must NOT be misflagged
        self.assertIn("B365", out["ftr"]["method"]["books_used"])
        self.assertIn("CH", out["market_data"]["csuffix_keys_dropped"][0])
        # B365C.{H,D,A} + B365.CH = 4 dropped entries
        self.assertEqual(out["data_quality"]["leakage_guards"]["csuffix_keys_dropped"], 4)
        self.assertEqual(sorted(out["ftr"]["method"]["books_used"]), ["B365", "VC"])

    def test_n4_label_field_rejected(self):
        raw = _inp()
        raw["match"]["fthg"] = 3  # attempt to smuggle a label
        out = predict_match(raw)
        self.assertEqual(out["overall_status"], "REJECTED")
        self.assertIn("fthg", " ".join(out["rejection_reasons"]))

    def test_n4b_top_level_label_rejected(self):
        raw = _inp()
        raw["label"] = "H"
        out = predict_match(raw)
        self.assertEqual(out["overall_status"], "REJECTED")

    def test_n5_retrieved_after_kickoff_rejected(self):
        out = predict_match(_inp(retrieved="2026-09-20T16:00:00+00:00"))
        self.assertEqual(out["overall_status"], "REJECTED")
        self.assertIsNone(out["ftr"]["probabilities"])

    def test_missing_retrieved_at_conditional_unknown_time_safe(self):
        out = predict_match(_inp(retrieved=None))
        self.assertEqual(out["data_quality"]["time_safe_status"], "UNKNOWN")
        self.assertEqual(out["overall_status"], "CONDITIONAL")

    def test_n6_nonfinite_and_low_odds(self):
        books = {"B365": {"H": float("nan"), "D": 3.5, "A": 3.6},
                 "VC": {"H": 0.9, "D": 3.4, "A": 3.55},
                 "WH": {"H": 2.15, "D": 3.45, "A": 3.65},
                 "PS": {"H": 2.08, "D": 3.42, "A": 3.58}}
        out = predict_match(_inp(books=books))
        self.assertEqual(out["ftr"]["method"]["books_used"], ["PS", "WH"])
        self.assertEqual(out["ftr"]["status"], "VALID")  # >=2 clean books remain

    def test_n9_single_book_downgrades_to_conditional(self):
        out = predict_match(_inp(books={"B365": {"H": 2.10, "D": 3.50, "A": 3.60,
                                                 ">2.5": 1.90, "<2.5": 1.95}}))
        self.assertEqual(out["ftr"]["method"]["method_id"], "M2")
        self.assertEqual(out["ftr"]["status"], "CONDITIONAL")
        self.assertEqual(out["overall_status"], "CONDITIONAL")
        self.assertTrue(out["ftr"]["method"]["fallback_chain"])

    def test_n10_frozen_fingerprint_drift_stops(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write("tampered\n")
            path = f.name
        try:
            out = predict_match(_inp(), frozen_path=Path(path))
            self.assertEqual(out["overall_status"], "STOP")
            self.assertIn("drift", out["stop_reason"].lower())
            self.assertIsNone(out["ftr"]["probabilities"])
        finally:
            Path(path).unlink()

    def test_schema_violation_rejected(self):
        raw = _inp()
        raw["schema_version"] = "unknown.v99"
        out = predict_match(raw)
        self.assertEqual(out["overall_status"], "REJECTED")
        self.assertTrue(out["rejection_reasons"])

    def test_bad_kickoff_rejected(self):
        out = predict_match(_inp(kickoff="not-a-date"))
        self.assertEqual(out["overall_status"], "REJECTED")

    def test_non_dict_input_rejected(self):
        out = predict_match([1, 2, 3])
        self.assertEqual(out["overall_status"], "REJECTED")

    def test_real_frozen_dataset_verifies_when_present(self):
        frozen = Path(__file__).resolve().parents[2] / "backtest_output" / "dataset_build" \
            / "freeze" / "1.1.0" / "baseline_dataset.jsonl"
        out = predict_match(_inp())
        if frozen.exists():
            self.assertTrue(out["frozen_dataset_provenance"]["verified"])
        else:
            self.assertFalse(out["frozen_dataset_provenance"]["verified"])


if __name__ == "__main__":
    unittest.main()
