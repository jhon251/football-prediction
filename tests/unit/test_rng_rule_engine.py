"""Unit tests: RNG reproducibility & rule engine."""

import unittest

from football_simulation.core.rule_engine import RuleEngine
from football_simulation.core.rng import SeedableRNG
from football_simulation.knowledge import load_all_knowledge
from football_simulation.models.knowledge import KnowledgeBase, KnowledgeRule, RuleCondition, RuleEffect
from football_simulation.models.world import WorldState


class TestRNG(unittest.TestCase):
    def test_reproducible(self):
        a = SeedableRNG(42).random(100)
        b = SeedableRNG(42).random(100)
        self.assertEqual(list(a), list(b))

    def test_different_seeds_differ(self):
        a = SeedableRNG(1).random(50)
        b = SeedableRNG(2).random(50)
        self.assertNotEqual(list(a), list(b))

    def test_spawn_stable_across_processes(self):
        # stable string hash - must not depend on PYTHONHASHSEED
        r1 = SeedableRNG(7).spawn("event_stream").random(20)
        r2 = SeedableRNG(7).spawn("event_stream").random(20)
        self.assertEqual(list(r1), list(r2))

    def test_derive_seed_deterministic(self):
        rng = SeedableRNG(12345)
        self.assertEqual(rng.derive_seed(0), SeedableRNG(12345).derive_seed(0))
        self.assertNotEqual(rng.derive_seed(0), rng.derive_seed(1))

    def test_choice_int(self):
        rng = SeedableRNG(3)
        for _ in range(100):
            idx = rng.choice(5)
            self.assertIn(idx, range(5))


class TestRuleEngine(unittest.TestCase):
    def setUp(self):
        self.knowledge = load_all_knowledge()
        self.engine = RuleEngine(self.knowledge["rules"])

    def test_default_pack_loads(self):
        self.assertGreater(len(self.knowledge["rules"].rules), 20)
        self.assertGreater(len(self.knowledge["tactical_patterns"].rules), 5)

    def test_condition_ops(self):
        world = WorldState(match_id="m1", score_home=1, current_minute=80)
        engine = self.engine
        self.assertTrue(engine.evaluate_condition(
            RuleCondition(field="score_home", op="gt", value=0), world))
        self.assertTrue(engine.evaluate_condition(
            RuleCondition(field="score_home", op="eq", value=1), world))
        self.assertFalse(engine.evaluate_condition(
            RuleCondition(field="score_home", op="lte", value=0), world))
        self.assertTrue(engine.evaluate_condition(
            RuleCondition(all=[
                RuleCondition(field="score_home", op="gt", value=0),
                RuleCondition(field="minute", op="gte", value=75),
            ]), world))

    def test_leading_rule_fires(self):
        world = WorldState(match_id="m1", score_home=1, current_minute=80)
        world.home_coach = __import__(
            "football_simulation.models.entities", fromlist=["CoachState"]
        ).CoachState(coach_id="c1", reaction_to_leading="defensive")
        mods = self.engine.apply(world)
        names = {m.rule_name for m in mods}
        self.assertIn("leading_team_tempo_moderation", names)

    def test_apply_modifiers_no_inplace_mutation(self):
        """Copy-on-write: applying modifiers must never mutate the input state."""
        world = WorldState(match_id="m1", score_home=1, current_minute=80)
        world.home_coach = __import__(
            "football_simulation.models.entities", fromlist=["CoachState"]
        ).CoachState(coach_id="c1", reaction_to_leading="defensive")
        before_pressing = world.home_tactical_state.pressing_intensity
        before_state = world.model_copy(deep=True)
        mods = self.engine.apply(world)
        updated = self.engine.apply_modifiers(world, mods)
        # input untouched
        self.assertEqual(world.home_tactical_state.pressing_intensity, before_pressing)
        self.assertEqual(world.model_dump(), before_state.model_dump())
        # output version bumped
        self.assertEqual(updated.state_version, world.state_version + 1)

    def test_deprecated_rules_excluded(self):
        kb = KnowledgeBase(rules=[
            KnowledgeRule(
                name="old_rule", status="deprecated", active=True,
                condition=RuleCondition(field="score_home", op="eq", value=0),
                effects=[RuleEffect(target="momentum_home", op="add", value=0.1)],
            )
        ])
        engine = RuleEngine(kb)
        mods = engine.apply(WorldState(match_id="m1"))
        self.assertEqual(mods, [])


if __name__ == "__main__":
    unittest.main()
