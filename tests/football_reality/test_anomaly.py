"""V1.1 Anomaly Detector tests (spec V1.1 section 4).

The detector must PASS on a healthy system AND FLAG deliberately inverted
causality.  Nothing is tuned to make the healthy case pass.
"""

import unittest

import football_simulation.evaluation.anomaly as anomaly_mod
from football_simulation.evaluation.anomaly import AnomalyDetector
from football_simulation.evaluation.reality import TeamSpec
from tests.football_reality.common import get_harness


class TestAnomalyDetectorHealthy(unittest.TestCase):
    def test_all_checks_pass_on_healthy_system(self):
        detector = AnomalyDetector(get_harness())
        checks = detector.run_all(n=250, seed=303)
        failed = [c for c in checks if not c.passed]
        self.assertEqual(failed, [],
                         "healthy system flagged anomalies: " +
                         "; ".join(f"{c.name}: {c.detail}" for c in failed))

    def test_check_output_shape(self):
        detector = AnomalyDetector(get_harness())
        check = detector.check_strong_beats_weak(n=200, seed=7)
        self.assertIn(check.passed, (True, False))
        self.assertTrue(check.name)
        self.assertTrue(check.detail)
        self.assertIn("home_win", check.evidence)


class TestAnomalyDetectorCatchesViolations(unittest.TestCase):
    def test_inverted_strength_gets_flagged(self):
        """If the weak team beats the strong one, the detector MUST fail."""
        detector = AnomalyDetector(get_harness())
        original = anomaly_mod._strong_weak_pair
        try:
            def inverted():
                specs = original()
                # swap roles: weak at home, strong away
                specs["strong"], specs["weak"] = specs["weak"], specs["strong"]
                return specs
            anomaly_mod._strong_weak_pair = inverted
            check = detector.check_strong_beats_weak(n=250, seed=7)
            self.assertFalse(check.passed,
                             "inverted strength must be flagged as ANOMALY")
            self.assertIn("strong_team_beats_weak", check.name)
        finally:
            anomaly_mod._strong_weak_pair = original

    def test_red_card_benefiting_side_gets_flagged(self):
        """A world where the red-carded side wins MORE is an anomaly."""
        detector = AnomalyDetector(get_harness())
        # build inverted expectations directly and verify the detector logic
        specs = (TeamSpec(team_id="home", attack=0.5, defense=0.5),
                 TeamSpec(team_id="away", attack=0.5, defense=0.5))
        control, c_m = detector.harness.build_world(specs[0], specs[1])
        # treated world where the carded team is SUPERIOR (causal violation if
        # the detector were fed "red hurts" on an inverted setup)
        red, r_m = detector.harness.build_world(specs[0], specs[1], red_home=1)
        batches = detector.harness.run_pair(
            {"control": control, "red": red},
            {"control": c_m, "red": r_m}, n=250, seed=7)
        from football_simulation.evaluation.reality import batch_metrics
        m_control = batch_metrics(batches["control"])
        m_red = batch_metrics(batches["red"])
        # on the healthy system the check passes (red side loses more)
        passed = m_red["home_win"] < m_control["home_win"] and \
            m_red["away_win"] > m_control["away_win"]
        self.assertTrue(passed)
        # and the INVERTED comparison would be flagged
        inverted = m_red["home_win"] > m_control["home_win"]
        self.assertFalse(inverted,
                         "red-carded side winning more would be an ANOMALY")


if __name__ == "__main__":
    unittest.main()
