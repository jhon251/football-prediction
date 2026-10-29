"""State Transition Agent - the simulation's state machine.

Any major event (goal, red card, penalty, injury, substitution, tactical
change, half time) MUST recompute the WorldState through this module.

Example: 0-0 -> home goal -> 1-0 -> home mentality=leading, away=trailing
-> away risk up, home tempo down -> event probabilities recomputed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from football_simulation.agents.base import AgentContext, BaseAgent
from football_simulation.agents.momentum import MomentumAgent
from football_simulation.core.rule_engine import RuleEngine
from football_simulation.models.base import AgentResult, ensure_range, Side
from football_simulation.models.entities import PlayerState
from football_simulation.models.events import EventType, MatchEvent
from football_simulation.models.knowledge import KnowledgeBase
from football_simulation.models.world import (
    MatchInjury,
    MatchPhase,
    Mentality,
    PsychologicalState,
    TacticalTeamState,
    WorldState,
)

_FORMATION_DOWN_A_MAN = {
    "4-3-3": "4-4-1",
    "4-2-3-1": "4-4-1",
    "4-4-2": "4-4-1",
    "3-5-2": "4-4-1",
    "3-4-3": "4-4-1",
    "3-4-2-1": "4-4-1",
    "5-3-2": "5-3-1",
    "5-4-1": "4-4-1",
    "4-1-4-1": "4-4-1",
    "4-3-2-1": "4-4-1",
}


class StateTransitionAgent(BaseAgent[WorldState]):
    name = "StateTransitionAgent"
    description = "Recomputes WorldState after every major event."

    def __init__(self, rule_engine: RuleEngine, momentum: MomentumAgent):
        self.rule_engine = rule_engine
        self.momentum = momentum
        self.momentum_enabled = True

    # ------------------------------------------------------------------
    # Major transitions
    # ------------------------------------------------------------------
    def apply_event(self, world: WorldState, event: MatchEvent) -> WorldState:
        """Apply the state effects of one (major) event."""
        world = world.evolution_snapshot(last_event=event.event_id)
        if self.momentum_enabled:
            world = self.momentum.apply_event(world, event, {})
        etype = event.event_type

        if etype in (EventType.GOAL, EventType.OWN_GOAL):
            world = self._apply_score_change(world, event)
        elif etype is EventType.RED_CARD or etype is EventType.SECOND_YELLOW:
            world = self._apply_red_card(world, event)
        elif etype is EventType.YELLOW_CARD:
            world = self._apply_yellow_card(world, event)
        elif etype is EventType.INJURY:
            world = self._apply_injury(world, event)
        elif etype is EventType.SUBSTITUTION:
            world = self._apply_substitution(world, event)

        # knowledge-rule driven refinement (mentality/psychology/fatigue/weather)
        # idempotent: rules fire only on condition edges, never compound
        world, _ = self.rule_engine.apply_state(world)
        world = self._sync_mentalities(world)
        return world

    def half_time(self, world: WorldState) -> WorldState:
        """Half-time transition: phase change, partial resets, coach adjustments."""
        world = world.evolution_snapshot(
            phase=MatchPhase.HALF_TIME,
            current_minute=45,
            current_second=0,
        )
        # momentum reset toward neutral per knowledge defaults
        world = world.evolution_snapshot(momentum_home=0.5, momentum_away=0.5)
        # slight physical recovery at the interval
        world = world.evolution_snapshot(
            fatigue_home=round(max(0.0, world.fatigue_home - 0.03), 4),
            fatigue_away=round(max(0.0, world.fatigue_away - 0.03), 4),
        )
        # coach halftime reactions
        world = self._coach_halftime_adjustment(world, Side.HOME)
        world = self._coach_halftime_adjustment(world, Side.AWAY)
        world, _ = self.rule_engine.apply_state(world)
        return self._sync_mentalities(world)

    def full_time(self, world: WorldState) -> WorldState:
        return world.evolution_snapshot(phase=MatchPhase.FULL_TIME)

    # ------------------------------------------------------------------
    # Score change
    # ------------------------------------------------------------------
    def _apply_score_change(self, world: WorldState, event: MatchEvent) -> WorldState:
        if event.side is Side.HOME:
            world = world.evolution_snapshot(score_home=world.score_home + 1)
        else:
            world = world.evolution_snapshot(score_away=world.score_away + 1)
        scorer_side = event.side
        conceder_side = scorer_side.opponent()

        world = self._adjust_psychology(world, scorer_side, conceder_side)
        world = self._coach_reaction(world, scorer_side, conceder_side, "scoring")
        world = self._sync_mentalities(world)
        return world

    def _adjust_psychology(self, world: WorldState, scorer: Side, conceder: Side) -> WorldState:
        changes: Dict[str, Any] = {}
        if scorer is Side.HOME:
            changes["home_psychological_state"] = world.home_psychological_state.model_copy(
                update={
                    "confidence": ensure_range(world.home_psychological_state.confidence + 0.06),
                    "pressure": ensure_range(world.home_psychological_state.pressure - 0.03),
                }
            )
            changes["away_psychological_state"] = world.away_psychological_state.model_copy(
                update={
                    "confidence": ensure_range(world.away_psychological_state.confidence - 0.05),
                    "pressure": ensure_range(world.away_psychological_state.pressure + 0.08),
                }
            )
        else:
            changes["away_psychological_state"] = world.away_psychological_state.model_copy(
                update={
                    "confidence": ensure_range(world.away_psychological_state.confidence + 0.06),
                    "pressure": ensure_range(world.away_psychological_state.pressure - 0.03),
                }
            )
            changes["home_psychological_state"] = world.home_psychological_state.model_copy(
                update={
                    "confidence": ensure_range(world.home_psychological_state.confidence - 0.05),
                    "pressure": ensure_range(world.home_psychological_state.pressure + 0.08),
                }
            )
        return world.evolution_snapshot(**changes)

    def _coach_reaction(
        self, world: WorldState, scorer: Side, conceder: Side, situation: str
    ) -> WorldState:
        """Coach behavioral reactions to scoring/conceding (leading/trailing)."""
        scorer_tac = world.tactical(scorer)
        conceder_tac = world.tactical(conceder)
        scorer_coach = world.coach(scorer)
        conceder_coach = world.coach(conceder)

        scorer_updates: Dict[str, Any] = {}
        conceder_updates: Dict[str, Any] = {}

        if situation == "scoring":
            if scorer_coach is not None:
                if scorer_coach.reaction_to_scoring == "defensive":
                    scorer_updates.update(risk_level=scorer_tac.risk_level - 0.08,
                                          attacking_intensity=scorer_tac.attacking_intensity - 0.06,
                                          tempo_contribution=scorer_tac.tempo_contribution - 0.06)
                elif scorer_coach.reaction_to_scoring == "aggressive":
                    scorer_updates.update(attacking_intensity=scorer_tac.attacking_intensity + 0.05)
            if conceder_coach is not None:
                if conceder_coach.reaction_to_conceding == "aggressive":
                    conceder_updates.update(attacking_intensity=conceder_tac.attacking_intensity + 0.10,
                                            risk_level=conceder_tac.risk_level + 0.10)
                elif conceder_coach.reaction_to_conceding == "moderate":
                    conceder_updates.update(attacking_intensity=conceder_tac.attacking_intensity + 0.05,
                                            risk_level=conceder_tac.risk_level + 0.05)

        changes: Dict[str, Any] = {}
        if scorer is Side.HOME:
            if scorer_updates:
                changes["home_tactical_state"] = scorer_tac.model_copy(update=scorer_updates)
            if conceder_updates:
                changes["away_tactical_state"] = conceder_tac.model_copy(update=conceder_updates)
        else:
            if scorer_updates:
                changes["away_tactical_state"] = scorer_tac.model_copy(update=scorer_updates)
            if conceder_updates:
                changes["home_tactical_state"] = conceder_tac.model_copy(update=conceder_updates)
        if changes:
            world = world.evolution_snapshot(**changes)
        return world

    # ------------------------------------------------------------------
    # Cards
    # ------------------------------------------------------------------
    def _apply_red_card(self, world: WorldState, event: MatchEvent) -> WorldState:
        if event.side is Side.HOME:
            world = world.evolution_snapshot(red_cards_home=world.red_cards_home + 1)
        else:
            world = world.evolution_snapshot(red_cards_away=world.red_cards_away + 1)
        tac = world.tactical(event.side)
        new_formation = _FORMATION_DOWN_A_MAN.get(tac.formation, "4-4-1")
        changes: Dict[str, Any] = {}
        if event.side is Side.HOME:
            changes["home_tactical_state"] = tac.model_copy(
                update={"formation": new_formation, "players_on_pitch": max(7, tac.players_on_pitch - 1)}
            )
        else:
            changes["away_tactical_state"] = tac.model_copy(
                update={"formation": new_formation, "players_on_pitch": max(7, tac.players_on_pitch - 1)}
            )
        world = world.evolution_snapshot(**changes)
        return self._sync_mentalities(world)

    def _apply_yellow_card(self, world: WorldState, event: MatchEvent) -> WorldState:
        if event.side is Side.HOME:
            return world.evolution_snapshot(yellow_cards_home=world.yellow_cards_home + 1)
        return world.evolution_snapshot(yellow_cards_away=world.yellow_cards_away + 1)

    # ------------------------------------------------------------------
    # Injuries
    # ------------------------------------------------------------------
    def _apply_injury(self, world: WorldState, event: MatchEvent) -> WorldState:
        injury = MatchInjury(
            side=event.side,
            player_id=event.player_id or "",
            minute=event.minute,
            severity=float(event.detail) if event.detail.replace(".", "", 1).isdigit() else 0.5,
            injury_type="match_injury",
            player_returns=False,
            forced_substitution=False,
        )
        injuries = list(world.injury_state.injuries) + [injury]
        return world.evolution_snapshot(injury_state=world.injury_state.model_copy(update={"injuries": injuries}))

    # ------------------------------------------------------------------
    # Substitutions
    # ------------------------------------------------------------------
    def _apply_substitution(self, world: WorldState, event: MatchEvent) -> WorldState:
        # event.detail: "player_out:player_in:type"
        parts = event.detail.split(":")
        if len(parts) < 2:
            return world
        player_out, player_in = parts[0], parts[1]
        sub_type = parts[2] if len(parts) > 2 else "tactical"

        side = event.side
        players = world.players(side)
        changes: Dict[str, Any] = {}
        players_changed: Dict[str, PlayerState] = {}
        if player_out in players:
            players_changed[player_out] = players[player_out].model_copy(
                update={"starting": False, "minutes_played": players[player_out].minutes_played}
            )
        if player_in in players:
            players_changed[player_in] = players[player_in].model_copy(
                update={"starting": True, "current_fatigue": 0.0}
            )
        if side is Side.HOME:
            changes["home_players"] = {**world.home_players, **players_changed}
        else:
            changes["away_players"] = {**world.away_players, **players_changed}

        # tactical effect of the substitution type
        tac = world.tactical(side)
        tac_updates: Dict[str, Any] = {}
        if sub_type == "defensive":
            tac_updates.update(attacking_intensity=ensure_range(tac.attacking_intensity - 0.04),
                               risk_level=ensure_range(tac.risk_level - 0.05),
                               pressing_intensity=ensure_range(tac.pressing_intensity + 0.03))
        elif sub_type == "attacking":
            tac_updates.update(attacking_intensity=ensure_range(tac.attacking_intensity + 0.06),
                               risk_level=ensure_range(tac.risk_level + 0.05))
        elif sub_type == "fatigue":
            tac_updates.update(chance_creation_modifier=tac.chance_creation_modifier * 1.03)
        if tac_updates:
            if side is Side.HOME:
                changes["home_tactical_state"] = tac.model_copy(update=tac_updates)
            else:
                changes["away_tactical_state"] = tac.model_copy(update=tac_updates)

        # bookkeeping
        sub_state = world.substitution_state.for_side(side)
        window = self._window_name(event.minute)
        changes["substitution_state"] = world.substitution_state.model_copy(
            update={
                "home" if side is Side.HOME else "away": sub_state.model_copy(
                    update={
                        "subs_made": sub_state.subs_made + 1,
                        "windows_used": sub_state.windows_used + ([window] if window not in sub_state.windows_used else []),
                    }
                )
            }
        )
        return world.evolution_snapshot(**changes)

    @staticmethod
    def _window_name(minute: int) -> str:
        if minute < 60:
            return "early"
        if minute < 75:
            return "mid"
        return "late"

    # ------------------------------------------------------------------
    # Coach halftime adjustment
    # ------------------------------------------------------------------
    def _coach_halftime_adjustment(self, world: WorldState, side: Side) -> WorldState:
        coach = world.coach(side)
        tac = world.tactical(side)
        mentality = world.mentality(side)
        updates: Dict[str, Any] = {}
        if coach is None:
            return world
        if mentality is Mentality.TRAILING and coach.reaction_to_trailing in ("moderate", "aggressive"):
            updates.update(attacking_intensity=ensure_range(tac.attacking_intensity + 0.08),
                           risk_level=ensure_range(tac.risk_level + 0.08),
                           tempo_contribution=ensure_range(tac.tempo_contribution + 0.05, -1.0, 1.0))
        elif mentality is Mentality.LEADING and coach.reaction_to_leading == "defensive":
            updates.update(attacking_intensity=ensure_range(tac.attacking_intensity - 0.05),
                           risk_level=ensure_range(tac.risk_level - 0.06),
                           defensive_line=ensure_range(tac.defensive_line - 0.04))
        if updates:
            changes = {"home_tactical_state" if side is Side.HOME else "away_tactical_state": tac.model_copy(update=updates)}
            world = world.evolution_snapshot(**changes)
        return world

    # ------------------------------------------------------------------
    # Mentality sync
    # ------------------------------------------------------------------
    def _sync_mentalities(self, world: WorldState) -> WorldState:
        home_ment = world.mentality(Side.HOME)
        away_ment = world.mentality(Side.AWAY)
        changes: Dict[str, Any] = {}
        if world.home_tactical_state.mentality != home_ment:
            changes["home_tactical_state"] = world.home_tactical_state.model_copy(update={"mentality": home_ment})
        if world.away_tactical_state.mentality != away_ment:
            changes["away_tactical_state"] = world.away_tactical_state.model_copy(update={"mentality": away_ment})
        if changes:
            world = world.evolution_snapshot(**changes)
        return world

    # ------------------------------------------------------------------
    # Agent interface (rarely used directly; engine calls the methods above)
    # ------------------------------------------------------------------
    def run(self, context: AgentContext) -> AgentResult[WorldState]:
        if context.world is None:
            return self.fail(context, "missing world state")
        world = self._sync_mentalities(context.world)
        world, mods = self.rule_engine.apply_state(world)
        return self.ok(
            context,
            world,
            confidence=0.7,
            evidence=[f"{m.rule_name}: {m.target} {m.before:.2f}->{m.after:.2f}" for m in mods[:10]],
            reasoning="State transitions applied from score/cards/injuries/subs + knowledge rules.",
        )
