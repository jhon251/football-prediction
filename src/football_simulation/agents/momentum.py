"""Momentum Agent: momentum with decay and mean reversion.

Momentum is NOT "who shot most recently".  It aggregates attacks, shots,
shots on target, dangerous attacks, territory, pressing success, recoveries,
big chances, goals, cards and crowd effect - then decays naturally over time.
"""

from __future__ import annotations

from typing import Dict, Optional

from football_simulation.agents.base import AgentContext, BaseAgent
from football_simulation.models.base import AgentResult, ensure_range, Side
from football_simulation.models.events import EventType, MatchEvent
from football_simulation.models.world import WorldState


class MomentumAgent(BaseAgent[dict]):
    name = "MomentumAgent"
    description = "Maintains decaying momentum with event-driven shifts."

    def shift_for_event(self, event_type: str) -> float:
        """Momentum shift for the *event side* (positive = boost)."""
        table = {
            EventType.GOAL.value: 0.30,
            EventType.PENALTY.value: 0.05,
            EventType.BIG_CHANCE.value: 0.08,
            EventType.SHOT_ON_TARGET.value: 0.04,
            EventType.SHOT.value: 0.02,
            EventType.CORNER.value: 0.015,
            EventType.YELLOW_CARD.value: 0.02,
            EventType.RED_CARD.value: -0.18,
            # Own-goal events carry the BENEFICIARY side (the team awarded the
            # goal), so the shift must be positive for the event side - a gift
            # goal still swings momentum toward the team it helps.
            EventType.OWN_GOAL.value: 0.26,
            EventType.MISS.value: 0.005,
            EventType.DEFENSIVE_ERROR.value: 0.03,
            EventType.GOALKEEPER_ERROR.value: 0.04,
        }
        return table.get(event_type, 0.0)

    def apply_event(self, world: WorldState, event: MatchEvent, params: Dict) -> WorldState:
        """Apply the momentum effect of one event."""
        shift = self.shift_for_event(event.event_type.value)
        side = event.side
        if event.event_type is EventType.RED_CARD:
            # a red card hurts the side that received it
            shift = -abs(shift)
        m_home = world.momentum_home
        m_away = world.momentum_away
        if side is Side.HOME:
            m_home += shift
        else:
            m_away += shift
        # momentum is a zero-sum share
        m_home, m_away = self._normalize(m_home, m_away)
        return world.evolution_snapshot(momentum_home=round(m_home, 4), momentum_away=round(m_away, 4))

    def decay(self, world: WorldState, params: Dict) -> WorldState:
        """Per-minute decay + mean reversion toward 0.5."""
        decay = params.get("decay_per_minute", 0.965)
        reversion = params.get("mean_reversion", 0.03)
        m_home = world.momentum_home
        # decay toward 0.5, then explicit mean reversion pull
        m_home = m_home * decay + 0.5 * (1 - decay)
        m_home += reversion * (0.5 - m_home)
        return world.evolution_snapshot(momentum_home=round(m_home, 4), momentum_away=round(1 - m_home, 4))

    @staticmethod
    def _normalize(m_home: float, m_away: float):
        total = m_home + m_away
        if total <= 0:
            return 0.5, 0.5
        m_home = ensure_range(m_home / total, 0.05, 0.95)
        return m_home, 1 - m_home

    def run(self, context: AgentContext) -> AgentResult[dict]:
        if context.world is None:
            return self.fail(context, "missing world state")
        world = context.world
        params = {"decay_per_minute": 0.965, "mean_reversion": 0.03}
        updated = self.decay(world, params)
        return self.ok(
            context,
            {"momentum_home": updated.momentum_home, "momentum_away": updated.momentum_away},
            confidence=0.6,
            evidence=[f"momentum home {updated.momentum_home:.2f} / away {updated.momentum_away:.2f}"],
            reasoning="Momentum decays per minute with mean reversion; events shift it.",
        )
