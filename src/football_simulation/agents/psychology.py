"""Psychology Agent: match-context psychology for both sides.

Psychology influences risk-taking, tempo, decision quality and late-game
behavior - never the result directly.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from football_simulation.agents.base import AgentContext, BaseAgent
from football_simulation.models.base import AgentResult, ensure_range
from football_simulation.models.data import MatchHistory
from football_simulation.models.entities import MatchRequest, TeamState
from football_simulation.models.world import PsychologicalState, Side


class PsychologyAgent(BaseAgent[Dict[str, PsychologicalState]]):
    name = "PsychologyAgent"
    description = "Derives psychological states from match context and form."

    def build_state(
        self,
        side: Side,
        team: TeamState,
        history: Optional[MatchHistory],
        is_home: bool,
        context_tags: List[str],
        importance: float,
        coach_pressure: float = 0.5,
    ) -> Tuple[PsychologicalState, List[str]]:
        evidence: List[str] = []

        entries = history.entries if history else []
        recent_points = 0
        wins = losses = draws = 0
        streak = 0  # consecutive wins at the START of the recent list
        for e in entries[:5]:
            if e.goals_for > e.goals_against:
                recent_points += 3
                wins += 1
                streak = streak + 1 if streak >= 0 else 1
            elif e.goals_for == e.goals_against:
                recent_points += 1
                draws += 1
                streak = 0
            else:
                losses += 1
                streak = -1

        confidence = ensure_range(
            0.45
            + 0.06 * (recent_points / 5 - 1.0)
            + (0.05 if streak >= 3 else 0.0)
            + (0.04 if is_home else -0.02)
        )

        pressure = ensure_range(
            0.4
            + 0.15 * importance
            + 0.1 * coach_pressure
            + (0.12 if recent_points <= 3 else 0.0)
            + (0.06 if "must_win" in context_tags else 0.0)
            - (0.08 if streak >= 3 else 0.0)
            + (-0.03 if is_home else 0.03)
        )
        motivation = ensure_range(
            0.5
            + 0.15 * importance
            + (0.10 if "derby" in context_tags else 0.0)
            + (0.05 if "relegation_battle" in context_tags else 0.0)
        )
        composure = ensure_range(0.55 + 0.1 * (confidence - 0.5) - 0.08 * max(0.0, pressure - 0.6))
        risk_appetite = ensure_range(team.risk_tolerance + 0.2 * (motivation - 0.5) - 0.15 * (importance - 0.5))
        crowd = 0.65 if is_home else 0.35
        decision_quality = ensure_range(composure)

        state = PsychologicalState(
            side=side,
            confidence=confidence,
            pressure=pressure,
            motivation=motivation,
            composure=composure,
            risk_appetite=risk_appetite,
            crowd_support=crowd,
            decision_quality=decision_quality,
            context_tags=context_tags,
        )
        evidence.append(
            f"{team.name}: confidence {confidence:.2f}, pressure {pressure:.2f}, "
            f"motivation {motivation:.2f}, tags={context_tags or ['none']}"
        )
        return state, evidence

    def run(self, context: AgentContext) -> AgentResult[Dict[str, PsychologicalState]]:
        if context.data is None or context.request is None or context.world is None:
            return self.fail(context, "missing data provider/request/world")
        request = context.request
        world = context.world
        tags_home, tags_away, importance = self._match_context(request)
        pressure_home, pressure_away = self._coach_pressure(world)

        out: Dict[str, PsychologicalState] = {}
        all_evidence: List[str] = []
        for side, team, is_home, tags, pressure in (
            (Side.HOME, world.home_team_state, True, tags_home, pressure_home),
            (Side.AWAY, world.away_team_state, False, tags_away, pressure_away),
        ):
            if team is None:
                return self.fail(context, "missing team state")
            history = context.data.get_match_history(
                team.team_id, request.competition_id, request.season, request.kickoff
            )
            state, evidence = self.build_state(
                side, team, history, is_home, tags, importance, pressure
            )
            out["home" if is_home else "away"] = state
            all_evidence.extend(evidence)

        return self.ok(
            context,
            out,
            confidence=0.55,
            evidence=all_evidence,
            reasoning="Psychology from context (importance/derby/form/pressure) with bounded effects.",
        )

    # ------------------------------------------------------------------
    def _match_context(self, request: MatchRequest) -> Tuple[List[str], List[str], float]:
        """V1 derives context tags from what the provider knows; unknown flags
        stay absent rather than being guessed."""
        home_tags: List[str] = []
        away_tags: List[str] = []
        importance = 0.5
        # The mock provider does not carry standings; a real provider would.
        # Optional tags are injectable via request? -> not available in V1, so
        # both sides start context-free and the data quality layer flags it.
        return home_tags, away_tags, importance

    def _coach_pressure(self, world) -> Tuple[float, float]:
        return 0.5, 0.5
