"""Agent base: the standard interface every agent implements.

Agents are STATELESS: they receive inputs (a WorldState snapshot and/or raw
data) and return an ``AgentResult``.  They never mutate shared global state
and never call each other directly - the Director orchestrates everything
(spec sections 60/61/62).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from football_simulation.models.base import AgentResult
from football_simulation.models.entities import MatchRequest
from football_simulation.models.world import WorldState

T = TypeVar("T")


class AgentContext(BaseModel):
    """Everything an agent is allowed to consume in one call."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    match_id: str
    request: Optional[MatchRequest] = None
    world: Optional[WorldState] = None
    data: Optional[Any] = None  # DataProvider
    knowledge: Optional[Any] = None  # dict of knowledge packs
    matchup: Optional[Any] = None  # TacticalMatchupState (set by Director)
    batch: Optional[Any] = None  # SimulationBatch (set by Director)
    input_version: int = 0

    def world_version(self) -> int:
        return self.world.state_version if self.world is not None else 0


class BaseAgent(ABC, Generic[T]):
    """Base class for every agent in the system."""

    name: str = "base_agent"
    description: str = ""

    @abstractmethod
    def run(self, context: AgentContext) -> AgentResult[T]:
        """Analyze the given context and return a standard AgentResult."""

    # -- helpers ----------------------------------------------------------
    def ok(
        self,
        context: AgentContext,
        output: T,
        confidence: float = 0.5,
        evidence: Optional[list] = None,
        reasoning: str = "",
        warnings: Optional[list] = None,
    ) -> AgentResult[T]:
        return AgentResult(
            agent_name=self.name,
            match_id=context.match_id,
            input_version=context.world_version(),
            output=output,
            confidence=max(0.0, min(1.0, confidence)),
            evidence=evidence or [],
            reasoning=reasoning,
            warnings=warnings or [],
        )

    def fail(self, context: AgentContext, reason: str) -> AgentResult[T]:
        return AgentResult(
            agent_name=self.name,
            match_id=context.match_id,
            input_version=context.world_version(),
            output=None,
            confidence=0.0,
            warnings=[reason],
        )


__all__ = ["AgentContext", "BaseAgent"]
