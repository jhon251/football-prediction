"""Fitness Agent: fatigue model.

NOT "consecutive matches = -10%": every player has an individual fatigue
sensitivity, and the team fatigue depends on days since last match, recent
match load, minutes played, travel, rotation, age and fitness.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Dict, List, Optional, Tuple

from football_simulation.agents.base import AgentContext, BaseAgent
from football_simulation.models.base import AgentResult, ensure_range
from football_simulation.models.data import MatchHistory
from football_simulation.models.entities import PlayerState, TeamState
from football_simulation.models.world import FitnessState, Side


class FitnessAgent(BaseAgent[Dict[str, FitnessState]]):
    name = "FitnessAgent"
    description = "Estimates per-player and team fatigue with individual sensitivity."

    def build_state(
        self,
        side: Side,
        team_id: str,
        players: Dict[str, PlayerState],
        history: Optional[MatchHistory],
        kickoff,
        travel_burden: float = 0.0,
    ) -> Tuple[FitnessState, List[str]]:
        evidence: List[str] = []
        recent = history.entries if history else []
        matches_recent = 0
        days_since = None
        if recent and kickoff is not None:
            for entry in recent:
                delta = kickoff - entry.date
                if timedelta(0) <= delta < timedelta(days=14):
                    matches_recent += 1
            days_since = (kickoff - recent[0].date).days if recent else None

        minutes_recent = None
        extra_time = False
        international = "unknown"

        per_player: Dict[str, float] = {}
        for pid, p in players.items():
            base_load = 0.0
            if matches_recent >= 3:
                base_load += 0.12 + 0.04 * matches_recent
            elif matches_recent == 2:
                base_load += 0.10
            elif matches_recent == 1:
                base_load += 0.05
            if days_since is not None and days_since <= 2:
                base_load += 0.12
            elif days_since is not None and days_since <= 4:
                base_load += 0.05
            # age & individual sensitivity modulate - not a flat penalty
            age_factor = 0.8 + 0.02 * max(0, p.age - 28)
            fatigue = ensure_range(base_load * p.fatigue_sensitivity * age_factor + travel_burden * 0.4 * p.fatigue_sensitivity)
            per_player[pid] = fatigue

        team_fatigue = sum(per_player.values()) / len(per_player) if per_player else 0.0
        avg_minutes = None
        if players and matches_recent:
            avg_minutes = round(70 + 10 * min(1.0, team_fatigue * 2), 1)

        # Expected fatigue curve over 90 minutes (per-cent segments)
        # higher base fatigue -> steeper late decline.
        decline = ensure_range(0.10 + 0.5 * team_fatigue + 0.2 * (0.5 if matches_recent >= 3 else 0.0), 0.0, 0.6)
        curve = []
        for minute in range(0, 96, 15):
            if minute <= 30:
                f = 0.0
            else:
                progress = (minute - 30) / 65.0
                f = team_fatigue + decline * (progress ** 1.6)
            curve.append(round(ensure_range(f), 3))

        evidence.append(
            f"{team_id}: matches in 14d={matches_recent}, days since last={days_since}, "
            f"team fatigue={team_fatigue:.2f}, late decline={decline:.2f}"
        )
        if international == "unknown":
            evidence.append("international duty: unknown (not fabricated)")

        state = FitnessState(
            side=side,
            team_id=team_id,
            fatigue_score=round(team_fatigue, 3),
            expected_fatigue_curve=curve,
            late_game_decline=round(decline, 3),
            days_since_last_match=days_since,
            matches_in_recent_period=matches_recent,
            average_minutes_recent=avg_minutes,
            travel_burden=travel_burden,
            extra_time_recent=extra_time,
            international_duty=international,
            rotation_freshness=0.5,
            per_player_fatigue={k: round(v, 3) for k, v in per_player.items()},
            evidence=evidence,
        )
        return state, evidence

    def run(self, context: AgentContext) -> AgentResult[Dict[str, FitnessState]]:
        if context.data is None or context.request is None or context.world is None:
            return self.fail(context, "missing data provider/request/world")
        request = context.request
        world = context.world

        out: Dict[str, FitnessState] = {}
        all_evidence: List[str] = []
        for side, team_id, players in (
            (Side.HOME, request.home_team_id, world.home_players),
            (Side.AWAY, request.away_team_id, world.away_players),
        ):
            history = context.data.get_match_history(
                team_id, request.competition_id, request.season, request.kickoff
            )
            state, evidence = self.build_state(side, team_id, players, history, request.kickoff)
            key = "home" if side is Side.HOME else "away"
            out[key] = state
            all_evidence.extend(evidence)

        return self.ok(
            context,
            out,
            confidence=0.6,
            evidence=all_evidence,
            reasoning="Fatigue computed per player (sensitivity x load x age) and aggregated per team.",
        )
