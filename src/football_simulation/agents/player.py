"""Player Agent: turns raw player profiles into match PlayerStates.

Players are never just attribute numbers: their state reacts to fatigue,
scoreline, tactics, matchups, psychology and match time (handled by the
simulation layer through PlayerState.current_fatigue etc.).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from football_simulation.agents.base import AgentContext, BaseAgent
from football_simulation.models.base import AgentResult, ensure_range
from football_simulation.models.entities import PlayerProfile, PlayerState, TeamState


class PlayerAgent(BaseAgent[Dict[str, PlayerState]]):
    name = "PlayerAgent"
    description = "Builds per-player match states for both squads."

    def build_state(
        self, profile: PlayerProfile, team_style: TeamState, fitness_inputs: Optional[dict] = None
    ) -> PlayerState:
        fitness_inputs = fitness_inputs or {}

        # Tactical fit: how well the player's profile suits the team's style.
        fit = 0.5
        if team_style.pressing_style == "high_press":
            fit += 0.15 * (profile.behaviors.pressing_behavior - 0.5)
        if team_style.possession_preference > 0.6:
            fit += 0.15 * (profile.technical.passing - 0.5)
        if team_style.counter_attack_strength > 0.6:
            fit += 0.15 * (profile.physical.pace - 0.5)
        fit = ensure_range(fit + profile.tactical_fit * 0.5)

        fatigue = ensure_range(fitness_inputs.get("fatigue", 0.0))
        fitness_score = ensure_range(0.95 - 0.35 * fatigue * profile.fatigue_sensitivity)

        return PlayerState(
            player_id=profile.player_id,
            name=profile.name,
            team_id=profile.team_id,
            age=profile.age,
            position=profile.position,
            role=profile.role,
            preferred_side=profile.preferred_side,
            technical=profile.technical,
            physical=profile.physical,
            mental=profile.mental,
            behaviors=profile.behaviors,
            fatigue_sensitivity=profile.fatigue_sensitivity,
            injury_risk=profile.injury_risk,
            form=profile.form,
            confidence=profile.confidence,
            discipline=profile.discipline,
            tactical_fit=fit,
            current_fatigue=fatigue,
            fitness_score=fitness_score,
            expected_fatigue_curve=fitness_inputs.get("expected_curve", []),
            available=True,
        )

    def run(self, context: AgentContext) -> AgentResult[Dict[str, PlayerState]]:
        if context.data is None or context.request is None or context.world is None:
            return self.fail(context, "missing data provider/request/world")
        request = context.request
        world = context.world

        fitness_by_player: Dict[str, dict] = {}
        for side_players in (world.home_players, world.away_players):
            for pid, ps in side_players.items():
                fitness_by_player[pid] = {"fatigue": ps.current_fatigue}

        out: Dict[str, PlayerState] = {}
        evidence: List[str] = []
        for team_id, team_state, is_home in (
            (request.home_team_id, world.home_team_state, True),
            (request.away_team_id, world.away_team_state, False),
        ):
            profiles = context.data.get_player_data(team_id)
            for profile in profiles:
                state = self.build_state(
                    profile,
                    team_state,
                    fitness_inputs=fitness_by_player.get(profile.player_id),
                )
                out[profile.player_id] = state
            evidence.append(f"{team_id}: {len(profiles)} player states built")

        return self.ok(
            context,
            out,
            confidence=0.8,
            evidence=evidence,
            reasoning="Player states include tactical fit vs team style and fitness-carry-over.",
        )
