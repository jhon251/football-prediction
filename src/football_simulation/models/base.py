"""Base domain types: enums, versioned models, agent results and opinions.

Everything in this module is deliberately dependency-light: it is the contract
every agent, the rule engine, the simulation engine and the data layer share.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


def utc_now() -> datetime:
    """UTC now (timezone aware)."""
    return datetime.now(timezone.utc)


def new_id(prefix: str = "") -> str:
    """Short stable id, optionally prefixed."""
    raw = uuid.uuid4().hex[:12]
    return f"{prefix}-{raw}" if prefix else raw


class Side(str, enum.Enum):
    """Which team an entity or event belongs to."""

    HOME = "home"
    AWAY = "away"

    def opponent(self) -> "Side":
        return Side.AWAY if self is Side.HOME else Side.HOME


class ConfidenceLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ImpactLevel(str, enum.Enum):
    """Environment / factor impact magnitude - never assume everything matters."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class KnowledgeStatus(str, enum.Enum):
    """Lifecycle of a knowledge rule.

    Unverified knowledge must never be treated as fact.  V1.2 adds the
    evidence-bearing levels: SUPPORTED (direction observed in real data but
    below the validation bar) and CONTRADICTED (observed against the rule).
    Only VALIDATED rules may be treated as established knowledge, and only
    after meeting the pre-defined statistical criteria.
    """

    ASSUMPTION = "assumption"
    UNVERIFIED = "unverified"
    TENTATIVE = "tentative"
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    VALIDATED = "validated"
    DEPRECATED = "deprecated"


class VersionedModel(BaseModel):
    """Base for every versioned domain object.

    All TeamState / PlayerState / CoachState / KnowledgeRule / Scenario /
    Prediction objects carry a version number so that future model versions
    can be compared against each other.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, description="Schema/model version of this object.")
    model_version: int = Field(default=1, description="Content version of this object.")


class AgentOpinion(BaseModel):
    """A single agent's structured opinion about one subject.

    The Director must NOT simply average opinions: each opinion carries its
    source, confidence, evidence and impact so that the Fusion Layer can weigh
    them appropriately.
    """

    model_config = ConfigDict(extra="forbid")

    opinion_id: str = Field(default_factory=new_id)
    agent_name: str
    subject: str = Field(description="What this opinion is about, e.g. 'home_attack_strength'.")
    value: float = Field(description="Numeric opinion value (unit depends on subject).")
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list)
    reasoning: str = ""
    impact: ImpactLevel = ImpactLevel.MEDIUM
    match_id: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)


class AgentResult(BaseModel, Generic[T]):
    """Standard result envelope returned by every agent.

    Agents are stateless: they receive inputs and return an AgentResult.
    """

    model_config = ConfigDict(extra="forbid")

    agent_name: str
    timestamp: datetime = Field(default_factory=utc_now)
    match_id: Optional[str] = None
    input_version: int = Field(description="Version of the WorldState/input this agent consumed.")
    output: Optional[T] = Field(default=None, description="Structured agent output.")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list)
    reasoning: str = ""
    warnings: List[str] = Field(default_factory=list)
    impact: ImpactLevel = ImpactLevel.MEDIUM
    opinions: List[AgentOpinion] = Field(
        default_factory=list,
        description="Optional structured opinions contributed to the fusion layer.",
    )


class ReasoningStep(BaseModel):
    """One step in the global reasoning trace (probability change -> scenario
    change -> state change -> agent decision -> evidence)."""

    model_config = ConfigDict(extra="forbid")

    sequence: int
    minute: Optional[int] = None
    agent_name: Optional[str] = None
    kind: str = Field(description="e.g. 'agent_decision', 'state_change', 'event', 'fusion'.")
    summary: str
    detail: str = ""
    evidence: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    confidence: Optional[float] = None
    before: Any = None
    after: Any = None


def ensure_range(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Clamp helper used throughout the codebase."""
    return max(low, min(high, value))
