"""V1.2 runner (walk-forward), experiment registry, and historical provider tests."""

import unittest
from pathlib import Path

from football_simulation.backtest.experiments import (
    ExperimentRegistry,
    code_fingerprint,
    data_version,
    git_commit,
    knowledge_version,
    parameter_version,
)
from football_simulation.backtest.metrics import model_comparison
from football_simulation.backtest.runner import WalkForwardBacktester
from football_simulation.data.historical.provider import HistoricalDataProvider
from football_simulation.data.historical.snapshot import SnapshotBuilder
from football_simulation.data.provider import FutureDataError
from tests.backtest.helpers import get_dataset, slice_season


class TestHistoricalProvider(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = get_dataset()
        match = cls.dataset.matches_in_season("2023-24")[5]
        builder = SnapshotBuilder(cls.dataset.matches, strict=True)
        cls.snapshot = builder.build(match)
        cls.provider = HistoricalDataProvider(cls.dataset, cls.snapshot)

    def test_post_match_methods_always_raise(self):
        with self.assertRaises(FutureDataError):
            self.provider.get_match_result("x")
        with self.assertRaises(FutureDataError):
            self.provider.get_event_data("x")

    def test_unknown_data_reported_honestly(self):
        self.assertEqual(self.provider.get_player_data(self.snapshot.home_team), [])
        self.assertFalse(self.provider.get_weather("m", "v").known)
        self.assertEqual(self.provider.get_injury(self.snapshot.home_team, self.snapshot.kickoff), [])

    def test_data_quality_reflects_unknowns(self):
        dq = self.provider.data_quality(self.provider.get_match_request(self.snapshot.match_id))
        self.assertGreater(len(dq.unknowns), 3)
        self.assertLessEqual(dq.completeness, 1.0)

    def test_team_profile_derived_from_past_only(self):
        profile = self.provider.get_team_data(self.snapshot.home_team)
        self.assertTrue(0.0 < profile.attack_strength <= 1.0)
        self.assertGreaterEqual(profile.elo_rating, 1400.0)

    def test_history_strictly_before_kickoff(self):
        history = self.provider.get_match_history(
            self.snapshot.home_team, "premier_league", "x", self.snapshot.kickoff)
        for entry in history.entries:
            self.assertLess(entry.date, self.snapshot.kickoff)

    def test_director_runs_on_unknown_data(self):
        """Full pipeline must not crash with NO_SIGNAL inputs."""
        from football_simulation.agents.director import DirectorAgent, DirectorConfig
        director = DirectorAgent(self.provider, DirectorConfig(simulation_runs=60, seed=7))
        report = director.analyze(self.snapshot.match_id)
        self.assertAlmostEqual(
            report.result_probability.home_win + report.result_probability.draw
            + report.result_probability.away_win, 1.0, places=3)
        # the NO_SIGNAL path is visible in the trace
        trace_text = " ".join(step.get("summary", "") for step in report.trace)
        self.assertIn("NO_SIGNAL", trace_text)


class TestWalkForwardRunner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = get_dataset()

    def test_small_walk_forward_run(self):
        import shutil
        import uuid
        from football_simulation.data.historical.etl import HistoricalDataset
        tmp = Path(__file__).resolve().parents[2] / "tests" / f".tmp_wf_{uuid.uuid4().hex[:8]}"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            targets = self.dataset.matches_in_season("2023-24")[:6]
            # run dataset = full history before the last target + the targets
            history = [m for m in self.dataset.matches if m.date < targets[-1].date]
            combined = {m.match_id: m for m in history + targets}
            run_dataset = HistoricalDataset(list(combined.values()), name="mini")
            runner = WalkForwardBacktester(
                run_dataset, runs=60, seed=3, include_system=True, cache_dir=tmp)
            records = runner.run_season("2023-24", resume=False)
            self.assertEqual(len(records), 6)
            for record in records:
                self.assertIn("random", record.predictions)
                self.assertIn("full_system", record.predictions)
                pred = record.predictions["full_system"]
                self.assertEqual(pred.validate_probabilities(), [])
            comparison = model_comparison(records)
            self.assertIn("full_system", comparison)
            self.assertIn("elo", comparison)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_cache_resume(self):
        import shutil
        import uuid
        tmp = Path(__file__).resolve().parents[2] / "tests" / f".tmp_wf2_{uuid.uuid4().hex[:8]}"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            from football_simulation.data.historical.etl import HistoricalDataset
            targets = self.dataset.matches_in_season("2023-24")[:4]
            history = [m for m in self.dataset.matches if m.date < targets[-1].date]
            combined = {m.match_id: m for m in history + targets}
            run_dataset = HistoricalDataset(list(combined.values()), name="mini")
            runner = WalkForwardBacktester(run_dataset, runs=60, seed=3,
                                           include_system=False, cache_dir=tmp)
            records_a = runner.run_season("2023-24", resume=False)
            records_b = runner.run_season("2023-24", resume=True)
            self.assertEqual([r.match_id for r in records_a],
                             [r.match_id for r in records_b])
            a = records_a[0].predictions["elo"].home_win
            b = records_b[0].predictions["elo"].home_win
            self.assertEqual(a, b)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestExperimentRegistry(unittest.TestCase):
    def test_registry_roundtrip(self):
        import shutil
        import uuid
        tmp = Path(__file__).resolve().parents[2] / "tests" / f".tmp_exp_{uuid.uuid4().hex[:8]}"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            registry = ExperimentRegistry(tmp / "registry.jsonl")
            entry = registry.record(
                data_version="dv", random_seed=1, train_period="t", test_period="p",
                models=["full_system"], matches_evaluated=10,
                metrics={"full_system": {"brier": 0.6}}, synthetic_data=True,
                notes=["test"])
            self.assertTrue(entry.experiment_id)
            listed = registry.list()
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0].matches_evaluated, 10)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_fingerprints_present(self):
        self.assertTrue(code_fingerprint())
        self.assertTrue(knowledge_version())
        self.assertTrue(parameter_version())
        self.assertIsInstance(git_commit(), str)


if __name__ == "__main__":
    unittest.main()
