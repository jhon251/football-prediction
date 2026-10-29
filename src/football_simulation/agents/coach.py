"""Coach Agent: models how a coach sets up and reacts.

Different coaches MUST produce different gameplans and different state
transitions (e.g. a defensive coach parks the bus at 1-0; a risk-taking
coach keeps pushing).
"""

from __future__ import annotations

from typing import Dict, List, Optional

from football_simulation.agents.base import AgentContext, BaseAgent
from football_simulation.models.base import AgentResult, ensure_range
from football_simulation.models.entities import CoachProfile, CoachState, TeamState


class CoachAgent(BaseAgent[Dict[str, CoachState]]):
    name = "CoachAgent"
    description = "Builds each coach's behavioral model and this-match gameplan."

    def build_state(
        self,
        profile: CoachProfile,
        own_team: TeamState,
        opponent: TeamState,
        is_home: bool,
        importance: float = 0.5,
    ) -> tuple:
        """Return (CoachState, evidence)."""
        evidence: List[str] = [
            f"{profile.name}: flexibility {profile.tactical_flexibility:.2f}, "
            f"risk tolerance {profile.risk_tolerance:.2f}"
        ]

        formation = profile.preferred_formations[0]
        if not is_home and profile.tactical_flexibility > 0.5 and len(profile.preferred_formations) > 1:
            formation = profile.preferred_formations[1]
            evidence.append(f"away game: switched to {formation}")

        strength_gap = own_team.attack_strength - opponent.defense_strength
        defense_gap = own_team.defense_strength - opponent.attack_strength

        # Gameplan risk: coach's own tolerance, tempered by opponent quality
        # and match importance (big matches -> more caution).
        risk = ensure_range(
            profile.risk_tolerance
            + 0.15 * strength_gap
            - 0.2 * (importance - 0.5)
            - 0.1 * (1.0 - is_home)  # away teams slightly more cautious
        )
        pressing = ensure_range(
            0.4 + 0.4 * profile.aggressiveness
            + (0.12 if own_team.pressing_style == "high_press" else 0)
            - (0.08 if own_team.pressing_style == "low_block" else 0)
            - (0.05 if defense_gap < -0.05 else 0)
        )
        line = ensure_range(
            own_team.defensive_line
            + 0.1 * (profile.risk_tolerance - 0.5)
            - (0.08 if defense_gap < -0.05 else 0)
        )
        tempo = ensure_range(own_team.tempo_preference + 0.1 * (profile.aggressiveness - 0.5))

        state = CoachState(
            coach_id=profile.coach_id,
            name=profile.name,
            team_id=profile.team_id,
            preferred_formations=profile.preferred_formations,
            tactical_flexibility=profile.tactical_flexibility,
            substitution_timing=profile.substitution_timing,
            substitution_patterns=profile.substitution_patterns,
            reaction_to_leading=profile.reaction_to_leading,
            reaction_to_trailing=profile.reaction_to_trailing,
            reaction_to_red_card=profile.reaction_to_red_card,
            reaction_to_conceding=profile.reaction_to_conceding,
            reaction_to_scoring=profile.reaction_to_scoring,
            rotation_tendency=profile.rotation_tendency,
            risk_tolerance=profile.risk_tolerance,
            big_match_behavior=profile.big_match_behavior,
            late_game_behavior=profile.late_game_behavior,
            aggressiveness=profile.aggressiveness,
            gameplan_formation=formation,
            gameplan_pressing_intensity=pressing,
            gameplan_defensive_line=line,
            gameplan_tempo=tempo,
            gameplan_risk_level=risk,
        )
        evidence.append(
            f"gameplan: {formation}, pressing {pressing:.2f}, line {line:.2f}, "
            f"tempo {tempo:.2f}, risk {risk:.2f}"
        )
        return state, evidence

    def run(self, context: AgentContext) -> AgentResult[Dict[str, CoachState]]:
        if context.data is None or context.request is None or context.world is None:
            return self.fail(context, "missing data provider/request/world")
        request = context.request
        world = context.world
        home_team = world.home_team_state
        away_team = world.away_team_state
        if home_team is None or away_team is None:
            return self.fail(context, "world state missing team states")

        home_profile = context.data.get_coach_data(self._coach_id(context.data, request.home_team_id))
        away_profile = context.data.get_coach_data(self._coach_id(context.data, request.away_team_id))

        home_state, home_ev = self.build_state(home_profile, home_team, away_team, is_home=True)
        away_state, away_ev = self.build_state(away_profile, away_team, home_team, is_home=False)
        return self.ok(
            context,
            {"home": home_state, "away": away_state},
            confidence=0.75,
            evidence=home_ev + away_ev,
            reasoning="Gameplans derived from coach profile + team style + opponent strength + home/away.",
        )

    @staticmethod
    def _coach_id(provider, team_id: str) -> str:
        team = provider.get_team_data(team_id)
        if team.coach_id is None:
            raise KeyError(f"No coach linked to team {team_id}")
        return team.coach_id
