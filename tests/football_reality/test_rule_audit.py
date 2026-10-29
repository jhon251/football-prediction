"""V1.1 Rule audit & evidence system tests (spec V1.1 sections 6/7)."""

import unittest

from football_simulation.evaluation.rule_audit import (
    RuleAuditEntry,
    audit_rules,
    rule_counts,
)
from football_simulation.knowledge import load_all_knowledge
from football_simulation.models.knowledge import KnowledgeRule


class TestRuleAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.knowledge = load_all_knowledge()
        cls.entries = audit_rules(cls.knowledge)

    def test_all_35_rules_audited(self):
        total = len(self.knowledge["rules"].rules) + len(self.knowledge["tactical_patterns"].rules)
        self.assertEqual(total, 35)
        self.assertEqual(len(self.entries), 35)

    def test_audit_entry_shape(self):
        for entry in self.entries:
            self.assertTrue(entry.rule_id)
            self.assertTrue(entry.statement)
            self.assertTrue(entry.causal_direction)
            self.assertIn(entry.risk_of_overfitting, ("low", "medium", "high"))
            self.assertTrue(entry.needs_real_data_validation,
                            f"{entry.rule_id} must wait for real data validation")
            self.assertTrue(entry.implemented)

    def test_nothing_claims_validation(self):
        counts = rule_counts(self.entries)
        self.assertEqual(counts["validated"], 0,
                         "no rule may claim VALIDATED without real evidence")
        self.assertEqual(counts["tentative"], 35)
        self.assertEqual(counts["assumption"], 35,
                         "every bundled rule is a development-time assumption")

    def test_unassessed_rules_flagged(self):
        # every rule id in the packs must have a curated annotation
        known = {e.rule_id for e in self.entries}
        for pack in (self.knowledge["rules"].rules,
                     self.knowledge["tactical_patterns"].rules):
            for rule in pack:
                self.assertIn(rule.rule_id, known)


class TestRuleEvidenceFields(unittest.TestCase):
    def test_evidence_fields_exist_and_are_optional(self):
        rule = KnowledgeRule.model_validate({
            "rule_id": "r-evidence", "name": "evidence test",
            "source_type": "historical_data", "verified_matches": 1250,
            "success_rate": 0.68, "counter_examples": 90,
            "condition": {"field": "score_home", "op": "eq", "value": 0},
            "effects": [{"target": "momentum_home", "op": "add", "value": 0.1}],
        })
        self.assertEqual(rule.source_type, "historical_data")
        self.assertEqual(rule.verified_matches, 1250)
        self.assertEqual(rule.success_rate, 0.68)
        self.assertEqual(rule.counter_examples, 90)

    def test_default_source_type_is_assumption(self):
        rule = KnowledgeRule.model_validate({
            "rule_id": "r-default", "name": "default source",
            "condition": {"field": "score_home", "op": "eq", "value": 0},
            "effects": [],
        })
        self.assertEqual(rule.source_type, "assumption")
        self.assertIsNone(rule.success_rate)


if __name__ == "__main__":
    unittest.main()
