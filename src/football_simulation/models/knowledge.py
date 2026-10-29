"""Knowledge layer models: KnowledgeRule, predicate conditions, effects.

Football knowledge is NOT hardcoded in the source: it lives in versioned,
status-tagged rules that the RuleEngine evaluates against the WorldState.
Unverified knowledge is never treated as fact.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from football_simulation.models.base import KnowledgeStatus, VersionedModel, new_id, utc_now


class RuleCondition(BaseModel):
    """Predicate tree evaluated by the RuleEngine.

    Leaf:        {"field": "score_home", "op": "gt", "value": 1}
    Combinators: {"all": [...]}, {"any": [...]}, {"not": {...}}

    Ops: eq, ne, gt, gte, lt, lte, in, contains, known, unknown
    """

    model_config = ConfigDict(extra="forbid")

    all: Optional[List["RuleCondition"]] = None
    any: Optional[List["RuleCondition"]] = None
    not_: Optional["RuleCondition"] = Field(default=None, alias="not")
    field: Optional[str] = None
    op: Optional[str] = None
    value: Optional[Any] = None


class RuleEffect(BaseModel):
    """One effect a rule applies to a WorldState field when its condition holds.

    ``op``: add | multiply | set | clamp01
    """

    model_config = ConfigDict(extra="forbid")

    target: str
    op: str = "add"
    value: float = 0.0
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = ""


class KnowledgeRule(VersionedModel):
    """A single piece of football knowledge with provenance and lifecycle.

    Evidence fields (spec V1.1 section 7): every rule can later accumulate
    verified match counts, observed success rates and counter-examples.
    """

    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(default_factory=new_id)
    name: str
    category: str = Field(
        default="rules",
        description="rules | principles | tactical_patterns | coach_patterns | "
        "team_patterns | player_patterns | competition_patterns | referee_patterns",
    )
    description: str = ""
    status: KnowledgeStatus = KnowledgeStatus.TENTATIVE
    source: str = "internal_default"
    source_type: str = Field(
        default="assumption",
        description="assumption | internal_derivation | literature | historical_data",
    )
    created_at: datetime = Field(default_factory=utc_now)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence_count: int = 0
    verified_matches: int = Field(default=0, description="Matches this rule has been checked against.")
    success_rate: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
        description="Observed agreement rate across verified matches (None = never measured).",
    )
    counter_examples: int = Field(default=0, description="Verified matches contradicting the rule.")
    last_verified_at: Optional[datetime] = None
    condition: RuleCondition = Field(default_factory=RuleCondition)
    effects: List[RuleEffect] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    active: bool = True


class StateModifier(BaseModel):
    """A concrete, applied rule effect (traceable: before -> after)."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    rule_name: str
    target: str
    op: str
    value: float
    before: float
    after: float
    confidence: float
    reason: str


class KnowledgeBase(BaseModel):
    """Versioned collection of knowledge rules."""

    model_config = ConfigDict(extra="forbid")

    kb_id: str = Field(default_factory=new_id)
    name: str = "default"
    version: int = 1
    rules: List[KnowledgeRule] = Field(default_factory=list)

    def active_rules(self, category: Optional[str] = None) -> List[KnowledgeRule]:
        rules = [r for r in self.rules if r.active and r.status != KnowledgeStatus.DEPRECATED]
        if category:
            rules = [r for r in rules if r.category == category]
        return rules

    def by_id(self, rule_id: str) -> Optional[KnowledgeRule]:
        for rule in self.rules:
            if rule.rule_id == rule_id:
                return rule
        return None

    def add_rule(self, rule: KnowledgeRule) -> None:
        if self.by_id(rule.rule_id) is not None:
            raise ValueError(f"Duplicate rule id: {rule.rule_id}")
        self.rules.append(rule)

    def deprecate(self, rule_id: str, reason: str = "") -> None:
        rule = self.by_id(rule_id)
        if rule is None:
            raise KeyError(rule_id)
        rule.status = KnowledgeStatus.DEPRECATED
        rule.active = False
        if reason:
            rule.description = f"{rule.description} [DEPRECATED: {reason}]"
