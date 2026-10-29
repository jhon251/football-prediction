"""Event Trigger Agent / Event Engine.

Discovers events that can change the match state and samples them given the
current WorldState + a seedable RNG.  Events are NOT random dice: every
probability is driven by WorldState, TeamState, PlayerState, TacticalState,
Momentum, Fatigue, Referee and Environment, and constrained by Event
Dependency Rules (no one-minute black-swan pileups).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from football_simulation.agents.base import AgentContext, BaseAgent
from football_simulation.agents.quality import estimate_player_quality
from football_simulation.core.rng import SeedableRNG
from football_simulation.models.base import AgentResult, ensure_range, Side, new_id
from football_simulation.models.entities import PlayerState, Position
from football_simulation.models.events import (
    EventDependencyRule,
    EventProbabilities,
    EventType,
    MatchEvent,
)
from football_simulation.models.world import TempoLevel, WorldState

_TEMPO_FACTOR = {
    TempoLevel.VERY_LOW: 0.78,
    TempoLevel.LOW: 0.90,
    TempoLevel.MEDIUM: 1.00,
    TempoLevel.HIGH: 1.12,
    TempoLevel.VERY_HIGH: 1.25,
}


class EventTriggerAgent(BaseAgent[EventProbabilities]):
    name = "EventTriggerAgent"
    description = "Computes event probabilities and samples events from the state."

    def __init__(self, event_defaults: Dict[str, Any]):
        self.defaults = event_defaults
        self.dependency_rules: Dict[EventType, EventDependencyRule] = {}
        for item in event_defaults.get("dependency_rules", []):
            rule = EventDependencyRule.model_validate(item)
            self.dependency_rules[rule.event_type] = rule

    # ------------------------------------------------------------------
    # Per-minute probabilities (the observable, explainable layer)
    # ------------------------------------------------------------------
    def per_minute_probabilities(self, world: WorldState) -> EventProbabilities:
        reasons: Dict[str, str] = {}
        lam_home, r_home = self._attack_intensity(world, Side.HOME)
        lam_away, r_away = self._attack_intensity(world, Side.AWAY)
        reasons["attack_home"] = r_home
        reasons["attack_away"] = r_away
        foul_home, foul_away = self._foul_rates(world)
        p_yellow_home, p_yellow_away = self._yellow_probabilities(world)
        p_pen_home, p_pen_away = self._penalty_probabilities(world)
        p_injury = self.defaults["injury"]["base_rate_per_minute"]

        return EventProbabilities(
            match_id=world.match_id,
            minute=world.current_minute,
            state_version=world.state_version,
            attack_intensity_home=round(lam_home, 5),
            attack_intensity_away=round(lam_away, 5),
            attack_outcomes=self.defaults["attack"]["outcomes"],
            foul_rate_home=foul_home,
            foul_rate_away=foul_away,
            p_yellow_given_foul_home=p_yellow_home,
            p_yellow_given_foul_away=p_yellow_away,
            p_penalty_given_attack=max(p_pen_home, p_pen_away),
            p_injury_per_minute=p_injury,
            reasons=reasons,
        )

    def _attack_intensity(self, world: WorldState, side: Side) -> Tuple[float, str]:
        base = self.defaults["attack"]["base_intensity"]
        tac = world.tactical(side)
        psy = world.psychological(side)
        lam = base
        parts = [f"base {base:.3f}"]

        lam *= tac.chance_creation_modifier
        parts.append(f"chance_creation x{tac.chance_creation_modifier:.2f}")

        f_att = 0.55 + 0.9 * tac.attacking_intensity
        lam *= f_att
        parts.append(f"attacking_intensity x{f_att:.2f}")

        m = world.momentum(side)
        f_mom = 0.72 + 0.56 * m
        lam *= f_mom
        parts.append(f"momentum x{f_mom:.2f}")

        f_fat = 1.0 - 0.30 * world.fatigue(side)
        lam *= f_fat
        parts.append(f"fatigue x{f_fat:.2f}")

        if world.players_on_pitch(side) < 11:
            lam *= 0.62
            parts.append("down_a_man x0.62")

        f_tempo = _TEMPO_FACTOR.get(world.tempo, 1.0)
        lam *= f_tempo
        parts.append(f"tempo x{f_tempo:.2f}")

        f_psy = 0.78 + 0.44 * psy.confidence
        lam *= f_psy
        parts.append(f"confidence x{f_psy:.2f}")

        # a tired defense is easier to attack (fatigue -> late vulnerability)
        f_opp_fatigue = 1.0 + 0.25 * world.fatigue(side.opponent())
        lam *= f_opp_fatigue
        if world.fatigue(side.opponent()) > 0.3:
            parts.append(f"opponent_fatigue x{f_opp_fatigue:.2f}")

        if side is Side.HOME and world.home_team_state is not None:
            lam *= 1.0 + world.home_team_state.home_advantage
            parts.append("home_advantage")

        if world.current_minute < 15:
            opening_key = "opening_home" if side is Side.HOME else "opening_away"
            f_open = world.trigger_flags.get(opening_key, 1.0)
            lam *= f_open
            parts.append(f"opening x{f_open:.2f}")

        lam *= self._weather_factor(world)
        return max(0.015, min(0.6, lam)), " | ".join(parts)

    def _weather_factor(self, world: WorldState) -> float:
        ws = world.weather_state
        if not ws.known:
            return 1.0
        factor = 1.0
        if ws.rain is not None and ws.rain > 0.6:
            factor *= 0.95
        if ws.temperature_c is not None and ws.temperature_c > 30:
            factor *= 0.95
        return factor

    def _foul_rates(self, world: WorldState) -> Tuple[float, float]:
        base = self.defaults["fouls"]["base_rate_per_minute"]
        ref_tol = world.referee_state.foul_tolerance if world.referee_state.known else 0.5
        foul_factor = 1.25 - 0.5 * ref_tol
        home = base * foul_factor * (0.75 + 0.5 * world.tactical(Side.HOME).pressing_intensity)
        away = base * foul_factor * (0.75 + 0.5 * world.tactical(Side.AWAY).pressing_intensity)
        if world.players_on_pitch(Side.HOME) < 11:
            home *= 0.8
        if world.players_on_pitch(Side.AWAY) < 11:
            away *= 0.8
        return round(max(0.01, home), 5), round(max(0.01, away), 5)

    def _yellow_probabilities(self, world: WorldState) -> Tuple[float, float]:
        base = self.defaults["fouls"]["p_yellow_given_foul"]
        ref = world.referee_state
        ref_factor = (0.5 + ref.yellow_card_tendency) if ref.known else 1.0
        p_home = base * ref_factor * (1.35 - 0.7 * self._avg_discipline(world, Side.HOME))
        p_away = base * ref_factor * (1.35 - 0.7 * self._avg_discipline(world, Side.AWAY))
        return round(min(0.5, p_home), 5), round(min(0.5, p_away), 5)

    def _penalty_probabilities(self, world: WorldState) -> Tuple[float, float]:
        base = self.defaults["attack"]["outcomes"].get("penalty", 0.01)
        ref = world.referee_state
        factor = (0.5 + ref.penalty_tendency) if ref.known else 1.0
        return base * factor, base * factor

    @staticmethod
    def _avg_discipline(world: WorldState, side: Side) -> float:
        players = [p for p in world.players(side).values() if p.starting and p.available]
        if not players:
            return 0.5
        return sum(p.discipline for p in players) / len(players)

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------
    def sample_minute(
        self, world: WorldState, rng: SeedableRNG, player_yellows: Optional[Dict[str, int]] = None
    ) -> List[MatchEvent]:
        """Sample all events for one minute of play (no state transitions here)."""
        events: List[MatchEvent] = []
        player_yellows = player_yellows or {}
        probs = self._raw_probabilities(world)

        # -- attacks ------------------------------------------------------
        for side, lam in ((Side.HOME, probs["lam_home"]), (Side.AWAY, probs["lam_away"])):
            n = min(6, rng.poisson(lam))
            for _ in range(n):
                event = self._sample_attack(world, side, rng)
                if event is not None:
                    events.append(event)
                    if event.event_type is EventType.PENALTY:
                        converted, pen_events = self._resolve_penalty(world, event, rng)
                        events.extend(pen_events)
                        if converted:
                            goal = self._make_event(
                                world, side, EventType.GOAL, rng, xg=0.76,
                                detail="penalty", player_id=event.player_id,
                            )
                            events.append(goal)
                        # no further attacks this minute after a penalty
                        break

        # -- fouls & cards ------------------------------------------------
        for side, rate, p_yellow in (
            (Side.HOME, probs["foul_home"], probs["p_yellow_home"]),
            (Side.AWAY, probs["foul_away"], probs["p_yellow_away"]),
        ):
            n_fouls = min(5, rng.poisson(rate))
            for _ in range(n_fouls):
                foul_events = self._sample_foul(world, side, p_yellow, rng, player_yellows)
                events.extend(foul_events)
                if any(e.event_type in (EventType.RED_CARD, EventType.SECOND_YELLOW) for e in foul_events):
                    break

        # -- injuries -----------------------------------------------------
        for side in (Side.HOME, Side.AWAY):
            p_inj = probs["p_injury"] * (1.0 + 2.0 * world.fatigue(side))
            if rng.random() < p_inj and world.current_minute >= self.defaults["injury"]["min_minute"]:
                event = self._sample_injury(world, side, rng)
                if event is not None:
                    events.append(event)

        # event dependency enforcement
        return self._enforce_dependencies(world, events, rng)

    # ------------------------------------------------------------------
    def _raw_probabilities(self, world: WorldState) -> Dict[str, float]:
        """Lightweight per-minute intensities (no model allocation)."""
        reasons: Dict[str, str] = {}
        lam_home, r_home = self._attack_intensity(world, Side.HOME)
        lam_away, r_away = self._attack_intensity(world, Side.AWAY)
        reasons["attack_home"] = r_home
        reasons["attack_away"] = r_away
        foul_home, foul_away = self._foul_rates(world)
        p_yellow_home, p_yellow_away = self._yellow_probabilities(world)
        return {
            "lam_home": lam_home,
            "lam_away": lam_away,
            "foul_home": foul_home,
            "foul_away": foul_away,
            "p_yellow_home": p_yellow_home,
            "p_yellow_away": p_yellow_away,
            "p_injury": self.defaults["injury"]["base_rate_per_minute"],
        }

    # ------------------------------------------------------------------
    def _sample_attack(self, world: WorldState, side: Side, rng: SeedableRNG) -> Optional[MatchEvent]:
        outcomes = dict(self.defaults["attack"]["outcomes"])
        opp = side.opponent()
        # fatigue of the opponent breeds defensive errors
        outcomes["defensive_error_opponent"] = outcomes.get("defensive_error_opponent", 0.04) * (
            1.0 + 1.5 * world.fatigue(opp)
        )
        # referee penalty tendency
        outcomes["penalty"] = outcomes.get("penalty", 0.01) * (
            0.5 + world.referee_state.penalty_tendency if world.referee_state.known else 1.0
        )
        keys = list(outcomes.keys())
        weights = [max(0.0, outcomes[k]) for k in keys]
        total = sum(weights)
        weights = [w / total for w in weights]
        outcome = keys[int(rng.choice(len(keys), p=weights))]

        shooter = self._pick_shooter(world, side, rng)

        if outcome == "nothing":
            return None
        if outcome == "shot" or outcome == "big_chance":
            return self._sample_shot(world, side, rng, shooter, big=outcome == "big_chance")
        if outcome == "corner":
            return self._make_event(world, side, EventType.CORNER, rng, xg=0.0, player_id=shooter)
        if outcome == "free_kick":
            return self._make_event(world, side, EventType.FREE_KICK, rng, xg=0.0, player_id=shooter)
            # note: free-kick shots are sampled as a follow-up chance
        if outcome == "foul_conceded_by_opponent":
            return self._make_event(world, opp, EventType.FOUL, rng, xg=0.0,
                                    detail="tactical", player_id=self._pick_fouler(world, opp, rng))
        if outcome == "defensive_error_opponent":
            err = self._make_event(world, opp, EventType.DEFENSIVE_ERROR, rng, xg=0.0,
                                   player_id=self._pick_defender(world, opp, rng))
            # own goal chance follows a defensive error.  An own goal is an
            # opponent error, NOT a team chance: it carries xg 0.0 so team xG
            # accounting stays clean.
            if rng.random() < self.defaults["errors"]["p_own_goal_given_defensive_error"]:
                og = self._make_event(world, side, EventType.OWN_GOAL, rng, xg=0.0,
                                      detail="defensive_mixup", player_id=None)
                return og
            return err
        if outcome == "penalty":
            return self._make_event(world, side, EventType.PENALTY, rng, xg=0.76,
                                    detail="foul_in_box", player_id=shooter)
        return None

    def _sample_shot(
        self, world: WorldState, side: Side, rng: SeedableRNG,
        shooter_id: Optional[str], big: bool = False,
    ) -> MatchEvent:
        cfg = self.defaults["attack"]
        attack_strength = world.team_state(side).attack_strength if world.team_state(side) else 0.6
        opp_defense = world.team_state(side.opponent()).defense_strength if world.team_state(side.opponent()) else 0.6
        # chance quality: own attack quality, suppressed by the opponent's
        # defensive quality (symmetric defense channel)
        mean = (
            cfg["shot_quality_mean"]
            * (0.6 + 0.8 * attack_strength)
            * (1.0 - 0.18 * (opp_defense - 0.5))
        )
        xg = max(0.01, min(cfg["max_xg"], rng.normal(mean, cfg["shot_quality_sigma"])))
        if big:
            xg = max(xg, min(cfg["max_xg"], rng.normal(cfg["big_chance_xg_mean"], 0.25)))
        # counter-attack chance: how often this side transitions against an
        # exposed opponent defense, with higher shot quality from breakaways.
        counter_p = min(
            0.6,
            world.tactical(side).counter_strength_current
            * (0.35 + 0.9 * world.tactical(side.opponent()).transition_risk),
        )
        is_counter = rng.random() < counter_p
        if is_counter:
            bonus = cfg["counter_shot_quality_bonus"]
            bonus += 0.10 * max(0.0, world.tactical(side.opponent()).transition_risk - 0.6)
            if world.matchup_state is not None:
                bonus += (
                    world.matchup_state.counter_shot_quality_bonus_home
                    if side is Side.HOME
                    else world.matchup_state.counter_shot_quality_bonus_away
                )
            xg = min(cfg["max_xg"], xg + bonus)
        shot = self._make_event(world, side, EventType.SHOT, rng, xg=round(xg, 3),
                                detail="counter" if is_counter else "open_play",
                                player_id=shooter_id)
        # Resolution.  CAUSAL INVARIANT: by definition of xG, the goal
        # probability of a shot IS its xG (adjusted for keeper quality here).
        # Gating the goal draw behind "on target" would decouple realized
        # goals from accumulated xG - so the goal draw is direct; on-target
        # only determines the event classification when the shot is NOT a goal.
        p_on = ensure_range(cfg["p_on_target_base"] + 0.35 * xg, 0.15, 0.85)
        gk = world.team_state(side.opponent())
        gk_strength = gk.goalkeeper_strength if gk else 0.6
        p_goal = ensure_range(xg * (1.0 - 0.35 * (gk_strength - 0.5)), 0.0, 0.95)
        scored = rng.random() < p_goal
        if not scored and rng.random() < self.defaults["errors"]["p_keeper_error_given_shot"]:
            if rng.random() < self.defaults["errors"]["keeper_error_goal_probability"]:
                scored = True
                shot = shot.model_copy(update={"detail": "goalkeeper_error"})
        if scored:
            return shot.model_copy(update={"event_type": EventType.GOAL, "detail": shot.detail})
        if rng.random() < p_on:
            return shot.model_copy(update={"event_type": EventType.SHOT_ON_TARGET})
        return shot.model_copy(update={"event_type": EventType.MISS})

    def _resolve_penalty(
        self, world: WorldState, event: MatchEvent, rng: SeedableRNG
    ) -> Tuple[bool, List[MatchEvent]]:
        events: List[MatchEvent] = []
        ref = world.referee_state
        if ref.known and rng.random() < self.defaults["var"]["p_review_penalty"] * (0.5 + ref.var_interaction):
            var = self._make_event(world, event.side, EventType.VAR_REVIEW, rng, xg=0.0, detail="penalty_check")
            events.append(var)
            if rng.random() < self.defaults["var"]["p_overturn_penalty"]:
                return False, events
        # penalty xG must behave like every other shot: keeper quality adjusts
        # the conversion probability, keeping xG accounting consistent.
        gk = world.team_state(event.side.opponent())
        gk_strength = gk.goalkeeper_strength if gk else 0.6
        p_pen = self.defaults["penalty"]["xg"] * (1.0 - 0.35 * (gk_strength - 0.5))
        converted = rng.random() < ensure_range(p_pen, 0.0, 0.95)
        return converted, events

    def _sample_foul(
        self,
        world: WorldState,
        side: Side,
        p_yellow: float,
        rng: SeedableRNG,
        player_yellows: Dict[str, int],
    ) -> List[MatchEvent]:
        events: List[MatchEvent] = []
        player = self._pick_fouler(world, side, rng, player_yellows)
        opp = side.opponent()
        events.append(self._make_event(world, side, EventType.FOUL, rng, xg=0.0,
                                       detail="foul", player_id=player))
        # free kick in a dangerous area?
        if rng.random() < 0.38:
            fk = self._make_event(world, opp, EventType.FREE_KICK, rng, xg=0.0,
                                  detail="foul", player_id=self._pick_shooter(world, opp, rng))
            events.append(fk)
            # direct shot from the set piece occasionally
            if rng.random() < 0.40:
                shot = self._set_piece_shot(world, opp, rng)
                if shot is not None:
                    events.append(shot)

        # cards - second yellow needs a booked player
        if player and player_yellows.get(player, 0) >= 1:
            p_second = self.defaults["fouls"]["p_second_yellow_given_foul"]
            if rng.random() < p_second:
                events.append(self._make_event(world, side, EventType.SECOND_YELLOW, rng, xg=0.0,
                                               detail="second_yellow", player_id=player))
            return events

        p_red = self.defaults["fouls"]["p_direct_red_given_foul"] * (
            0.5 + world.referee_state.red_card_tendency if world.referee_state.known else 1.0
        )
        if rng.random() < p_red:
            events.append(self._make_event(world, side, EventType.RED_CARD, rng, xg=0.0,
                                           detail="straight_red", player_id=player))
        elif rng.random() < p_yellow:
            yellow = self._make_event(world, side, EventType.YELLOW_CARD, rng, xg=0.0,
                                      detail="foul", player_id=player)
            events.append(yellow)
        return events

    def _set_piece_shot(self, world: WorldState, side: Side, rng: SeedableRNG) -> Optional[MatchEvent]:
        xg = max(0.01, min(0.5, rng.normal(0.09, 0.05)))
        shooter = self._pick_shooter(world, side, rng)
        return self._sample_shot_from_xg(world, side, rng, xg, shooter, "set_piece")

    def _sample_shot_from_xg(
        self, world: WorldState, side: Side, rng: SeedableRNG,
        xg: float, shooter: Optional[str], detail: str,
    ) -> MatchEvent:
        p_on = ensure_range(self.defaults["attack"]["p_on_target_base"] + 0.35 * xg, 0.12, 0.8)
        gk = world.team_state(side.opponent())
        gk_strength = gk.goalkeeper_strength if gk else 0.6
        p_goal = ensure_range(xg * (1.0 - 0.35 * (gk_strength - 0.5)), 0.0, 0.9)
        # same xG invariant as open-play shots: goal draw is direct
        scored = rng.random() < p_goal
        shot = self._make_event(world, side, EventType.SHOT, rng, xg=round(xg, 3), detail=detail, player_id=shooter)
        if scored:
            return shot.model_copy(update={"event_type": EventType.GOAL})
        if rng.random() < p_on:
            return shot.model_copy(update={"event_type": EventType.SHOT_ON_TARGET})
        return shot.model_copy(update={"event_type": EventType.MISS})

    def _sample_injury(self, world: WorldState, side: Side, rng: SeedableRNG) -> Optional[MatchEvent]:
        players = [p for p in world.players(side).values() if p.starting and p.available]
        if not players:
            return None
        weights = [p.injury_risk * (1 + p.current_fatigue) for p in players]
        total = sum(weights) or 1.0
        idx = int(rng.choice(len(players), p=[w / total for w in weights]))
        player = players[idx]
        severe = rng.random() < self.defaults["injury"]["severe_probability"]
        severity = rng.uniform(0.55, 0.95) if severe else rng.uniform(0.15, 0.6)
        return self._make_event(world, side, EventType.INJURY, rng, xg=0.0,
                                detail=f"{severity:.2f}", player_id=player.player_id)

    # ------------------------------------------------------------------
    # Player selection
    # ------------------------------------------------------------------
    def _pick_shooter(self, world: WorldState, side: Side, rng: SeedableRNG) -> Optional[str]:
        players = [p for p in world.players(side).values() if p.starting and p.available]
        attackers = [p for p in players if p.position in (Position.ST, Position.LW, Position.RW, Position.AM)]
        pool = attackers or players
        weights = [0.3 + p.technical.finishing + p.mental.composure for p in pool]
        idx = int(rng.choice(len(pool), p=[w / sum(weights) for w in weights]))
        return pool[idx].player_id

    def _pick_defender(self, world: WorldState, side: Side, rng: SeedableRNG) -> Optional[str]:
        players = [p for p in world.players(side).values() if p.starting and p.available]
        defenders = [p for p in players if p.position in (Position.CB, Position.LB, Position.RB, Position.DM)]
        pool = defenders or players
        return pool[int(rng.randint(0, len(pool)))].player_id

    def _pick_fouler(
        self, world: WorldState, side: Side, rng: SeedableRNG,
        player_yellows: Optional[Dict[str, int]] = None,
    ) -> Optional[str]:
        player_yellows = player_yellows or {}
        players = [p for p in world.players(side).values() if p.starting and p.available]
        weights = [
            (p.mental.aggression + (1 - p.discipline) + 0.2 * p.mental.bravery)
            * (0.35 if player_yellows.get(p.player_id, 0) >= 1 else 1.0)
            for p in players
        ]
        idx = int(rng.choice(len(players), p=[w / sum(weights) for w in weights]))
        return players[idx].player_id

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _make_event(
        self,
        world: WorldState,
        side: Side,
        etype: EventType,
        rng: SeedableRNG,
        xg: float = 0.0,
        detail: str = "",
        player_id: Optional[str] = None,
    ) -> MatchEvent:
        return MatchEvent(
            event_id=new_id("ev"),
            match_id=world.match_id,
            minute=world.current_minute,
            second=int(rng.randint(0, 59)),
            side=side,
            event_type=etype,
            player_id=player_id,
            detail=detail,
            xg=xg,
            probability=0.0,
            state_before_version=world.state_version,
            state_after_version=world.state_version,
        )

    def _enforce_dependencies(
        self, world: WorldState, events: List[MatchEvent], rng: SeedableRNG
    ) -> List[MatchEvent]:
        """Hard constraints from the Event Dependency Rules."""
        counts: Dict[EventType, int] = {}
        for e in events:
            counts[e.event_type] = counts.get(e.event_type, 0) + 1
        per_team: Dict[Tuple[EventType, Side], int] = {}
        for e in events:
            per_team[(e.event_type, e.side)] = per_team.get((e.event_type, e.side), 0) + 1

        kept: List[MatchEvent] = []
        for e in events:
            rule = self.dependency_rules.get(e.event_type)
            if rule is not None:
                if per_team.get((e.event_type, e.side), 0) > rule.max_per_team:
                    continue
                if counts.get(e.event_type, 0) > rule.max_per_match:
                    # drop the excess of the rarest event type
                    continue
                if kept:
                    same_minute = sum(1 for k in kept if k.event_type is e.event_type)
                    if same_minute >= rule.max_per_minute:
                        continue
                if e.event_type in (EventType.RED_CARD, EventType.SECOND_YELLOW) and world.players_on_pitch(e.side) <= 10:
                    continue  # already down a man
            kept.append(e)
        return kept

    # ------------------------------------------------------------------
    def run(self, context: AgentContext) -> AgentResult[EventProbabilities]:
        if context.world is None:
            return self.fail(context, "missing world state")
        probs = self.per_minute_probabilities(context.world)
        return self.ok(
            context,
            probs,
            confidence=0.6,
            evidence=list(probs.reasons.values()),
            reasoning="Event intensities derived from state (attack/fouls/cards/injuries) with dependency caps.",
        )
