"""Space Agent: identifies dangerous zones dynamically.

Dangerous spaces change with the match state (red cards, trailing push,
tactical changes) - not fixed at kickoff.
"""

from __future__ import annotations

from typing import List

from football_simulation.agents.base import AgentContext, BaseAgent
from football_simulation.models.base import AgentResult, ensure_range, Side
from football_simulation.models.world import (
    DangerousSpace,
    SpaceZone,
    TacticalMatchupState,
    WorldState,
)


class SpaceAgent(BaseAgent[List[DangerousSpace]]):
    name = "SpaceAgent"
    description = "Identifies current dangerous zones from matchup + state."

    def analyze(self, world: WorldState, matchup: TacticalMatchupState) -> List[DangerousSpace]:
        zones: List[DangerousSpace] = []
        home_team = world.home_team_state
        away_team = world.away_team_state

        def add(zone: SpaceZone, side: Side, danger: float, reason: str) -> None:
            zones.append(DangerousSpace(zone=zone, side=side, danger=ensure_range(danger), reason=reason))

        if matchup is not None:
            for zone_name in matchup.dangerous_zones:
                mapping = {
                    "left_wing": SpaceZone.LEFT_WING,
                    "right_wing": SpaceZone.RIGHT_WING,
                    "half_space_left": SpaceZone.HALF_SPACE_LEFT,
                    "half_space_right": SpaceZone.HALF_SPACE_RIGHT,
                    "central": SpaceZone.CENTRAL,
                    "behind_defense": SpaceZone.BEHIND_DEFENSE,
                    "between_lines": SpaceZone.BETWEEN_LINES,
                    "set_piece": SpaceZone.SET_PIECE,
                }
                if zone_name in mapping:
                    add(mapping[zone_name], Side.HOME, 0.6, f"matchup pattern: {zone_name}")

        # State-driven changes:
        if home_team and away_team:
            # Trailing side pushes the line up -> space behind it grows.
            if world.mentality(Side.AWAY) is not None:
                if world.score_home > world.score_away and world.current_minute >= 60:
                    add(SpaceZone.BEHIND_DEFENSE, Side.HOME, 0.7, "away pushing up while trailing")
            if world.score_away > world.score_home and world.current_minute >= 60:
                add(SpaceZone.BEHIND_DEFENSE, Side.AWAY, 0.7, "home pushing up while trailing")

        # Numerical advantage opens spaces everywhere for the 11-man side.
        if world.red_cards_home > world.red_cards_away:
            add(SpaceZone.BETWEEN_LINES, Side.AWAY, 0.75, "home down a man")
            add(SpaceZone.BEHIND_DEFENSE, Side.AWAY, 0.7, "home down a man")
        elif world.red_cards_away > world.red_cards_home:
            add(SpaceZone.BETWEEN_LINES, Side.HOME, 0.75, "away down a man")
            add(SpaceZone.BEHIND_DEFENSE, Side.HOME, 0.7, "away down a man")

        # Set-piece danger driven by accumulated corners/free kicks.
        if world.corners_home + world.corners_away >= 8:
            add(SpaceZone.SET_PIECE, Side.HOME, 0.55, "many dead-ball situations")

        return zones

    def run(self, context: AgentContext) -> AgentResult[List[DangerousSpace]]:
        if context.world is None:
            return self.fail(context, "missing world state")
        matchup = context.matchup if context.matchup is not None else TacticalMatchupState()
        zones = self.analyze(context.world, matchup)
        return self.ok(
            context,
            zones,
            confidence=0.6,
            evidence=[f"{z.zone.value} (danger {z.danger:.2f}) - {z.reason}" for z in zones],
            reasoning="Zones from matchup patterns + live match state (cards/score/time).",
        )
