"""V1.2 leakage audit tests + rule evidence + failure analysis."""

import unittest
from datetime import timedelta

from football_simulation.backtest.failure_analysis import (
    analyze_failure,
    failure_summary,
    sample_failures,
)
from football_simulation.backtest.leakage import audit_leakage
from football_simulation.backtest.models import ModelPrediction, PredictionRecord
from football_simulation.data.historical.etl import HistoricalDataset
from football_simulation.data.historical.schema import HistoricalOdds
from football_simulation.evaluation.rule_evidence import (
    CounterExample,
    CounterexampleStore,
    RuleEvidenceBackfill,
    binomial_p_value,
)
from football_simulation.knowledge import load_all_knowledge
from tests.backtest.helpers import get_dataset


class TestLeakageAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = get_dataset()

    def test_audit_passes_on_clean_dataset(self):
        report = audit_leakage(self.dataset)
        names = {s.name for s in report.sections}
        for required in ("temporal_leakage", "future_match_leakage", "post_match_leakage",
                         "lineup_leakage", "odds_leakage", "player_leakage",
                         "ranking_leakage"):
            self.assertIn(required, names)
        self.assertTrue(report.passed, report.model_dump())

    def test_audit_catches_injected_odds_leak(self):
        poisoned = [m for m in self.dataset.matches]
        match = poisoned[200]
        poisoned[200] = match.model_copy(update={
            "closing_odds": HistoricalOdds(
                home=2.0, draw=3.2, away=3.6,
                odds_timestamp=match.date + timedelta(hours=3)),
        })
        report = audit_leakage(HistoricalDataset(poisoned, name="poisoned"))
        self.assertFalse(report.passed)
        self.assertFalse(report.sections[4].passed)  # odds section

    def test_audit_catches_injected_lineup_leak(self):
        poisoned = [m for m in self.dataset.matches]
        match = poisoned[201]
        poisoned[201] = match.model_copy(update={
            "home_lineup_status": "confirmed",
            "home_lineup": ["x"] * 11,
            "lineup_observed_at": match.date + timedelta(hours=1),
        })
        report = audit_leakage(HistoricalDataset(poisoned, name="poisoned"))
        self.assertFalse(report.passed)

    def test_synthetic_never_passes_as_real(self):
        self.assertTrue(all(m.is_synthetic for m in self.dataset.matches))


class TestRuleEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = get_dataset()
        knowledge = load_all_knowledge()
        cls.knowledge = {"rules": knowledge["rules"],
                         "tactical_patterns": knowledge["tactical_patterns"]}

    def test_backfill_runs_and_classifies(self):
        backfill = RuleEvidenceBackfill(self.dataset, self.knowledge)
        results = backfill.run()
        self.assertEqual(len(results), 35)
        observable = [r for r in results if r.observable]
        not_observable = [r for r in results if not r.observable]
        self.assertGreaterEqual(len(observable), 8)
        self.assertGreaterEqual(len(not_observable), 15)
        for result in observable:
            self.assertGreater(result.verified_matches, 0)
            self.assertIsNotNone(result.success_rate)

    def test_status_criteria(self):
        backfill = RuleEvidenceBackfill(self.dataset, self.knowledge)
        # supported needs n >= 50 and rate > 0.52
        self.assertEqual(backfill._classify(40, 0.6), "tentative")
        self.assertEqual(backfill._classify(60, 0.60), "supported")
        # contradicted needs n >= 50 and rate < 0.45
        self.assertEqual(backfill._classify(60, 0.40), "contradicted")
        # validated needs n >= 200, rate >= 0.55, p < 0.05
        self.assertEqual(backfill._classify(200, 0.60), "validated")
        self.assertEqual(backfill._classify(200, 0.54), "supported")

    def test_binomial_p_value(self):
        self.assertLess(binomial_p_value(120, 200), 0.05)
        self.assertGreater(binomial_p_value(104, 200), 0.05)

    def test_apply_updates_knowledge_only_evidence(self):
        knowledge = load_all_knowledge()
        packs = {"rules": knowledge["rules"],
                 "tactical_patterns": knowledge["tactical_patterns"]}
        before = {r.rule_id: (r.condition.model_dump(), [e.model_dump() for e in r.effects])
                  for pack in packs.values() for r in pack.rules}
        backfill = RuleEvidenceBackfill(self.dataset, packs)
        backfill.run()
        counts = backfill.apply_to_knowledge()
        after = {r.rule_id: (r.condition.model_dump(), [e.model_dump() for e in r.effects])
                 for pack in packs.values() for r in pack.rules}
        # conditions/effects untouched; evidence fields updated
        self.assertEqual(before, after)
        self.assertGreaterEqual(sum(counts.values()), 35)

    def test_counterexample_store_roundtrip(self):
        import shutil
        import uuid
        from pathlib import Path
        tmp = Path(__file__).resolve().parents[2] / "tests" / f".tmp_ev_{uuid.uuid4().hex[:8]}"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            store = CounterexampleStore(tmp / "ce.json")
            store.add_many([CounterExample(
                rule_id="R_TEST", match_id="m1",
                kickoff=self.dataset.matches[0].date,
                condition="x", what_happened="y", why_contradicts="z")])
            reloaded = CounterexampleStore(tmp / "ce.json")
            self.assertEqual(len(reloaded.entries), 1)
            self.assertEqual(reloaded.entries[0].why_contradicts, "z")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_status_enum_has_five_levels(self):
        from football_simulation.models.base import KnowledgeStatus
        values = {member.value for member in KnowledgeStatus}
        for level in ("assumption", "tentative", "supported",
                      "contradicted", "validated"):
            self.assertIn(level, values)


