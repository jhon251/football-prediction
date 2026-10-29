"""Substitution Agent: when / who / why to substitute.

Supports: defensive subs while leading, attacking subs while trailing,
fatigue subs, yellow-card subs, tactical-counter subs and forced injury subs.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from football_simulation.agents.base import AgentContext, BaseAgent
from football_simulation.agents.quality import estimate_player_quality
from football_simulation.models.base import AgentResult, Side
from football_simulation.models.entities import CoachState, PlayerState, Position
from football_simulation.models.world import WorldState


class SubstitutionAgent(BaseAgent[dict]):
    name = "SubstitutionAgent"
    description = "Plans and triggers substitutions with reasons and effects."

    # ------------------------------------------------------------------
    def make_plan(self, world: WorldState, side: Side) -> List[Dict]:
        """Pre-match substitution plan for one side."""
        coach = world.coach(side)
        plan: List[Dict] = []
        if coach is None:
            return plan
        timing = coach.substitution_timing
        windows: List[Tuple[int, str]] = []
        if timing.get("early", 0) > 0.25:
            windows.append((55, "early"))
        if timing.get("mid", 0) > 0.25:
            windows.append((65, "mid"))
        if timing.get("late", 0) > 0.25:
            windows.append((78, "late"))
        n_planned = min(3, len(windows))
        for i in range(n_planned):
            minute, window = windows[i]
            plan.append({"minute": minute, "window": window, "type": "fatigue", "reason": "planned rotation"})
        return plan

    def decide(self, world: WorldState, side: Side, rng=None) -> Optional[Dict]:
        """Return a substitution decision {player_out, player_in, type, reason} or None."""
        coach = world.coach(side)
        if coach is None:
            return None
        sub_state = world.substitution_state.for_side(side)
        if sub_state.subs_made >= sub_state.subs_limit:
            return None
        players = world.players(side)
        on_pitch = [p for p in players.values() if p.starting and p.available]
        if not on_pitch:
            return None
        bench = [p for p in players.values() if not p.starting and p.available]
        if not bench:
            return None

        mentality = world.mentality(side)
        minute = world.current_minute

        # 1) forced-ish: player on a yellow with low discipline, late in game
        if minute >= 60 and world.yellow_cards(side) >= 1:
            for p in on_pitch:
                if p.discipline < 0.35 and p.current_fatigue > 0.4:
                    replacement = self._pick_replacement(bench, p.position, "defensive")
                    if replacement is not None:
                        return self._decision(p, replacement, "yellow_card", "booked player at risk")

        # 2) fatigue: tired players after 60'
        if minute >= 60:
            tired = sorted(on_pitch, key=lambda p: -(p.current_fatigue * p.fatigue_sensitivity))
            for p in tired:
                if p.current_fatigue * p.fatigue_sensitivity > 0.42:
                    replacement = self._pick_replacement(bench, p.position, "fatigue")
                    if replacement is not None:
                        return self._decision(p, replacement, "fatigue", "fatigue replacement")

        # 3) trailing -> attacking sub
        if mentality.value == "trailing" and minute >= 55:
            if coach.reaction_to_trailing in ("moderate", "aggressive"):
                mids = [p for p in on_pitch if p.position in (Position.DM, Position.CM)]
                if mids:
                    tired_mid = max(mids, key=lambda p: p.current_fatigue)
                    replacement = self._pick_replacement(bench, Position.AM, "attacking")
                    if replacement is None:
                        replacement = self._pick_replacement(bench, Position.ST, "attacking")
                    if replacement is not None:
                        return self._decision(tired_mid, replacement, "attacking", "chasing the game")

        # 4) leading -> defensive sub
        if mentality.value == "leading" and minute >= 60:
            if coach.reaction_to_leading in ("defensive", "moderate"):
                attackers = [p for p in on_pitch if p.position in (Position.AM, Position.LW, Position.RW)]
                if attackers:
                    tired_att = max(attackers, key=lambda p: p.current_fatigue)
                    replacement = self._pick_replacement(bench, Position.DM, "defensive")
                    if replacement is None:
                        replacement = self._pick_replacement(bench, Position.CB, "defensive")
                    if replacement is not None:
                        return self._decision(tired_att, replacement, "defensive", "protecting the lead")

        return None

    # ------------------------------------------------------------------
    def forced_injury_sub(self, world: WorldState, side: Side, player_out_id: str) -> Optional[Dict]:
        """Forced replacement for an injured player."""
        players = world.players(side)
        player_out = players.get(player_out_id)
        if player_out is None:
            return None
        bench = [p for p in players.values() if not p.starting and p.available]
        replacement = self._pick_replacement(bench, player_out.position, "tactical")
        if replacement is None:
            return None
        return self._decision(player_out, replacement, "injury", "forced injury substitution")

    def red_card_reaction(self, world: WorldState, side: Side) -> Optional[Dict]:
        """After a red card, replace an attacker with a defender if possible."""
        coach = world.coach(side)
        if coach is None:
            return None
        if coach.reaction_to_red_card != "defensive":
            return None
        players = world.players(side)
        on_pitch = [p for p in players.values() if p.starting and p.available]
        bench = [p for p in players.values() if not p.starting and p.available]
        attackers = [p for p in on_pitch if p.position in (Position.LW, Position.RW, Position.ST)]
        if not attackers:
            return None
        replacement = self._pick_replacement(bench, Position.CB, "defensive")
        if replacement is None:
            replacement = self._pick_replacement(bench, Position.DM, "defensive")
        if replacement is None:
            return None
        return self._decision(attackers[0], replacement, "defensive", "reshaping after red card")

    # ------------------------------------------------------------------
    def _pick_replacement(
        self, bench: List[PlayerState], position: Position, sub_type: str
    ) -> Optional[PlayerState]:
        same_pos = [p for p in bench if p.position is position]
        pool = same_pos or bench
        if not pool:
            return None
        return max(pool, key=lambda p: estimate_player_quality(p) + (0.1 if p.current_fatigue < 0.2 else 0))

    @staticmethod
    def _decision(player_out: PlayerState, player_in: PlayerState, sub_type: str, reason: str) -> Dict:
        return {
            "player_out": player_out.player_id,
            "player_in": player_in.player_id,
            "type": sub_type,
            "reason": reason,
            "detail": f"{player_out.player_id}:{player_in.player_id}:{sub_type}",
        }

    # ------------------------------------------------------------------
    def run(self, context: AgentContext) -> AgentResult[dict]:
        if context.world is None:
            return self.fail(context, "missing world state")
        world = context.world
        home_plan = self.make_plan(world, Side.HOME)
        away_plan = self.make_plan(world, Side.AWAY)
        return self.ok(
            context,
            {"home_plan": home_plan, "away_plan": away_plan},
            confidence=0.6,
            evidence=[f"home plan: {len(home_plan)} subs", f"away plan: {len(away_plan)} subs"],
            reasoning="Substitution plans follow coach timing distributions; in-match triggers react to score/cards/fatigue.",
        )
