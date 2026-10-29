# -*- coding: utf-8 -*-
"""External-signal gating tests — spec §5 N7/N8 + candidate paths."""
import unittest
from datetime import datetime, timezone

from football_prediction import signals as S

KICKOFF = datetime(2026, 9, 20, 14, 0, tzinfo=timezone.utc)


def _sig(**kw):
    base = {"source": "understat", "namespace": "forward", "dq_status": "time_safe",
            "retrieved_at": "2026-09-18T20:30:00+00:00",
            "generated_at": None, "published_at": None}
    base.update(kw)
    return base


class TestSignalGate(unittest.TestCase):
    def test_time_safe_forward_is_candidate_not_validated(self):
        rec = S.gate_signal(_sig(), KICKOFF)
        self.assertEqual(rec["status"], "candidate")
        agg = S.gate_signals([_sig()], KICKOFF)
        self.assertEqual(agg["overall_status"], S.OVERALL_CANDIDATE)
        self.assertFalse(agg["signals_used_in_prediction"])

    def test_n7_retro_namespaces_rejected(self):
        for kw in ({"namespace": "dq_validation"},
                   {"namespace": "historical_retro"},
                   {"dq_status": "historical_retro"},
                   {"namespace": "forward", "dq_status": "window_late"}):
            rec = S.gate_signal(_sig(**kw), KICKOFF)
            self.assertEqual(rec["status"], "rejected", msg=str(kw))
        agg = S.gate_signals([_sig(namespace="dq_validation")], KICKOFF)
        self.assertEqual(agg["overall_status"], S.OVERALL_REJECTED)
        self.assertNotEqual(agg["overall_status"], S.OVERALL_VALIDATED)

    def test_n7_retrieved_after_kickoff_rejected(self):
        rec = S.gate_signal(_sig(retrieved_at="2026-09-20T15:00:00+00:00"), KICKOFF)
        self.assertEqual(rec["status"], "rejected")

    def test_n8_missing_timestamps_stay_unknown_never_inferred(self):
        rec = S.gate_signal(_sig(), KICKOFF)
        self.assertEqual(rec["generated_at_status"], "UNKNOWN")
        self.assertIsNone(rec["generated_at"])
        self.assertEqual(rec["published_at_status"], "UNKNOWN")
        # missing retrieved_at -> unknown, not rejected
        rec2 = S.gate_signal(_sig(retrieved_at=None), KICKOFF)
        self.assertEqual(rec2["status"], "unknown")

    def test_no_signals_not_available(self):
        agg = S.gate_signals(None, KICKOFF)
        self.assertEqual(agg["overall_status"], S.OVERALL_NOT_AVAILABLE)

    def test_time_safe_validated_unreachable_without_registry(self):
        """TIME_SAFE_VALIDATED requires validated_signal_registry.json (absent today)."""
        reg = S._load_validated_registry()
        self.assertEqual(reg, {})
        agg = S.gate_signals([_sig()], KICKOFF)
        self.assertNotEqual(agg["overall_status"], S.OVERALL_VALIDATED)


if __name__ == "__main__":
    unittest.main()
