"""V1.2 Real-Data Onboarding tests (E0.csv doctor + importer)."""

import unittest
from pathlib import Path

from football_simulation.data.historical.doctor import (
    field_kind,
    is_c_suffix,
    run_doctor,
)
from football_simulation.data.historical.etl import HistoricalDataset
from football_simulation.data.historical.profile import CsvProfile
from football_simulation.data.historical.source import CsvFootballDataCoUkSource

RAW = Path(__file__).resolve().parents[2] / "data" / "historical" / "raw" / "E0.csv"
CANONICAL = Path(__file__).resolve().parents[2] / "data" / "historical" / "epl_2025_26.json"


@unittest.skipUnless(RAW.exists(), "real E0.csv not present")
class TestRealDataDoctor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_doctor(str(RAW))

    def test_doctor_passes(self):
        self.assertTrue(self.result.passed, "\n".join(self.result.problems))
        self.assertIn("REAL DATA ONBOARDING PASS", self.result.render())

    def test_doctor_sections_present(self):
        names = [name for name, _, _ in self.result.sections]
        for required in ("schema", "missing data", "duplicate data", "date validity",
                         "team consistency", "odds validity", "temporal validity",
                         "leakage risks", "synthetic flag", "real data status"):
            self.assertIn(required, names)

    def test_profile_numbers(self):
        profile = CsvProfile(RAW)
        self.assertEqual(len(profile.rows), 380)
        self.assertEqual(len(profile.fieldnames), 132)
        self.assertEqual(profile.teams()["distinct_teams"], 20)
        self.assertEqual(profile.duplicates(), [])
        self.assertEqual(profile.temporal_validity(), [])
        core_missing = {f: n for f, n in profile.missing_by_column().items()
                        if f in ("Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG")}
        self.assertEqual(core_missing, {})

    def test_result_fields_never_pre_match(self):
        for field in ("FTHG", "FTAG", "HTHG", "HTAG", "HS", "AS", "HY", "AY", "HR", "AR"):
            kind = field_kind(field)
            self.assertEqual(kind, "result", field)

    def test_c_suffix_classification(self):
        profile = CsvProfile(RAW)
        c_fields = [f for f in profile.fieldnames if is_c_suffix(f)]
        # 33 1X2 + 10 O/U + 11 AH
        self.assertEqual(len(c_fields), 54)
        for field in ("B365CH", "B365CD", "B365CA", "B365C>2.5", "AHCh", "BFECAHA"):
            self.assertIn(field, c_fields)

    def test_odds_validity(self):
        profile = CsvProfile(RAW)
        odds = profile.odds_validity()
        self.assertEqual(odds["problem_count"], 0)


@unittest.skipUnless(CANONICAL.exists(), "canonical real dataset not built")
class TestRealDataImport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = HistoricalDataset.load(CANONICAL)

    def test_dataset_is_real(self):
        self.assertEqual(len(self.dataset.matches), 380)
        self.assertTrue(all(not m.is_synthetic for m in self.dataset.matches))
        self.assertEqual(self.dataset.validate(), [])

    def test_closing_odds_convention(self):
        match = self.dataset.matches[0]
        self.assertIsNotNone(match.closing_odds)
        self.assertEqual(match.closing_odds.bookmaker, "Avg")
        self.assertEqual(match.closing_odds.kind, "closing")
        # stamped at kickoff: closing-snapshot convention, pre-match usable
        self.assertLessEqual(match.closing_odds.odds_timestamp, match.date)
        # no verifiable opening snapshot exists -> stays None
        self.assertIsNone(match.opening_odds)

    def test_c_suffix_odds_kept_unknown(self):
        match = self.dataset.matches[0]
        unknown = {k: v for k, v in match.raw_odds.items()
                   if v.get("time_semantics") == "unknown_time_semantics"}
        self.assertEqual(len(unknown), 54)
        for field in ("B365CH", "B365CD", "B365CA", "AHCh"):
            self.assertIn(field, unknown)

    def test_corners_imported(self):
        match = self.dataset.matches[0]
        self.assertIsNotNone(match.home_corners)
        self.assertIsNotNone(match.away_corners)

    def test_leakage_audit_passes_on_real_data(self):
        from football_simulation.backtest.leakage import audit_leakage
        report = audit_leakage(self.dataset)
        self.assertTrue(report.passed, report.model_dump())


class TestDoctorOnPoisonedCopy(unittest.TestCase):
    def test_doctor_fails_on_duplicates(self):
        import shutil
        import tempfile
        import uuid
        tmp = Path(__file__).resolve().parents[2] / "tests" / f".tmp_doc_{uuid.uuid4().hex[:8]}"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            lines = RAW.read_text(encoding="utf-8-sig").splitlines()
            poisoned = Path(tmp) / "poisoned.csv"
            # duplicate the first data row
            poisoned.write_text("\n".join([lines[0], lines[1], lines[1]]),
                                encoding="utf-8")
            result = run_doctor(str(poisoned))
            self.assertFalse(result.passed)
            self.assertTrue(any("duplicate" in p for p in result.problems))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestImporterFieldFamilies(unittest.TestCase):
    def test_import_roundtrip_header(self):
        source = CsvFootballDataCoUkSource()
        text = RAW.read_text(encoding="utf-8-sig")
        matches = source.parse(text, season="2025-26", source_label="test")
        self.assertEqual(len(matches), 380)
        first = matches[0]
        # plain columns labeled closing convention
        plain = {k: v for k, v in first.raw_odds.items()
                 if v.get("time_semantics") == "closing_convention_pre_kickoff"}
        c_suffix = {k: v for k, v in first.raw_odds.items()
                    if v.get("time_semantics") == "unknown_time_semantics"}
        self.assertEqual(len(c_suffix), 54)
        self.assertGreater(len(plain), 40)
        self.assertIn("AvgH", plain)


if __name__ == "__main__":
    unittest.main()
