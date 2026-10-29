"""Match Simulation Engine - the core executor.

Runs one full match (0 -> 90+) from a frozen WorldState: state -> events ->
state changes -> new event probabilities, minute by minute.  Supports
``simulate_match(seed)`` and ``simulate_n_matches(n)`` with full
reproducibility and convergence analysis (spec sections 26, 46-48).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from football_simulation.agents.momentum import MomentumAgent
from football_simulation.agents.possession import PossessionAgent
from football_simulation.agents.space import SpaceAgent
from football_simulation.agents.substitution import SubstitutionAgent
from football_simulation.agents.tempo import TempoAgent
from football_simulation.core.event_engine import EventTriggerAgent
from football_simulation.core.rng import SeedableRNG
from football_simulation.core.state_machine import StateTransitionAgent
from football_simulation.models.base import Side
from football_simulation.models.events import EventType, MatchEvent
from football_simulation.models.report import ConvergenceReport
from football_simulation.models.simulation import (
    ScoreTimelineEntry,
    SimulatedMatch,
    SimulationBatch,
    TeamMatchStats,
)
from football_simulation.models.world import MatchPhase, TacticalMatchupState, WorldState

_TEMPO_FATIGUE = {"very_low": 0.8, "low": 0.9, "medium": 1.0, "high": 1.12, "very_high": 1.25}


class SimulationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_runs: int = 10000
    keep_events: bool = False
    convergence_threshold: float = 0.005
    convergence_runs: List[int] = Field(default_factory=lambda: [1000, 5000, 10000, 50000])
    possession_inertia: float = 0.85
    possession_noise: float = 0.035
    enable_momentum: bool = True
    start_minute: int = Field(default=0, ge=0, le=90,
                              description="Reality-testing hook: begin the match at this minute.")


@dataclass
class _Run:
    """Mutable per-match bookkeeping (never shared between simulations)."""

    events: List[MatchEvent] = field(default_factory=list)
    player_yellows: Dict[str, int] = field(default_factory=dict)
    subs_planned: Dict[Side, List[Dict]] = field(default_factory=dict)
    possession_sum: Dict[str, float] = field(default_factory=lambda: {"home": 0.0, "away": 0.0})
    possession_n: int = 0
    added_counters: Dict[str, int] = field(
        default_factory=lambda: {"subs": 0, "goals": 0, "injuries": 0}
    )
    match_totals: Dict[EventType, int] = field(default_factory=dict)
    team_totals: Dict[Tuple[EventType, Side], int] = field(default_factory=dict)


class MatchSimulationEngine:
    def __init__(
        self,
        world_template: WorldState,
        rule_engine,
        momentum: MomentumAgent,
        event_agent: EventTriggerAgent,
        substitution_agent: SubstitutionAgent,
        state_machine: StateTransitionAgent,
        matchup: TacticalMatchupState,
        config: Optional[SimulationConfig] = None,
    ):
        self.template = world_template
        self.rule_engine = rule_engine
        self.momentum = momentum
        self.event_agent = event_agent
        self.substitution_agent = substitution_agent
        self.state_machine = state_machine
        self.matchup = matchup
        self.config = config or SimulationConfig()
        self.space_agent = SpaceAgent()
        self.possession_agent = PossessionAgent()
        self.tempo_agent = TempoAgent()
        # momentum can be switched off for ablation studies
        self.state_machine.momentum_enabled = self.config.enable_momentum

    # ------------------------------------------------------------------
    # Single match
    # ------------------------------------------------------------------
    def simulate_match(self, seed: int = 12345) -> SimulatedMatch:
        rng = SeedableRNG(seed)
        # NOTE: nested objects are never mutated in place - every update goes
        # through model_copy, so a SHALLOW copy of the template is safe and
        # dramatically faster than a deep copy.
        world = self.template.model_copy(deep=False)
        world.state_version = 0
        start = self.config.start_minute
        world.current_minute = start
        world.current_second = 0
        world.phase = MatchPhase.SECOND_HALF if start >= 45 else MatchPhase.FIRST_HALF

        run = _Run(
            subs_planned={
                Side.HOME: self.substitution_agent.make_plan(world, Side.HOME),
                Side.AWAY: self.substitution_agent.make_plan(world, Side.AWAY),
            }
        )

        ht_home = ht_away = 0
        added_first = 0
        if start < 45:
            # ---- first half regular minutes start..44 --------------------
            world = self._play_regular(world, start, 44, 1, rng, run)
            added_first = self._added_time(run.added_counters, first_half=True)
            run.added_counters = {"subs": 0, "goals": 0, "injuries": 0}
            # ---- first-half stoppage time ---------------------------------
            for minute in range(45, 45 + added_first):
                world = world.evolution_snapshot(current_minute=minute, phase=MatchPhase.FIRST_HALF)
                world = self._play_minute(world, minute, 1, rng, run, True)
            # ---- half time -------------------------------------------------
            world = self.state_machine.half_time(world)
            ht_home, ht_away = world.score_home, world.score_away
            second_start = 45
        else:
            # injected mid-match states carry the current score as the HT score
            ht_home, ht_away = world.score_home, world.score_away
            second_start = start

        # ---- second half second_start..89 ---------------------------------
        world = self._play_regular(world, second_start, 89, 2, rng, run)
        added_second = self._added_time(run.added_counters, first_half=False)

        # ---- second-half stoppage time ------------------------------------
        for minute in range(90, 90 + added_second):
            world = world.evolution_snapshot(current_minute=minute, phase=MatchPhase.SECOND_HALF)
            world = self._play_minute(world, minute, 2, rng, run, True)

        world = self.state_machine.full_time(world)

        stats_home = self._build_stats(world, Side.HOME, run.possession_sum["home"], run.possession_n, ht_home)
        stats_away = self._build_stats(world, Side.AWAY, run.possession_sum["away"], run.possession_n, ht_away)
        tag = classify_scenario(run.events, ht_home, ht_away, world.score_home, world.score_away)

        return SimulatedMatch(
            match_id=world.match_id,
            seed=seed,
            score_home=world.score_home,
            score_away=world.score_away,
            ht_score_home=ht_home,
            ht_score_away=ht_away,
            home_stats=stats_home,
            away_stats=stats_away,
            events=run.events,
            timeline=build_timeline(run.events),
            scenario_tag=tag,
            minutes_played=90 + added_first + added_second,
        )

    def _play_regular(self, world, minute_start, minute_end, half, rng, run: "_Run"):
        for minute in range(minute_start, minute_end + 1):
            world = world.evolution_snapshot(
                current_minute=minute,
                phase=MatchPhase.FIRST_HALF if half == 1 else MatchPhase.SECOND_HALF,
            )
            world = self._play_minute(world, minute, half, rng, run, False)
        # count stoppage-time drivers from the events of this segment
        for event in run.events:
            if minute_start <= event.minute <= minute_end:
                if event.event_type is EventType.GOAL:
                    run.added_counters["goals"] += 1
                elif event.event_type is EventType.SUBSTITUTION:
                    run.added_counters["subs"] += 1
                elif event.event_type is EventType.INJURY:
                    run.added_counters["injuries"] += 1
        return world

    # ------------------------------------------------------------------
    def _play_minute(
        self,
        world: WorldState,
        minute: int,
        half: int,
        rng: SeedableRNG,
        run: "_Run",
        in_added: bool,
    ) -> WorldState:
        # --- per-minute dynamics -----------------------------------------
        if self.config.enable_momentum:
            world = self.momentum.decay(world, {"decay_per_minute": 0.965, "mean_reversion": 0.03})
        world = self._accumulate_fatigue(world)
        world = self.possession_agent.evolve(
            world,
            self.matchup,
            self.config.possession_inertia,
            self.config.possession_noise * rng.uniform(-1.0, 1.0),
        )
        level, _, _ = self.tempo_agent.compute(world)
        world = world.evolution_snapshot(tempo=level)

        run.possession_sum["home"] += world.possession_home
        run.possession_sum["away"] += world.possession_away
        run.possession_n += 1

        # refresh dangerous spaces periodically / after card shocks
        if minute % 10 == 0 or world.red_cards_home + world.red_cards_away > 0:
            world = world.evolution_snapshot(
                dangerous_spaces=self.space_agent.analyze(world, self.matchup)
            )

        # --- events --------------------------------------------------------
        minute_events = self.event_agent.sample_minute(world, rng, run.player_yellows)
        for event in minute_events:
            if not self._within_caps(event.event_type, event.side, run):
                continue
            event.state_before_version = world.state_version
            run.events.append(event)
            self._count_event(event, run)
            world = self._apply_event(world, event, run, rng)

        # --- substitutions --------------------------------------------------
        world = self._run_substitutions(world, minute, rng, run)

        return world

    # ------------------------------------------------------------------
    def _within_caps(self, etype: EventType, side: Side, run: "_Run") -> bool:
        """Match-level Event Dependency Rule caps (per-minute caps are handled
        by the event agent itself)."""
        rule = self.event_agent.dependency_rules.get(etype)
        if rule is None:
            return True
        if run.match_totals.get(etype, 0) >= rule.max_per_match:
            return False
        if run.team_totals.get((etype, side), 0) >= rule.max_per_team:
            return False
        return True

    @staticmethod
    def _count_event(event: MatchEvent, run: "_Run") -> None:
        run.match_totals[event.event_type] = run.match_totals.get(event.event_type, 0) + 1
        run.team_totals[(event.event_type, event.side)] = (
            run.team_totals.get((event.event_type, event.side), 0) + 1
        )

    def _append_event(self, world: WorldState, event: MatchEvent, run: "_Run", rng: SeedableRNG) -> WorldState:
        """Append + apply an internally-generated event if the caps allow it."""
        if not self._within_caps(event.event_type, event.side, run):
            return world
        event.state_before_version = world.state_version
        run.events.append(event)
        self._count_event(event, run)
        world = self.state_machine.apply_event(world, event)
        event.state_after_version = world.state_version
        return world

    # ------------------------------------------------------------------
    def _apply_event(
        self,
        world: WorldState,
        event: MatchEvent,
        run: "_Run",
        rng: SeedableRNG,
    ) -> WorldState:
        etype = event.event_type
        side = event.side

        # cheap counter updates
        if etype is EventType.GOAL:
            world = self._bump(world, side, shots=1, sot=1, xg=event.xg)
        elif etype is EventType.SHOT_ON_TARGET:
            world = self._bump(world, side, shots=1, sot=1, xg=event.xg)
        elif etype in (EventType.SHOT, EventType.MISS):
            world = self._bump(world, side, shots=1, xg=event.xg)
        elif etype is EventType.BIG_CHANCE:
            world = self._bump(world, side, big_chances=1)
        elif etype is EventType.CORNER:
            world = self._bump(world, side, corners=1)
        elif etype is EventType.FOUL:
            world = self._bump(world, side, fouls=1)
        elif etype is EventType.DEFENSIVE_ERROR:
            world = self._bump(world, side, dangerous_attacks=1)
        elif etype is EventType.VAR_REVIEW:
            world = world.evolution_snapshot(
                referee_state=world.referee_state.model_copy(
                    update={"var_reviews": world.referee_state.var_reviews + 1}
                )
            )

        # yellow with second-yellow tracking
        if etype is EventType.YELLOW_CARD:
            if event.player_id:
                run.player_yellows[event.player_id] = run.player_yellows.get(event.player_id, 0) + 1
                if run.player_yellows[event.player_id] >= 2:
                    world = self.state_machine._apply_yellow_card(world, event)
                    red = event.model_copy(
                        update={
                            "event_type": EventType.SECOND_YELLOW,
                            "detail": "second_yellow",
                            "event_id": f"{event.event_id}-2y",
                        }
                    )
                    world = self._append_event(world, red, run, rng)
                    return world
            world = self.state_machine.apply_event(world, event)

        # major events -> full state transitions
        elif etype in (
            EventType.GOAL,
            EventType.OWN_GOAL,
            EventType.RED_CARD,
            EventType.SECOND_YELLOW,
            EventType.PENALTY,
            EventType.INJURY,
            EventType.SUBSTITUTION,
        ):
            world = self.state_machine.apply_event(world, event)
            if etype is EventType.INJURY and event.player_id:
                decision = self.substitution_agent.forced_injury_sub(world, side, event.player_id)
                if decision is not None:
                    sub_event = self._sub_event(world, side, decision, event.minute, rng)
                    world = self._append_event(world, sub_event, run, rng)
            elif etype is EventType.RED_CARD:
                decision = self.substitution_agent.red_card_reaction(world, side)
                if decision is not None and rng.random() < 0.7:
                    sub_event = self._sub_event(world, side, decision, event.minute, rng)
                    world = self._append_event(world, sub_event, run, rng)

        event.state_after_version = world.state_version
        return world

    def _bump(self, world: WorldState, side: Side, **counts: float) -> WorldState:
        """Increment cumulative counters for one side."""
        prefix = "home" if side is Side.HOME else "away"
        changes: Dict[str, Any] = {}
        for key, value in counts.items():
            if key == "xg":
                field = f"xg_{prefix}"
            elif key == "sot":
                field = f"shots_on_target_{prefix}"
            else:
                field = f"{key}_{prefix}"
            current = getattr(world, field)
            changes[field] = current + value
        return world.evolution_snapshot(**changes)

    # ------------------------------------------------------------------
    def _run_substitutions(
        self,
        world: WorldState,
        minute: int,
        rng: SeedableRNG,
        run: "_Run",
    ) -> WorldState:
        if not (45 <= minute <= 92):
            return world
        for side in (Side.HOME, Side.AWAY):
            plan = run.subs_planned[side]
            due = [p for p in plan if p["minute"] == minute]
            for _ in due:
                decision = self.substitution_agent.decide(world, side, rng)
                if decision is not None:
                    sub_event = self._sub_event(world, side, decision, minute, rng)
                    world = self._append_event(world, sub_event, run, rng)
            run.subs_planned[side] = [p for p in plan if p["minute"] != minute]
            if minute in (55, 62, 70, 78, 84) and rng.random() < 0.55:
                decision = self.substitution_agent.decide(world, side, rng)
                if decision is not None:
                    sub_event = self._sub_event(world, side, decision, minute, rng)
                    world = self._append_event(world, sub_event, run, rng)
        return world

    def _sub_event(self, world: WorldState, side: Side, decision: Dict, minute: int, rng: SeedableRNG) -> MatchEvent:
        return MatchEvent(
            event_id=f"ev-sub-{minute}-{side.value}-{rng.randint(0, 9999)}",
            match_id=world.match_id,
            minute=minute,
            second=int(rng.randint(0, 59)),
            side=side,
            event_type=EventType.SUBSTITUTION,
            player_id=decision["player_out"],
            detail=decision["detail"],
            xg=0.0,
            probability=0.0,
            state_before_version=world.state_version,
            state_after_version=world.state_version,
        )

    # ------------------------------------------------------------------
    def _accumulate_fatigue(self, world: WorldState) -> WorldState:
        cfg = self.event_agent.defaults["fatigue"]
        tempo_factor = _TEMPO_FATIGUE.get(world.tempo.value, 1.0)
        late = 1.35 if world.current_minute >= 70 else 1.0
        rate = cfg["base_rate_per_minute"] * tempo_factor * late
        world = world.evolution_snapshot(
            fatigue_home=round(min(0.95, world.fatigue_home + rate), 4),
            fatigue_away=round(min(0.95, world.fatigue_away + rate), 4),
        )
        if world.current_minute % 10 == 0:
            home_players = {
                pid: p.model_copy(
                    update={
                        "current_fatigue": round(
                            min(0.95, p.current_fatigue + 10 * rate * p.fatigue_sensitivity), 4
                        )
                    }
                )
                for pid, p in world.home_players.items()
                if p.starting and p.available
            }
            away_players = {
                pid: p.model_copy(
                    update={
                        "current_fatigue": round(
                            min(0.95, p.current_fatigue + 10 * rate * p.fatigue_sensitivity), 4
                        )
                    }
                )
                for pid, p in world.away_players.items()
                if p.starting and p.available
            }
            world = world.evolution_snapshot(
                home_players={**world.home_players, **home_players},
                away_players={**world.away_players, **away_players},
            )
        return world

    # ------------------------------------------------------------------
    def _added_time(self, counters: Dict[str, int], first_half: bool) -> int:
        cfg = self.event_agent.defaults["added_time"]
        base = cfg["first_half_base"] if first_half else cfg["second_half_base"]
        extra = (
            cfg["per_substitution"] * counters["subs"]
            + cfg["per_goal"] * counters["goals"]
            + cfg["per_injury"] * counters["injuries"]
        )
        return min(cfg["max_extra"], max(cfg["min_extra"], int(round(base + extra))))

    def _build_stats(self, world: WorldState, side: Side, poss_sum: float, poss_n: int, ht_goals: int) -> TeamMatchStats:
        home = side is Side.HOME
        return TeamMatchStats(
            goals=world.score_home if home else world.score_away,
            ht_goals=ht_goals,
            shots=world.shots_home if home else world.shots_away,
            shots_on_target=world.shots_on_target_home if home else world.shots_on_target_away,
            corners=world.corners_home if home else world.corners_away,
            fouls=world.fouls_home if home else world.fouls_away,
            yellow_cards=world.yellow_cards_home if home else world.yellow_cards_away,
            red_cards=world.red_cards_home if home else world.red_cards_away,
            xg=round(world.xg_home if home else world.xg_away, 3),
            big_chances=world.big_chances_home if home else world.big_chances_away,
            dangerous_attacks=world.dangerous_attacks_home if home else world.dangerous_attacks_away,
            possession_avg=round(poss_sum / poss_n, 4) if poss_n else 0.5,
        )

    # ------------------------------------------------------------------
    # Monte Carlo
    # ------------------------------------------------------------------
    def simulate_n_matches(
        self,
        n: Optional[int] = None,
        base_seed: int = 12345,
        keep_events: Optional[bool] = None,
        progress: Optional[Callable[[int, int], None]] = None,
    ) -> SimulationBatch:
        n = n or self.config.default_runs
        keep = self.config.keep_events if keep_events is None else keep_events
        rng_master = SeedableRNG(base_seed)
        results: List[SimulatedMatch] = []
        for i in range(n):
            seed = rng_master.derive_seed(i)
            match = self.simulate_match(seed)
            if not keep:
                match = match.model_copy(update={"events": []})
            results.append(match)
            if progress is not None and (i + 1) % max(1, n // 20) == 0:
                progress(i + 1, n)
        return SimulationBatch(
            match_id=self.template.match_id,
            runs=n,
            base_seed=base_seed,
            results=results,
            keep_events=keep,
        )

    def convergence_analysis(
        self, runs: Optional[List[int]] = None, base_seed: int = 12345
    ) -> ConvergenceReport:
        """Run increasing batch sizes and check home-win stability."""
        runs = runs or self.config.convergence_runs
        samples: List[Dict[str, Any]] = []
        home_wins: List[float] = []
        for n in runs:
            batch = self.simulate_n_matches(n=n, base_seed=base_seed, keep_events=False)
            counts = batch.result_counts()
            samples.append(
                {
                    "n": n,
                    "home_win": round(counts["home_win"] / n, 4),
                    "draw": round(counts["draw"] / n, 4),
                    "away_win": round(counts["away_win"] / n, 4),
                }
            )
            home_wins.append(counts["home_win"] / n)
        max_delta = max(abs(a - b) for a, b in zip(home_wins, home_wins[1:])) if len(home_wins) > 1 else 1.0
        return ConvergenceReport(
            converged=max_delta <= self.config.convergence_threshold,
            threshold=self.config.convergence_threshold,
            samples=samples,
            max_delta=round(max_delta, 5),
        )


# --------------------------------------------------------------------------
# Module-level helpers
# --------------------------------------------------------------------------

def build_timeline(events: List[MatchEvent]) -> List[ScoreTimelineEntry]:
    timeline: List[ScoreTimelineEntry] = []
    score_h = score_a = 0
    for event in events:
        if event.event_type in (EventType.GOAL, EventType.OWN_GOAL):
            if event.side is Side.HOME:
                score_h += 1
            else:
                score_a += 1
            timeline.append(
                ScoreTimelineEntry(minute=event.minute, score_home=score_h, score_away=score_a)
            )
    return timeline


def classify_scenario(
    events: List[MatchEvent], ht_home: int, ht_away: int, ft_home: int, ft_away: int
) -> str:
    """Map one simulated match to a named scenario archetype (long tail included)."""
    goals = [e for e in events if e.event_type in (EventType.GOAL, EventType.OWN_GOAL)]
    red_cards = [e for e in events if e.event_type in (EventType.RED_CARD, EventType.SECOND_YELLOW)]
    penalties = [e for e in events if e.event_type is EventType.PENALTY]
    own_goals = [e for e in events if e.event_type is EventType.OWN_GOAL]
    keeper_errors = [e for e in events if e.event_type is EventType.GOAL and "goalkeeper_error" in e.detail]
    total = ft_home + ft_away
    result = "home_win" if ft_home > ft_away else ("away_win" if ft_away > ft_home else "draw")

    # rare / long-tail patterns take priority (more specific)
    if own_goals:
        return f"own_goal_{result}"
    if total >= 6:
        return f"goal_fest_{result}"
    if keeper_errors:
        return f"keeper_error_{result}"
    if red_cards:
        return f"red_card_match_{result}"
    if penalties:
        return f"penalty_decided_{result}"

    early_home = any(e.side is Side.HOME and e.minute <= 15 for e in goals)
    early_away = any(e.side is Side.AWAY and e.minute <= 15 for e in goals)

    if result == "home_win" and ht_away > ht_home:
        return "comeback_home"
    if result == "away_win" and ht_home > ht_away:
        return "comeback_away"

    if total == 0:
        return "goalless_draw"
    if result == "draw":
        return "scoring_draw_1_1" if total == 2 else "high_scoring_draw"

    if result == "home_win":
        if early_home and ft_home - ft_away >= 2:
            return "home_early_goal_control"
        if early_home:
            return "home_early_goal_nervous_finish"
        late_decider = any(e.side is Side.HOME and e.minute >= 75 for e in goals)
        if ft_home - ft_away >= 2 and len(goals) >= 3:
            return "high_scoring_home_win"
        if late_decider and ft_home - ft_away == 1:
            return "late_show_home"
        if ft_home - ft_away == 1:
            return "tight_home_win"
        return "home_dominant_win"

    if early_away and ft_away - ft_home >= 2:
        return "away_early_goal_control"
    if early_away:
        return "away_early_goal_nervous_finish"
    late_decider = any(e.side is Side.AWAY and e.minute >= 75 for e in goals)
    if ft_away - ft_home >= 2 and len(goals) >= 3:
        return "high_scoring_away_win"
    if late_decider and ft_away - ft_home == 1:
        return "late_show_away"
    if ft_away - ft_home == 1:
        return "tight_away_win"
    return "away_dominant_win"
