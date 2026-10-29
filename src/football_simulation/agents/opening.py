"""Opening Agent: models the 0-15 minute phase.

Judges who starts aggressively, the pressing intensity, tempo, early chance
creation and early goal risk.
"""

from __future__ import annotations

import math
from typing import List, Optional

from football_simulation.agents.base import AgentContext, BaseAgent
from football_simulation.models.base import AgentResult, ensure_range, Side
from football_simulation.models.world import OpeningState, TacticalMatchupState, WorldState


class OpeningAgent(BaseAgent[OpeningState]):
    name = "OpeningAgent"
    description = "Models the opening 0-15 minutes of the match."

    def analyze(self, world: WorldState, matchup: TacticalMatchupState) -> tuple:
        home_tac = world.home_tactical_state
        away_tac = world.away_tactical_state
        home_psy = world.home_psychological_state
        away_psy = world.away_psychological_state

        home_press = ensure_range(home_tac.pressing_intensity + 0.1 * (1 if world.home_team_state and world.home_team_state.pressing_style == "high_press" else 0))
        away_press = ensure_range(away_tac.pressing_intensity + 0.1 * (1 if world.away_team_state and world.away_team_state.pressing_style == "high_press" else 0))
        if world.home_coach is not None:
            home_press = ensure_range(home_press + 0.08 * (world.home_coach.aggressiveness - 0.5))
        if world.away_coach is not None:
            away_press = ensure_range(away_press + 0.08 * (world.away_coach.aggressiveness - 0.5))

        aggressive_side = Side.HOME if home_press > away_press + 0.05 else (Side.AWAY if away_press > home_press + 0.05 else None)

        # early chance modifiers: matchup modifiers dampened early (game settling)
        home_early = ensure_range(0.75 + 0.45 * (matchup.chance_creation_home - 1.0) + 0.25 * (home_psy.confidence - 0.5), 0.4, 1.8)
        away_early = ensure_range(0.75 + 0.45 * (matchup.chance_creation_away - 1.0) + 0.25 * (away_psy.confidence - 0.5), 0.4, 1.8)

        # early goal risk: P(goal within first 15 minutes) via Poisson
        lam_home = 1.9 * max(0.05, home_early)
        lam_away = 1.9 * max(0.05, away_early)
        risk_home = round(1 - math.exp(-lam_home), 4)
        risk_away = round(1 - math.exp(-lam_away), 4)

        description = (
            f"home press {home_press:.2f} / away press {away_press:.2f}; "
            f"early goal risk home {risk_home:.1%} / away {risk_away:.1%}"
        )

        state = OpeningState(
            aggressive_side=aggressive_side,
            pressing_intensity_home=round(home_press, 3),
            pressing_intensity_away=round(away_press, 3),
            tempo=world.tempo,
            early_chance_modifier_home=round(home_early, 3),
            early_chance_modifier_away=round(away_early, 3),
            early_goal_risk_home=risk_home,
            early_goal_risk_away=risk_away,
            description=description,
        )
        evidence = [
            f"aggressive side: {aggressive_side.value if aggressive_side else 'neither'}",
            description,
        ]
        return state, evidence

    def run(self, context: AgentContext) -> AgentResult[OpeningState]:
        if context.world is None:
            return self.fail(context, "missing world state")
        world = context.world
        matchup = context.matchup if context.matchup is not None else TacticalMatchupState()
        state, evidence = self.analyze(world, matchup)
        return self.ok(
            context,
            state,
            confidence=0.6,
            evidence=evidence,
            reasoning="Opening behavior from coach aggressiveness, styles and psychology.",
        )
