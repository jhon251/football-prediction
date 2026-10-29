"""Tactical Matchup Agent - the core analytical agent.

Answers: "How does team A's tactic act on team B?" using the tactical pattern
knowledge pack (RuleEngine over {home_style, away_style}) plus structural
style-vs-style logic (pressing vs build-up, low block vs possession,
counter vs high line, wing play vs narrow defense, ...).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from football_simulation.agents.base import AgentContext, BaseAgent
from football_simulation.core.rule_engine import RuleEngine
from football_simulation.models.base import AgentResult, ensure_range
from football_simulation.models.entities import TeamState
from football_simulation.models.world import TacticalMatchupState


class TacticalMatchupAgent(BaseAgent[TacticalMatchupState]):
    name = "TacticalMatchupAgent"
    description = "Computes tactical advantages, dangerous zones and chance modifiers."

    def analyze(
        self, home: TeamState, away: TeamState, pattern_kb: Any
    ) -> tuple:
        """Return (TacticalMatchupState, evidence lines)."""
        ctx = {
            "home_style": home,
            "away_style": away,
            "home_pressing_success_probability": 0.5,
            "away_pressing_success_probability": 0.5,
            "home_chance_creation_modifier": 1.0,
            "away_chance_creation_modifier": 1.0,
            "home_possession_modifier": 0.0,
            "away_possession_modifier": 0.0,
            "home_transition_risk": 0.5,
            "away_transition_risk": 0.5,
            "home_counter_shot_quality_bonus": 0.0,
            "away_counter_shot_quality_bonus": 0.0,
            "home_set_piece_xg_bonus": 0.0,
            "away_set_piece_xg_bonus": 0.0,
            "home_crossing_modifier": 0.0,
            "away_crossing_modifier": 0.0,
        }
        engine = RuleEngine(pattern_kb)
        mods = engine.apply(ctx, category="tactical_patterns")
        applied = engine.apply_modifiers(ctx, mods, copy=True)
        pattern_names = sorted({m.rule_name for m in mods})

        # ---- transition risk first (chance creation depends on it) -------
        # how exposed a side is to opponent counters
        trans_home = ensure_range(
            0.4
            + 0.35 * away.counter_attack_strength
            + 0.15 * home.defensive_line
            + (applied["home_transition_risk"] - 0.5)
        )
        trans_away = ensure_range(
            0.4
            + 0.35 * home.counter_attack_strength
            + 0.15 * away.defensive_line
            + (applied["away_transition_risk"] - 0.5)
        )

        # ---- structural (non-pattern) matchup terms ---------------------
        # chance creation is a SYMMETRIC attack-vs-defense comparison: a
        # strong defense must suppress the opponent's chance quality even
        # when the opponent is not stronger on paper.
        cc_home = applied["home_chance_creation_modifier"] * ensure_range(
            0.75 + 0.5 * (home.attack_strength - away.defense_strength), 0.45, 1.35
        )
        cc_home *= 1.0 + 0.55 * max(0.0, home.counter_attack_strength * trans_away - 0.25)
        cc_away = applied["away_chance_creation_modifier"] * ensure_range(
            0.75 + 0.5 * (away.attack_strength - home.defense_strength), 0.45, 1.35
        )
        cc_away *= 1.0 + 0.55 * max(0.0, away.counter_attack_strength * trans_home - 0.25)

        press_home = ensure_range(
            applied["home_pressing_success_probability"]
            + 0.15 * (1 if home.pressing_style == "high_press" else 0)
            - 0.15 * (1 if away.build_up_style == "positional" else 0)
            + 0.10 * (home.midfield_strength - away.midfield_strength)
        )
        press_away = ensure_range(
            applied["away_pressing_success_probability"]
            + 0.15 * (1 if away.pressing_style == "high_press" else 0)
            - 0.15 * (1 if home.build_up_style == "positional" else 0)
            + 0.10 * (away.midfield_strength - home.midfield_strength)
        )

        poss_home = ensure_range(
            0.5
            + 0.30 * (home.possession_preference - away.possession_preference)
            + 0.22 * (home.midfield_strength - away.midfield_strength)
            + applied["home_possession_modifier"]
            - applied["away_possession_modifier"],
            0.28,
            0.72,
        )

        adv_home = ensure_range(
            (cc_home - cc_away) * 0.55 + (press_home - press_away) * 0.35, -1.0, 1.0
        )

        zones, spaces = self._zones(home, away, applied)
        analysis_lines = [
            f"chance creation: home {cc_home:.2f} vs away {cc_away:.2f}",
            f"pressing success: home {press_home:.2f} vs away {press_away:.2f}",
            f"possession target: home {poss_home:.2f}",
            f"transition risk: home {trans_home:.2f} vs away {trans_away:.2f}",
            f"active patterns: {pattern_names or ['none']}",
            f"dangerous zones: {zones or ['none']}",
        ]

        state = TacticalMatchupState(
            tactical_advantage_home=round(adv_home, 3),
            tactical_advantage_away=round(-adv_home, 3),
            dangerous_zones=zones,
            exploitable_spaces=spaces,
            transition_risk_home=round(trans_home, 3),
            transition_risk_away=round(trans_away, 3),
            pressing_success_home=round(press_home, 3),
            pressing_success_away=round(press_away, 3),
            chance_creation_home=round(ensure_range(cc_home, 0.1, 3.0), 3),
            chance_creation_away=round(ensure_range(cc_away, 0.1, 3.0), 3),
            possession_target_home=round(poss_home, 3),
            counter_shot_quality_bonus_home=round(applied["home_counter_shot_quality_bonus"], 3),
            counter_shot_quality_bonus_away=round(applied["away_counter_shot_quality_bonus"], 3),
            set_piece_xg_bonus_home=round(applied["home_set_piece_xg_bonus"], 3),
            set_piece_xg_bonus_away=round(applied["away_set_piece_xg_bonus"], 3),
            crossing_modifier_home=round(applied["home_crossing_modifier"], 3),
            crossing_modifier_away=round(applied["away_crossing_modifier"], 3),
            analysis=" | ".join(analysis_lines),
            pattern_names=pattern_names,
        )
        return state, analysis_lines

    # ------------------------------------------------------------------
    def _zones(self, home: TeamState, away: TeamState, applied: Dict[str, Any]):
        zones: List[str] = []
        spaces: List[str] = []
        if home.wing_attack_preference > 0.55:
            zones.append("right_wing")
            zones.append("left_wing")
            spaces.append("wide_areas_vs_narrow_defense")
        if home.counter_attack_strength > 0.6 and away.defensive_line > 0.6:
            zones.append("behind_defense")
            spaces.append("space_behind_away_high_line")
        if away.counter_attack_strength > 0.6 and home.defensive_line > 0.6:
            zones.append("behind_defense")
            spaces.append("space_behind_home_high_line")
        if home.central_attack_preference > 0.55:
            zones.append("central")
        if away.pressing_style == "low_block":
            zones.append("between_lines")
            spaces.append("between_the_lines_vs_low_block")
        if abs(home.set_piece_strength - away.set_piece_defense) > 0.2:
            zones.append("set_piece")
        # dedupe, keep order
        zones = list(dict.fromkeys(zones))
        spaces = list(dict.fromkeys(spaces))
        return zones, spaces

    # ------------------------------------------------------------------
    def run(self, context: AgentContext) -> AgentResult[TacticalMatchupState]:
        if context.world is None or context.knowledge is None:
            return self.fail(context, "missing world/knowledge")
        world = context.world
        home = world.home_team_state
        away = world.away_team_state
        if home is None or away is None:
            return self.fail(context, "world state missing team states")
        pattern_kb = context.knowledge.get("tactical_patterns")
        if pattern_kb is None:
            return self.fail(context, "tactical pattern knowledge pack missing")
        state, evidence = self.analyze(home, away, pattern_kb)
        return self.ok(
            context,
            state,
            confidence=0.65,
            evidence=evidence,
            reasoning="Matchup = tactical pattern rules + structural style-vs-style terms.",
        )
