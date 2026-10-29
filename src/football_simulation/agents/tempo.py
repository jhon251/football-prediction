"""Tempo Agent: match tempo state machine.

Tempo in {very_low, low, medium, high, very_high} driven by score, tactical
state, fatigue, psychology, time, cards and importance.
"""

from __future__ import annotations

from football_simulation.agents.base import AgentContext, BaseAgent
from football_simulation.models.base import AgentResult, ensure_range, Side
from football_simulation.models.world import TempoLevel, WorldState


_TEMPO_ORDER = [
    TempoLevel.VERY_LOW,
    TempoLevel.LOW,
    TempoLevel.MEDIUM,
    TempoLevel.HIGH,
    TempoLevel.VERY_HIGH,
]


class TempoAgent(BaseAgent[TempoLevel]):
    name = "TempoAgent"
    description = "Derives the current match tempo level."

    def compute(self, world: WorldState) -> tuple:
        """Return (TempoLevel, score, reasons)."""
        score = 2.0  # neutral index into _TEMPO_ORDER (0..4)
        reasons = []

        home_tac = world.home_tactical_state
        away_tac = world.away_tactical_state
        score += 0.5 * (home_tac.tempo_contribution + away_tac.tempo_contribution)
        reasons.append(f"tactical contributions {home_tac.tempo_contribution:+.2f}/{away_tac.tempo_contribution:+.2f}")

        # scoreline effects
        if world.score_home != world.score_away:
            trailing = Side.HOME if world.score_home < world.score_away else Side.AWAY
            tac = world.tactical(trailing)
            score += 0.15 + 0.3 * tac.attacking_intensity * (0.5 if world.current_minute < 60 else 1.0)
            reasons.append("trailing side pushing the pace")
        if world.score_home + world.score_away >= 3:
            score += 0.1
            reasons.append("open game after multiple goals")

        # time-of-match effects: late game urgency
        if world.current_minute >= 75 and world.score_home != world.score_away:
            score += 0.2
            reasons.append("late-game urgency")
        elif world.current_minute >= 75:
            score -= 0.1
            reasons.append("late-game deadlock caution")

        # fatigue drags tempo
        score -= 0.25 * (world.fatigue_home + world.fatigue_away) / 2
        if world.fatigue_home > 0.5 or world.fatigue_away > 0.5:
            reasons.append("fatigue slowing the game")

        # psychology
        home_psy = world.home_psychological_state
        away_psy = world.away_psychological_state
        score += 0.15 * ((home_psy.motivation - 0.5) + (away_psy.motivation - 0.5))
        score -= 0.1 * ((home_psy.pressure - 0.5) + (away_psy.pressure - 0.5))
        reasons.append("psychology-adjusted")

        # cards
        if world.red_cards_home + world.red_cards_away > 0:
            score -= 0.1
            reasons.append("red card reshuffling slows play")

        idx = int(round(ensure_range(score, 0.0, 4.0)))
        return _TEMPO_ORDER[idx], round(score, 3), reasons

    def run(self, context: AgentContext) -> AgentResult[TempoLevel]:
        if context.world is None:
            return self.fail(context, "missing world state")
        level, score, reasons = self.compute(context.world)
        return self.ok(
            context,
            level,
            confidence=0.65,
            evidence=reasons,
            reasoning=f"tempo index {score:.2f} -> {level.value}",
        )