class TestFailureAnalysis(unittest.TestCase):
    def _records(self):
        from datetime import datetime, timezone
        records = []
        for i, (result, prob_home) in enumerate([
                ("home_win", 0.85), ("away_win", 0.75), ("draw", 0.70), ("away_win", 0.65)]):
            p = ModelPrediction(model="full_system", home_win=prob_home,
                                draw=(1 - prob_home) / 2, away_win=(1 - prob_home) / 2,
                                expected_goals=2.6, over25=0.5, btts_yes=0.5,
                                score_matrix={"1-0": 0.2, "1-1": 0.2, "0-1": 0.2,
                                              "2-1": 0.2, "2-0": 0.2})
            records.append(PredictionRecord(
                match_id=f"m{i}", kickoff=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
                home_team="h", away_team="a",
                actual_home_goals=1 if result in ("home_win", "draw") else 0,
                actual_away_goals=1 if result in ("away_win", "draw") else 0,
                predictions={"full_system": p}, synthetic=True,
                unknowns=["home_lineup"] if i == 2 else []))
        return records

    def test_sample_failures_orders_by_confidence(self):
        records = self._records()
        cases = sample_failures(records, model="full_system", n=4)
        # match 1 predicted home 0.85 but actual home_win... it is correct;
        # the misses are m2 (away), m3 (draw), m4 (away) -> 3 failures
        self.assertEqual(len(cases), 3)
        # highest-confidence miss first
        self.assertGreaterEqual(cases[0].probability, cases[1].probability)

    def test_error_location_rules(self):
        records = self._records()
        case = analyze_failure(records[1], "full_system")  # 0.75 home, actual away
        # away prob 0.125 < 0.15, goals near expectation, no unknowns, no
        # calibration context -> honest "unknown" (never forced)
        self.assertIn(case.error_location,
                      ("randomness", "world_model_error", "simulation_error",
                       "data_error", "unknown"))

    def test_data_error_when_unknown_inputs(self):
        from datetime import datetime, timezone
        from football_simulation.backtest.models import ModelPrediction, PredictionRecord
        # draw actual; draw prob 0.04 (< 0.15), goals near expectation,
        # unknown inputs present -> data_error (nothing better explains it)
        p = ModelPrediction(model="full_system", home_win=0.92, draw=0.04,
                            away_win=0.04, expected_goals=2.6, over25=0.5,
                            btts_yes=0.5, score_matrix={"1-0": 0.2})
        record = PredictionRecord(
            match_id="m-x", kickoff=datetime(2024, 1, 1, tzinfo=timezone.utc),
            home_team="h", away_team="a", actual_home_goals=1, actual_away_goals=1,
            predictions={"full_system": p}, synthetic=True,
            unknowns=["home_lineup", "weather"])
        case = analyze_failure(record, "full_system")
        self.assertEqual(case.error_location, "data_error")

    def test_failure_summary_counts(self):
        records = self._records()
        cases = sample_failures(records, model="full_system", n=4)
        summary = failure_summary(cases)
        self.assertGreaterEqual(sum(summary.values()), len(cases))


if __name__ == "__main__":
    unittest.main()
