"""Team Agent: builds the behavioral model (TeamState) of teams for a match.

Not just ELO/rank/points - it models HOW the team plays and HOW it reacts.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from football_simulation.agents.base import AgentContext, BaseAgent
from football_simulation.models.base import AgentResult, ensure_range
from football_simulation.models.data import MatchHistory
from football_simulation.models.entities import TeamProfile, TeamState


class TeamAgent(BaseAgent[Dict[str, TeamState]]):
    name = "TeamAgent"
    description = "Builds each team's playing style & behavioral model (TeamState)."

    def build_state(
        self, profile: TeamProfile, history: Optional[MatchHistory], is_home: bool
    ) -> tuple:
        """Return (TeamState, evidence_lines)."""
        evidence: List[str] = [f"profile {profile.name} ({profile.team_id})"]

        form_mult = 1.0
        recent = history.entries if history else []
        if recent:
            points = 0
            goals_for = 0
            goals_against = 0
            n = min(6, len(recent))
            for entry in recent[:n]:
                goals_for += entry.goals_for
                goals_against += entry.goals_against
                if entry.goals_for > entry.goals_against:
                    points += 3
                elif entry.goals_for == entry.goals_against:
                    points += 1
            ppg = points / n if n else 1.0
            form_mult = ensure_range(0.85 + (ppg - 1.2) * 0.12, 0.85, 1.15)
            gd = goals_for - goals_against
            evidence.append(
                f"recent form: {points}pts/{n} games (GD {gd:+d}) -> strength multiplier {form_mult:.2f}"
            )
        else:
            evidence.append("no match history available; form multiplier stays 1.0")

        home_mod = profile.home_advantage if is_home else -profile.home_advantage * 0.6
        evidence.append(f"home/away adjustment: {home_mod:+.3f}")

        state = TeamState(
            team_id=profile.team_id,
            name=profile.name,
            preferred_formation=profile.preferred_formation,
            build_up_style=profile.build_up_style,
            pressing_style=profile.pressing_style,
            defensive_line=profile.defensive_line,
            transition_style=profile.transition_style,
            counter_attack_strength=profile.counter_attack_strength,
            possession_preference=profile.possession_preference,
            crossing_preference=profile.crossing_preference,
            central_attack_preference=profile.central_attack_preference,
            wing_attack_preference=profile.wing_attack_preference,
            set_piece_strength=profile.set_piece_strength,
            set_piece_defense=profile.set_piece_defense,
            reaction_to_leading="moderate",
            reaction_to_trailing="moderate",
            reaction_to_draw="balanced",
            late_game_behavior="game_management",
            home_behavior="standard" if is_home else "cautious",
            away_behavior="standard" if not is_home else "assertive",
            home_advantage=profile.home_advantage,
            tempo_preference=ensure_range(0.4 + profile.possession_preference * 0.3),
            risk_tolerance=ensure_range(0.35 + profile.counter_attack_strength * 0.3),
            attack_strength=ensure_range(profile.attack_strength * form_mult + home_mod),
            defense_strength=ensure_range(
                profile.defense_strength * (0.6 + 0.4 * form_mult)
                + (home_mod if home_mod > 0 else home_mod * 0.5)
            ),
            goalkeeper_strength=profile.goalkeeper_strength,
            midfield_strength=profile.midfield_strength,
            squad_depth=profile.squad_depth,
            elo_rating=profile.elo_rating,
        )
        return state, evidence

    def run(self, context: AgentContext) -> AgentResult[Dict[str, TeamState]]:
        if context.data is None or context.request is None:
            return self.fail(context, "missing data provider or request")
        request = context.request
        home_profile = context.data.get_team_data(request.home_team_id)
        away_profile = context.data.get_team_data(request.away_team_id)
        home_history = context.data.get_match_history(
            request.home_team_id, request.competition_id, request.season, request.kickoff
        )
        away_history = context.data.get_match_history(
            request.away_team_id, request.competition_id, request.season, request.kickoff
        )
        home_state, home_evidence = self.build_state(home_profile, home_history, is_home=True)
        away_state, away_evidence = self.build_state(away_profile, away_history, is_home=False)

        reasoning = (
            f"{home_state.name}: attack {home_state.attack_strength:.2f} / defense "
            f"{home_state.defense_strength:.2f} / midfield {home_state.midfield_strength:.2f} | "
            f"{away_state.name}: attack {away_state.attack_strength:.2f} / defense "
            f"{away_state.defense_strength:.2f} / midfield {away_state.midfield_strength:.2f}"
        )
        confidence = 0.7 if (home_history.entries and away_history.entries) else 0.45
        return self.ok(
            context,
            {"home": home_state, "away": away_state},
            confidence=confidence,
            evidence=home_evidence + away_evidence,
            reasoning=reasoning,
        )
