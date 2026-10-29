"""Rule Engine.

Reads knowledge rules -> evaluates conditions against a context object ->
computes effects -> returns concrete ``StateModifier`` records.

The context is normally a ``WorldState``, but tactical pattern rules are
evaluated against a ``{home_style, away_style}`` matchup context instead.
Football knowledge is never hardcoded in agent code: agents *may* call the
rule engine (or consume its modifiers), and the knowledge base can grow and be
re-validated without code changes (spec sections 64/65).
"""

from __future__ import annotations

import operator
from typing import Any, List, Optional

from football_simulation.models.base import ensure_range
from football_simulation.models.knowledge import (
    KnowledgeBase,
    KnowledgeRule,
    RuleCondition,
    StateModifier,
)
from football_simulation.models.world import WorldState

_OPS: dict = {
    "eq": operator.eq,
    "ne": operator.ne,
    "gt": operator.gt,
    "gte": operator.ge,
    "lt": operator.lt,
    "lte": operator.le,
}


class RuleEngine:
    """Evaluates a KnowledgeBase against contexts (WorldState or dict)."""

    # Pseudo-fields computed from a WorldState that rules may reference.
    COMPUTED_FIELDS = {
        "minute": lambda ws: ws.minute_float(),
        "goal_diff_home": lambda ws: ws.score_home - ws.score_away,
        "goal_diff_away": lambda ws: ws.score_away - ws.score_home,
        "mentality_home": lambda ws: ws.mentality(ws.home_tactical_state.side).value,
        "mentality_away": lambda ws: ws.mentality(ws.away_tactical_state.side).value,
        "players_on_pitch_home": lambda ws: ws.players_on_pitch(ws.home_tactical_state.side),
        "players_on_pitch_away": lambda ws: ws.players_on_pitch(ws.away_tactical_state.side),
        "is_second_half": lambda ws: 1.0 if ws.current_minute >= 45 else 0.0,
        "is_late_game": lambda ws: 1.0 if ws.current_minute >= 75 else 0.0,
        "total_goals": lambda ws: ws.score_home + ws.score_away,
    }

    def __init__(self, knowledge_base: KnowledgeBase):
        self.kb = knowledge_base

    # ------------------------------------------------------------------
    # Field resolution
    # ------------------------------------------------------------------
    def resolve_field(self, context: Any, field: str) -> Any:
        """Resolve a dotted field path (or computed pseudo-field) on a context."""
        if isinstance(context, WorldState) and field in self.COMPUTED_FIELDS:
            return self.COMPUTED_FIELDS[field](context)
        value: Any = context
        for part in field.split("."):
            if isinstance(value, dict):
                value = value[part]
            else:
                value = getattr(value, part)
        if hasattr(value, "value") and not isinstance(value, (int, float, str, bool, list, dict)):
            value = value.value  # enums -> primitive
        return value

    def resolve_path(self, context: Any, path: str) -> tuple:
        """Resolve a path for *modification* (returns the parent object and attr)."""
        parts = path.split(".")
        obj: Any = context
        for part in parts[:-1]:
            obj = obj[part] if isinstance(obj, dict) else getattr(obj, part)
        return obj, parts[-1]

    # ------------------------------------------------------------------
    # Condition evaluation
    # ------------------------------------------------------------------
    def evaluate_condition(self, cond: RuleCondition, context: Any) -> bool:
        if cond.all is not None:
            return all(self.evaluate_condition(c, context) for c in cond.all)
        if cond.any is not None:
            return any(self.evaluate_condition(c, context) for c in cond.any)
        if cond.not_ is not None:
            return not self.evaluate_condition(cond.not_, context)
        if cond.field is None or cond.op is None:
            return False
        actual = self.resolve_field(context, cond.field)
        return self._compare(actual, cond.op, cond.value)

    def _compare(self, actual: Any, op: str, expected: Any) -> bool:
        if op in ("known", "unknown"):
            is_known = actual is not None and actual != "unknown"
            return is_known if op == "known" else not is_known
        if op == "in":
            if isinstance(expected, str):
                expected = [expected]
            return actual in expected
        if op == "contains":
            if isinstance(actual, (list, tuple)):
                return expected in actual
            if isinstance(actual, str):
                return str(expected) in actual
            return False
        fn = _OPS.get(op)
        if fn is None:
            raise ValueError(f"Unknown condition op: {op!r}")
        try:
            if isinstance(actual, str) and not isinstance(expected, str):
                return fn(actual, str(expected))
            return fn(actual, expected)
        except TypeError:
            return False

    # ------------------------------------------------------------------
    # Rule application
    # ------------------------------------------------------------------
    def apply(self, context: Any, category: Optional[str] = None) -> List[StateModifier]:
        """Evaluate all active rules and return the modifiers for the ones that fire."""
        modifiers: List[StateModifier] = []
        for rule in self.kb.active_rules(category):
            try:
                if not self.evaluate_condition(rule.condition, context):
                    continue
                for effect in rule.effects:
                    modifiers.append(self._compute_effect(context, rule, effect))
            except (KeyError, AttributeError, TypeError, ValueError):
                # A rule referencing a field that does not exist in this context
                # shape must never crash the pipeline - skip it.
                continue
        return modifiers

    def _compute_effect(self, context: Any, rule: KnowledgeRule, effect: Any) -> StateModifier:
        obj, attr = self.resolve_path(context, effect.target)
        before = float(getattr(obj, attr) if not isinstance(obj, dict) else obj[attr])
        after = self._apply_op(before, effect.op, effect.value)
        return StateModifier(
            rule_id=rule.rule_id,
            rule_name=rule.name,
            target=effect.target,
            op=effect.op,
            value=float(effect.value),
            before=before,
            after=after,
            confidence=float(effect.confidence),
            reason=effect.reason,
        )

    @staticmethod
    def _apply_op(before: float, op: str, value: float) -> float:
        if op == "add":
            return before + value
        if op == "multiply":
            return before * value
        if op == "set":
            return value
        if op == "clamp01":
            return ensure_range(before + value)
        raise ValueError(f"Unknown effect op: {op!r}")

    # ------------------------------------------------------------------
    # Idempotent state application (used by the state machine)
    # ------------------------------------------------------------------
    def apply_state(self, world: WorldState, category: Optional[str] = None):
        """Evaluate rules against a WorldState exactly-once per condition edge.

        State-describing rules (e.g. "down a man -> chance creation x 0.68")
        must not re-fire on every subsequent event while their condition keeps
        holding, or multiplicative effects would compound.  ``world.rule_conditions``
        tracks the last evaluated truth value per rule; a rule fires only when
        its condition transitions False -> True.

        Returns (new_world, modifiers).
        """
        signatures: Dict[str, bool] = dict(world.rule_conditions)
        modifiers: List[StateModifier] = []
        for rule in self.kb.active_rules(category):
            try:
                cond_true = self.evaluate_condition(rule.condition, world)
            except (KeyError, AttributeError, TypeError, ValueError):
                continue
            previously_holding = signatures.get(rule.rule_id, False)
            signatures[rule.rule_id] = cond_true
            if not cond_true or previously_holding:
                continue
            for effect in rule.effects:
                modifiers.append(self._compute_effect(world, rule, effect))
        updated = self.apply_modifiers(world, modifiers)
        if signatures != world.rule_conditions:
            updated = updated.evolution_snapshot(rule_conditions=signatures)
        return updated, modifiers

    # ------------------------------------------------------------------
    # Applying modifiers back onto a context
    # ------------------------------------------------------------------
    def apply_modifiers(self, context: Any, modifiers: List[StateModifier], copy: bool = True) -> Any:
        """Return a new context (version bumped once when it is a WorldState)
        with modifiers applied.  Multiple modifiers on the same field compose
        in order.

        Nested attribute paths are updated copy-on-write so shared nested
        models (from shallow WorldState copies) are NEVER mutated in place.
        """
        import copy as _copy

        if isinstance(context, WorldState):
            updated = context.model_copy(deep=False)
        else:
            updated = _copy.deepcopy(context) if copy else context
        for mod in modifiers:
            self._set_path(updated, mod.target, mod.after)
        if isinstance(updated, WorldState):
            updated.state_version = context.state_version + 1
        return updated

    @staticmethod
    def _set_path(context: Any, path: str, value: float) -> None:
        """Set a dotted path with copy-on-write along attribute chains."""
        parts = path.split(".")
        current = context
        for part in parts[:-1]:
            if isinstance(current, dict):
                current = current[part]
                continue
            child = getattr(current, part)
            if hasattr(child, "model_copy"):
                child = child.model_copy(deep=False)
                setattr(current, part, child)
                current = child
            else:
                current = child
        last = parts[-1]
        if isinstance(current, dict):
            current[last] = value
        else:
            setattr(current, last, value)
