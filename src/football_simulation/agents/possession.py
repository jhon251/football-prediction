"""Possession Agent: dynamic possession share.

Possession is never a static prediction: it responds to score, tactics,
fatigue, momentum and substitutions through a target + inertia model.
"""

from __future__ import annotations

from typing import List

from football_simulation.agents.base import AgentContext, BaseAgent
from football_simulation.models.base import AgentResult, ensure_range, Side
from football_simulation.models.world import TacticalMatchupState, WorldState


class PossessionAgent(BaseAgent[dict]):
    name = "PossessionAgent"
    description = "Computes the possession target and evolves the live share."

    def target(self, world: WorldState, matchup: TacticalMatchupState) -> float:
        """Target possession for the home side given the current state."""
        home = world.home_team_state
        away = world.away_team_state
        base = matchup.possession_target_home if matchup is not None else 0.5
        # score effect: leading team sits slightly deeper -> concedes possession
        if world.score_home > world.score_away:
            base -= 0.03
        elif world.score_away > world.score_home:
            base += 0.03
        # cards: down a man -> concedes possession
        if world.red_cards_home > world.red_cards_away:
            base -= 0.07
        elif world.red_cards_away > world.red_cards_home:
            base += 0.07
        # fatigue: tired side sits off the ball
        base += 0.04 * (world.fatigue_away - world.fatigue_home)
        # momentum: the side with momentum keeps the ball
        base += 0.06 * (world.momentum_home - 0.5)
        return ensure_range(base, 0.25, 0.75)

    def evolve(
        self,
        world: WorldState,
        matchup: TacticalMatchupState,
        inertia: float,
        noise: float,
    ) -> WorldState:
        """One-step possession update (returns a new WorldState)."""
        target = self.target(world, matchup)
        if world.phase.value in ("first_half", "second_half", "extra_time"):
            drift = noise
            new_home = inertia * world.possession_home + (1 - inertia) * target + drift
            new_home = ensure_range(new_home, 0.1, 0.9)
        else:
            new_home = target
        return world.evolution_snapshot(possession_home=round(new_home, 4), possession_away=round(1 - new_home, 4))

    def run(self, context: AgentContext) -> AgentResult[dict]:
        if context.world is None:
            return self.fail(context, "missing world state")
        matchup = context.matchup if context.matchup is not None else TacticalMatchupState()
        world = context.world
        target = self.target(world, matchup)
        return self.ok(
            context,
            {"target_home": target, "current_home": world.possession_home},
            confidence=0.7,
            evidence=[
                f"possession target {target:.2f} (current {world.possession_home:.2f})"
            ],
            reasoning="Target from matchup + score + cards + fatigue + momentum.",
        )
