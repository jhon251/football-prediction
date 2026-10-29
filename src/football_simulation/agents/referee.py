"""Referee Agent: referee behavioral model.

The referee NEVER decides a result - the tendencies only shift event
probabilities (card/penalty rates), and only via knowledge-backed modifiers.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from football_simulation.agents.base import AgentContext, BaseAgent
from football_simulation.models.base import AgentResult, ensure_range
from football_simulation.models.entities import RefereeProfile, RefereeState
from football_simulation.models.world import RefereeMatchState


class RefereeAgent(BaseAgent[RefereeMatchState]):
    name = "RefereeAgent"
    description = "Builds the referee behavior model for the match."

    def build_state(self, profile: RefereeProfile) -> tuple:
        evidence_quality = ensure_range(min(1.0, profile.matches_officiated / 100.0))
        evidence = [
            f"{profile.name}: {profile.matches_officiated} matches officiated -> "
            f"evidence quality {evidence_quality:.2f}"
        ]
        state = RefereeMatchState(
            referee_id=profile.referee_id,
            name=profile.name,
            yellow_card_tendency=profile.yellow_card_tendency,
            red_card_tendency=profile.red_card_tendency,
            penalty_tendency=profile.penalty_tendency,
            foul_tolerance=profile.foul_tolerance,
            advantage_play=profile.advantage_play,
            var_interaction=profile.var_interaction,
            known=True,
        )
        return state, evidence

    def run(self, context: AgentContext) -> AgentResult[RefereeMatchState]:
        if context.data is None or context.request is None:
            return self.fail(context, "missing data provider/request")
        request = context.request
        referee_id = context.data.referee_for_match(request.match_id)
        if referee_id is None:
            return self.ok(
                context,
                RefereeMatchState(known=False),
                confidence=0.2,
                warnings=[f"referee for match {request.match_id} unknown"],
                reasoning="Referee unknown; neutral tendencies assumed and flagged.",
            )
        profile = context.data.get_referee_data(referee_id)
        state, evidence = self.build_state(profile)
        return self.ok(
            context,
            state,
            confidence=0.6 + 0.3 * ensure_range(profile.matches_officiated / 100.0),
            evidence=evidence,
            reasoning="Referee tendencies shift event probabilities only (cards/penalties/VAR).",
        )
