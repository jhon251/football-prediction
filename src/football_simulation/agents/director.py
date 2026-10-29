"""Director Agent - the orchestrator.

Pipeline: load data -> run agents -> build WorldState -> generate scenarios ->
simulate -> probability agents -> risk agents -> explanation -> report.
The Director schedules, coordinates, handles conflicts and quality control;
it does NOT make football judgments itself (spec sections 36/37/60).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from football_simulation.agents.base import AgentContext, BaseAgent
from football_simulation.agents.coach import CoachAgent
from football_simulation.agents.counterfactual import CounterfactualAgent
from football_simulation.agents.environment import EnvironmentAgent
from football_simulation.agents.explanation import ExplanationAgent
from football_simulation.agents.fitness import FitnessAgent
from football_simulation.agents.fusion import OpinionFusionLayer
from football_simulation.agents.lineup import LineupAgent
from football_simulation.agents.momentum import MomentumAgent
from football_simulation.agents.opening import OpeningAgent
from football_simulation.agents.player import PlayerAgent
from football_simulation.agents.possession import PossessionAgent
from football_simulation.agents.probability import (
    GoalsOUProbabilityAgent,
    HTFTProbabilityAgent,
    ResultProbabilityAgent,
    ScoreProbabilityAgent,
)
from football_simulation.agents.psychology import PsychologyAgent
from football_simulation.agents.referee import RefereeAgent
from football_simulation.agents.risk import ConfidenceAgent, RiskAgent, UpsetRiskAgent
from football_simulation.agents.space import SpaceAgent
from football_simulation.agents.substitution import SubstitutionAgent
from football_simulation.agents.tactical import TacticalMatchupAgent
from football_simulation.agents.team import TeamAgent
from football_simulation.core.event_engine import EventTriggerAgent
from football_simulation.core.rule_engine import RuleEngine
from football_simulation.core.scenario_engine import MatchScriptAgent, ScenarioRankingAgent
from football_simulation.core.simulation_engine import MatchSimulationEngine, SimulationConfig
from football_simulation.core.state_machine import StateTransitionAgent
from football_simulation.data.provider import DataProvider, PreMatchFreeze
from football_simulation.knowledge.loader import load_all_knowledge
from football_simulation.models.base import (
    AgentOpinion,
    AgentResult,
    ImpactLevel,
    ReasoningStep,
    RiskLevel,
    Side,
)
from football_simulation.models.report import (
    ConfidenceReport,
    DataQualityReport,
    FailureCondition,
    MatchInfo,
    MatchPredictionReport,
    ResultProbability,
)
from football_simulation.models.scenario import ScenarioRanking
from football_simulation.models.entities import CoachState, PlayerState, TeamState
from football_simulation.models.world import (
    PsychologicalState,
    RefereeMatchState,
    TacticalMatchupState,
    WeatherState,
    WorldState,
)


class DirectorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    simulation_runs: int = 10000
    seed: int = 12345
    keep_events: bool = False
    run_convergence: bool = False
    run_counterfactuals: bool = False
    counterfactual_runs: int = 2000
    freeze: bool = True
    convergence_threshold: float = 0.005
    convergence_runs: List[int] = Field(default_factory=lambda: [1000, 5000, 10000, 50000])
    # V1.1 ablation switches (measurement only - not gameplay features)
    disabled_agents: List[str] = Field(default_factory=list)
    enable_scenarios: bool = True


class DirectorAgent(BaseAgent[MatchPredictionReport]):
    name = "DirectorAgent"
    description = "Orchestrates the complete analyze -> simulate -> report pipeline."

    def __init__(self, provider: DataProvider, config: Optional[DirectorConfig] = None):
        self.provider = provider
        self.config = config or DirectorConfig()
        self.knowledge = load_all_knowledge()
        self.trace: List[ReasoningStep] = []
        self._seq = 0

        # agent instances (stateless; created once)
        self.team_agent = TeamAgent()
        self.coach_agent = CoachAgent()
        self.player_agent = PlayerAgent()
        self.lineup_agent = LineupAgent()
        self.fitness_agent = FitnessAgent()
        self.psychology_agent = PsychologyAgent()
        self.environment_agent = EnvironmentAgent()
        self.referee_agent = RefereeAgent()
        self.tactical_agent = TacticalMatchupAgent()
        self.opening_agent = OpeningAgent()
        self.space_agent = SpaceAgent()
        self.possession_agent = PossessionAgent()
        self.substitution_agent = SubstitutionAgent()
        self.momentum = MomentumAgent()
        self.result_agent = ResultProbabilityAgent()
        self.score_agent = ScoreProbabilityAgent()
        self.goals_agent = GoalsOUProbabilityAgent()
        self.htft_agent = HTFTProbabilityAgent()
        self.script_agent = MatchScriptAgent()
        self.ranking_agent = ScenarioRankingAgent()
        self.upset_agent = UpsetRiskAgent()
        self.risk_agent = RiskAgent()
        self.confidence_agent = ConfidenceAgent()
        self.explanation_agent = ExplanationAgent()
        self.counterfactual_agent = CounterfactualAgent()
        self.fusion = OpinionFusionLayer()

    # ------------------------------------------------------------------
    def _step(self, kind: str, summary: str, detail: str = "", **kw: Any) -> None:
        self._seq += 1
        self.trace.append(
            ReasoningStep(sequence=self._seq, kind=kind, summary=summary, detail=detail, **kw)
        )

    # ------------------------------------------------------------------
    def prepare_world(self, match_id: str, disabled_agents: Optional[set] = None):
        """Run the full pre-match agent chain and return the WorldState.

        ``disabled_agents`` (ablation studies): any agent named in this set is
        skipped and its output replaced by a NEUTRAL default, so its marginal
        contribution can be measured.  This is a measurement instrument, not a
        gameplay feature.

        Returns (context, world, matchup, agreement, data_quality, lineup_certainty).
        """
        disabled = set(disabled_agents or ())
        request = self.provider.get_match_request(match_id)
        data = PreMatchFreeze(self.provider)
        if self.config.freeze:
            data.freeze(request.kickoff)
        self._step(
            "data",
            "data loaded & frozen",
            f"freeze={self.config.freeze}, cutoff={request.kickoff.isoformat()}",
        )

        context = AgentContext(
            match_id=match_id,
            request=request,
            data=data,
            knowledge={
                "rules": self.knowledge["rules"],
                "tactical_patterns": self.knowledge["tactical_patterns"],
                "event_defaults": self.knowledge["event_defaults"],
            },
        )

        if "Team" in disabled:
            home_profile = data.get_team_data(request.home_team_id)
            away_profile = data.get_team_data(request.away_team_id)
            home_team_state = self._neutral_team_state(home_profile)
            away_team_state = self._neutral_team_state(away_profile)
            self._step("agent_decision", "TeamAgent DISABLED (neutral states)",
                       agent_name="TeamAgent")
        else:
            team_result = self.team_agent.run(context)
            teams = team_result.output or {}
            home_team_state = teams.get("home")
            away_team_state = teams.get("away")
            if home_team_state is None or away_team_state is None:
                raise RuntimeError(f"TeamAgent failed: {team_result.warnings}")
            self._step("agent_decision", "TeamAgent built team states",
                       team_result.reasoning, agent_name="TeamAgent",
                       confidence=team_result.confidence)

        world = WorldState(
            match_id=match_id,
            competition=request.competition_id,
            season=request.season,
            kickoff=request.kickoff,
            as_of=request.as_of,
            home_team=request.home_team_id,
            away_team=request.away_team_id,
            home_team_state=home_team_state,
            away_team_state=away_team_state,
        )
        context.world = world
        context.input_version = world.state_version

        if "Coach" in disabled:
            world = world.evolution_snapshot(
                home_coach=CoachState(coach_id=f"neutral-{request.home_team_id}"),
                away_coach=CoachState(coach_id=f"neutral-{request.away_team_id}"),
            )
            context.world = world
            self._step("agent_decision", "CoachAgent DISABLED (neutral coaches)",
                       agent_name="CoachAgent")
        else:
            coach_result = self.coach_agent.run(context)
            coaches = coach_result.output or {}
            world = world.evolution_snapshot(
                home_coach=coaches.get("home"), away_coach=coaches.get("away")
            )
            context.world = world
            self._step("agent_decision", "CoachAgent gameplans", coach_result.reasoning,
                       agent_name="CoachAgent", confidence=coach_result.confidence)

        if "Fitness" in disabled:
            fitness = {}
            self._step("agent_decision", "FitnessAgent DISABLED (no fatigue)",
                       agent_name="FitnessAgent")
        else:
            fitness_result = self.fitness_agent.run(context)
            fitness = fitness_result.output or {}
            self._step("agent_decision", "FitnessAgent fatigue model",
                       "; ".join(fitness_result.evidence[:2]), agent_name="FitnessAgent",
                       confidence=fitness_result.confidence)

        if "Player" in disabled:
            home_profiles = data.get_player_data(request.home_team_id)
            away_profiles = data.get_player_data(request.away_team_id)
            all_players = {
                p.player_id: self._neutral_player_state(p) for p in home_profiles + away_profiles
            }
            self._step("agent_decision", "PlayerAgent DISABLED (neutral players)",
                       agent_name="PlayerAgent")
        else:
            player_result = self.player_agent.run(context)
            all_players = player_result.output or {}
        if not all_players:
            # UNKNOWN player data (e.g. historical backtest sources): use
            # clearly-flagged NEUTRAL placeholder squads.  This keeps the
            # pipeline structurally complete without inventing player skill.
            home_profiles = data.get_player_data(request.home_team_id)
            away_profiles = data.get_player_data(request.away_team_id)
            if not home_profiles and not away_profiles:
                all_players = {
                    **self._unknown_squad(request.home_team_id),
                    **self._unknown_squad(request.away_team_id),
                }
                self._step(
                    "agent_decision",
                    "PlayerAgent NO_SIGNAL (player data unknown - neutral placeholder squads)",
                    agent_name="PlayerAgent",
                    warnings=["player data unknown for both teams; placeholder squads used"],
                )
        home_players = {pid: p for pid, p in all_players.items() if p.team_id == request.home_team_id}
        away_players = {pid: p for pid, p in all_players.items() if p.team_id == request.away_team_id}
        if "home" in fitness:
            for pid, f in fitness["home"].per_player_fatigue.items():
                if pid in home_players:
                    home_players[pid] = home_players[pid].model_copy(update={"current_fatigue": f})
        if "away" in fitness:
            for pid, f in fitness["away"].per_player_fatigue.items():
                if pid in away_players:
                    away_players[pid] = away_players[pid].model_copy(update={"current_fatigue": f})
        world = world.evolution_snapshot(
            home_players=home_players,
            away_players=away_players,
            fatigue_home=fitness.get("home").fatigue_score if fitness.get("home") else 0.0,
            fatigue_away=fitness.get("away").fatigue_score if fitness.get("away") else 0.0,
        )
        context.world = world

        lineup_result = self.lineup_agent.run(context)
        lineups = lineup_result.output or {}
        home_lineup = lineups.get("home", {}).get("lineup")
        away_lineup = lineups.get("away", {}).get("lineup")
        if home_lineup is not None:
            home_players = {
                pid: p.model_copy(update={"starting": pid in home_lineup.starters})
                for pid, p in home_players.items()
            }
        if away_lineup is not None:
            away_players = {
                pid: p.model_copy(update={"starting": pid in away_lineup.starters})
                for pid, p in away_players.items()
            }
        world = world.evolution_snapshot(
            home_players=home_players,
            away_players=away_players,
            home_lineup=home_lineup,
            away_lineup=away_lineup,
        )
        context.world = world
        self._step("agent_decision", "LineupAgent resolved lineups",
                   "; ".join(lineup_result.evidence[:4]), agent_name="LineupAgent",
                   confidence=lineup_result.confidence, warnings=lineup_result.warnings)

        psych_result = self.psychology_agent.run(context) if "Psychology" not in disabled else None
        psych = psych_result.output if psych_result is not None else None
        world = world.evolution_snapshot(
            home_psychological_state=psych.get("home") if psych else PsychologicalState(side=Side.HOME),
            away_psychological_state=psych.get("away") if psych else PsychologicalState(side=Side.AWAY),
        )
        context.world = world
        if "Psychology" in disabled:
            self._step("agent_decision", "PsychologyAgent DISABLED (neutral psychology)",
                       agent_name="PsychologyAgent")

        if "Environment" in disabled:
            world = world.evolution_snapshot(weather_state=WeatherState(known=False))
            context.world = world
            self._step("agent_decision", "EnvironmentAgent DISABLED (no weather effects)",
                       agent_name="EnvironmentAgent")
        else:
            env_result = self.environment_agent.run(context)
            if env_result.output is not None:
                world = world.evolution_snapshot(weather_state=env_result.output)
                context.world = world

        if "Referee" in disabled:
            world = world.evolution_snapshot(referee_state=RefereeMatchState(known=False))
            context.world = world
            self._step("agent_decision", "RefereeAgent DISABLED (neutral referee)",
                       agent_name="RefereeAgent")
        else:
            referee_result = self.referee_agent.run(context)
            if referee_result.output is not None:
                world = world.evolution_snapshot(referee_state=referee_result.output)
                context.world = world

        if "Tactical" in disabled:
            matchup = TacticalMatchupState()
            self._step("agent_decision", "TacticalMatchupAgent DISABLED (neutral matchup)",
                       agent_name="TacticalMatchupAgent")
        else:
            matchup_result = self.tactical_agent.run(context)
            matchup = matchup_result.output
            if matchup is None:
                matchup = TacticalMatchupState()
            self._step("agent_decision", "TacticalMatchupAgent analyzed the matchup",
                       matchup.analysis, agent_name="TacticalMatchupAgent",
                       confidence=matchup_result.confidence)
        context.matchup = matchup
        world = world.evolution_snapshot(matchup_state=matchup)
        context.world = world

        opening_result = self.opening_agent.run(context)
        opening = opening_result.output
        world = self._apply_opening_to_world(world, opening, matchup)
        context.world = world
        self._step("agent_decision", "OpeningAgent opening phase", opening.description if opening else "",
                   agent_name="OpeningAgent")

        zones = self.space_agent.analyze(world, matchup)
        world = world.evolution_snapshot(dangerous_spaces=zones)
        context.world = world

        opinions = self._collect_opinions(context)
        fused = self.fusion.fuse_all(opinions)
        agreement = fused.get("home_strength_advantage", {}).get("agreement", 0.5)
        self._step("fusion", "opinion fusion",
                   f"agreement={agreement:.2f}, opinions={len(opinions)}")

        dq = data.data_quality(request)
        lineup_certainty = 1.0 if (world.home_lineup and world.home_lineup.confirmed and
                                   world.away_lineup and world.away_lineup.confirmed) else 0.5
        return context, world, matchup, agreement, dq, lineup_certainty

    # ------------------------------------------------------------------
    @staticmethod
    def _neutral_team_state(profile) -> TeamState:
        return TeamState(team_id=profile.team_id, name=profile.name)

    @staticmethod
    def _neutral_player_state(profile) -> PlayerState:
        return PlayerState(
            player_id=profile.player_id, name=profile.name, team_id=profile.team_id,
            age=profile.age, position=profile.position, preferred_side=profile.preferred_side,
        )

    @staticmethod
    def _unknown_squad(team_id: str, size: int = 22) -> Dict[str, PlayerState]:
        """Neutral placeholder squad for UNKNOWN player data (NO_SIGNAL)."""
        from football_simulation.models.entities import Position
        positions = [
            Position.GK, Position.CB, Position.CB, Position.LB, Position.RB,
            Position.DM, Position.CM, Position.CM, Position.AM, Position.LW, Position.RW,
            Position.ST, Position.GK, Position.CB, Position.DM, Position.CM,
            Position.AM, Position.LW, Position.RW, Position.ST, Position.CB, Position.ST,
        ]
        squad: Dict[str, PlayerState] = {}
        for i in range(size):
            position = positions[i % len(positions)]
            pid = f"unknown-{team_id}-{i:02d}"
            squad[pid] = PlayerState(
                player_id=pid, name="UNKNOWN", team_id=team_id, position=position,
                starting=i < 11,
            )
        return squad

    # ------------------------------------------------------------------
    def analyze(self, match_id: str) -> MatchPredictionReport:
        started = time.time()
        self.trace = []
        self._seq = 0

        disabled = set(self.config.disabled_agents or ())
        context, world, matchup, agreement, dq, lineup_certainty = self.prepare_world(
            match_id, disabled_agents=disabled
        )

        # ---- simulation engine -------------------------------------------
        rule_engine = RuleEngine(self.knowledge["rules"])
        state_machine = StateTransitionAgent(rule_engine, self.momentum)
        event_agent = EventTriggerAgent(self.knowledge["event_defaults"])
        engine = MatchSimulationEngine(
            world, rule_engine, self.momentum, event_agent,
            self.substitution_agent, state_machine, matchup,
            SimulationConfig(
                default_runs=self.config.simulation_runs,
                keep_events=self.config.keep_events,
                convergence_threshold=self.config.convergence_threshold,
                convergence_runs=self.config.convergence_runs,
                enable_momentum="Momentum" not in disabled,
            ),
        )
        batch = engine.simulate_n_matches(n=self.config.simulation_runs, base_seed=self.config.seed)
        self._step("simulation", "Monte Carlo batch complete",
                   f"runs={batch.runs}, seed={self.config.seed}, "
                   f"top score shares={_top_scores(batch)}")

        # ---- probability agents ------------------------------------------
        context.batch = batch
        result_probability = self.result_agent.run(context).output
        score_matrix = self.score_agent.run(context).output
        goals, btts = self.goals_agent.compute(batch)
        htft = self.htft_agent.compute(batch)
        self._step("probability", "probability agents complete",
                   f"1X2: {result_probability.home_win:.3f}/{result_probability.draw:.3f}/{result_probability.away_win:.3f}")

        # ---- scenarios ----------------------------------------------------
        if self.config.enable_scenarios and "Scenario" not in disabled:
            scenarios = self.script_agent.build_scenarios(batch, match_id)
            ranking = self.ranking_agent.rank(scenarios)
            scenario_probs = [s.probability for s in ranking.scenarios[:8]]
            concentration = sum(p * p for p in scenario_probs) if scenario_probs else 0.0
            scenario_divergence = max(0.0, min(1.0, 1.0 - (concentration - 0.05) / 0.3))
            self._step("scenario", "scenarios ranked",
                       f"top={ranking.scenarios[0].name if ranking.scenarios else '-'} "
                       f"({ranking.scenarios[0].probability:.3f} if ranking.scenarios else 0), "
                       f"long tail={ranking.long_tail_probability:.3f}")
        else:
            from football_simulation.models.scenario import ScenarioRanking
            ranking = ScenarioRanking()
            scenario_probs = []
            scenario_divergence = 0.3  # neutral when scenario layer is off
            self._step("scenario", "Scenario layer DISABLED (ablation)")

        # ---- risk / confidence --------------------------------------------
        context.knowledge = {**context.knowledge, "result_probability": result_probability}
        upset = self.upset_agent.run(context).output
        model_uncertainty = 0.35 * (1 - dq.completeness) + 0.35 * (1 - agreement) + 0.15
        risk = self.risk_agent.compute(world, min(1.0, model_uncertainty), scenario_divergence, dq)
        confidence = self.confidence_agent.compute(
            scenario_probs, dq, agreement, lineup_certainty, result_probability
        )
        self._step("risk", "risk & confidence complete",
                   f"upset={upset.level.value} risk={risk.overall_risk.value} confidence={confidence.level.value}")

        # ---- failure conditions --------------------------------------------
        failure_conditions = self._failure_conditions(world, upset, dq)

        # ---- counterfactuals (optional) ------------------------------------
        counterfactuals = []
        if self.config.run_counterfactuals and "Counterfactual" not in disabled:
            single = engine.simulate_match(seed=self.config.seed)
            key_events = [e for e in single.events if e.event_type.value in
                          ("goal", "red_card", "second_yellow", "injury")][:3]
            self.counterfactual_agent.set_engine(engine)
            baseline = result_probability.model_dump()
            counterfactuals = self.counterfactual_agent.run_counterfactual(
                match_id, baseline, key_events, self.config.counterfactual_runs, self.config.seed + 7
            )
            self._step("counterfactual", "counterfactuals complete", f"{len(counterfactuals)} what-ifs")

        # ---- convergence (optional) -----------------------------------------
        convergence = None
        if self.config.run_convergence:
            convergence = engine.convergence_analysis(base_seed=self.config.seed)
            self._step("simulation", "convergence analysis",
                       f"converged={convergence.converged}, max_delta={convergence.max_delta}")

        # ---- explanation ------------------------------------------------------
        context.knowledge = {
            **context.knowledge,
            "scenarios": ranking.scenarios,
            "upset_risk": upset,
            "risk": risk,
            "confidence": confidence,
            "failure_conditions": [f.condition for f in failure_conditions],
        }
        explanation = self.explanation_agent.run(context).output or ""

        report = MatchPredictionReport(
            match=MatchInfo(
                match_id=match_id,
                home=world.home_team_state.name if world.home_team_state else world.home_team,
                away=world.away_team_state.name if world.away_team_state else world.away_team,
                competition=context.request.competition_id,
                season=context.request.season,
                kickoff=context.request.kickoff,
            ),
            result_probability=result_probability,
            score_probability=score_matrix,
            goals_probability=goals,
            btts=btts,
            half_time_full_time=htft,
            scenarios=ranking.scenarios,
            scenario_ranking={
                "long_tail_probability": ranking.long_tail_probability,
                "long_tail_count": ranking.long_tail_count,
            },
            upset_risk=upset,
            risk=risk,
            confidence=confidence,
            failure_conditions=failure_conditions,
            explanation=explanation,
            data_quality=DataQualityReport(
                completeness=dq.completeness,
                unknowns=dq.unknowns,
                lineup_confirmed=dq.lineup_confirmed,
                notes=dq.notes,
            ),
            convergence=convergence,
            counterfactuals=counterfactuals,
            trace=[s.model_dump() for s in self.trace],
            simulation_runs=batch.runs,
            seed=self.config.seed,
        )
        self._step("report", "final report assembled", f"elapsed {time.time() - started:.1f}s")
        report.trace = [s.model_dump() for s in self.trace]
        return report

    # ------------------------------------------------------------------
    def _apply_opening_to_world(self, world: WorldState, opening, matchup) -> WorldState:
        if opening is None:
            return world
        home_tac = world.home_tactical_state.model_copy(
            update={
                "pressing_intensity": opening.pressing_intensity_home,
                "chance_creation_modifier": matchup.chance_creation_home,
                "counter_strength_current": (world.home_team_state.counter_attack_strength
                                             if world.home_team_state else 0.5),
                "transition_risk": matchup.transition_risk_home,
                "pressing_success_probability": matchup.pressing_success_home,
            }
        )
        away_tac = world.away_tactical_state.model_copy(
            update={
                "pressing_intensity": opening.pressing_intensity_away,
                "chance_creation_modifier": matchup.chance_creation_away,
                "counter_strength_current": (world.away_team_state.counter_attack_strength
                                             if world.away_team_state else 0.5),
                "transition_risk": matchup.transition_risk_away,
                "pressing_success_probability": matchup.pressing_success_away,
            }
        )
        flags = dict(world.trigger_flags.flags)
        flags["opening_home"] = opening.early_chance_modifier_home
        flags["opening_away"] = opening.early_chance_modifier_away
        return world.evolution_snapshot(
            home_tactical_state=home_tac,
            away_tactical_state=away_tac,
            trigger_flags=world.trigger_flags.model_copy(update={"flags": flags}),
        )

    def _collect_opinions(self, context: AgentContext) -> List[AgentOpinion]:
        world = context.world
        opinions: List[AgentOpinion] = []
        if world.home_team_state and world.away_team_state:
            h = world.home_team_state
            a = world.away_team_state
            opinions.append(AgentOpinion(
                agent_name="TeamAgent", subject="home_strength_advantage",
                value=max(-1.0, min(1.0, (h.attack_strength + h.defense_strength - a.attack_strength - a.defense_strength))),
                confidence=0.7, impact=ImpactLevel.HIGH, match_id=context.match_id,
                evidence=[f"{h.name} att {h.attack_strength:.2f} def {h.defense_strength:.2f}",
                          f"{a.name} att {a.attack_strength:.2f} def {a.defense_strength:.2f}"],
                reasoning="squad strength differential",
            ))
        if world.matchup_state is not None:
            opinions.append(AgentOpinion(
                agent_name="TacticalMatchupAgent", subject="home_strength_advantage",
                value=world.matchup_state.tactical_advantage_home,
                confidence=0.65, impact=ImpactLevel.HIGH, match_id=context.match_id,
                evidence=world.matchup_state.pattern_names,
                reasoning="tactical matchup advantage",
            ))
        opinions.append(AgentOpinion(
            agent_name="FitnessAgent", subject="home_strength_advantage",
            value=max(-1.0, min(1.0, 0.5 * (world.fatigue_away - world.fatigue_home))),
            confidence=0.6, impact=ImpactLevel.MEDIUM, match_id=context.match_id,
            evidence=[f"fatigue home {world.fatigue_home:.2f} away {world.fatigue_away:.2f}"],
            reasoning="freshness differential",
        ))
        opinions.append(AgentOpinion(
            agent_name="PsychologyAgent", subject="home_strength_advantage",
            value=max(-1.0, min(1.0, 0.4 * (world.home_psychological_state.confidence
                                            - world.away_psychological_state.confidence))),
            confidence=0.5, impact=ImpactLevel.MEDIUM, match_id=context.match_id,
            evidence=[], reasoning="confidence differential",
        ))
        return opinions

    def _failure_conditions(self, world: WorldState, upset, dq) -> List[FailureCondition]:
        conditions: List[FailureCondition] = []
        if world.home_lineup and not world.home_lineup.confirmed:
            conditions.append(FailureCondition(
                condition="主队首发名单未确认，若核心球员缺阵将显著改变攻防结构",
                impact="lineup", severity=RiskLevel.HIGH,
            ))
        if world.away_lineup and not world.away_lineup.confirmed:
            conditions.append(FailureCondition(
                condition="客队首发名单未确认，若核心球员缺阵将显著改变攻防结构",
                impact="lineup", severity=RiskLevel.HIGH,
            ))
        if world.matchup_state is not None and world.matchup_state.transition_risk_home > 0.6:
            conditions.append(FailureCondition(
                condition="若客队摆出低位防守并专注反击，主队高位防线将被惩罚",
                impact="tactical", severity=RiskLevel.MEDIUM,
            ))
        if world.matchup_state is not None and world.matchup_state.transition_risk_away > 0.6:
            conditions.append(FailureCondition(
                condition="若主队低位反击战术奏效，客队压上将被惩罚",
                impact="tactical", severity=RiskLevel.MEDIUM,
            ))
        conditions.append(FailureCondition(
            condition="若任一球队30分钟内被罚下，比赛结构将彻底改变",
            impact="red_card", severity=RiskLevel.HIGH,
        ))
        if not world.weather_state.known:
            conditions.append(FailureCondition(
                condition="天气数据缺失：极端天气可能改变节奏与机会质量",
                impact="weather", severity=RiskLevel.MEDIUM,
            ))
        if upset.level in (RiskLevel.HIGH, RiskLevel.VERY_HIGH):
            conditions.append(FailureCondition(
                condition=f"爆冷情景({upset.direction})概率达到 {upset.probability:.0%}，需警惕结构性驱动因素",
                impact="upset", severity=upset.level,
            ))
        return conditions[:6]

    # ------------------------------------------------------------------
    def run(self, context: AgentContext) -> AgentResult[MatchPredictionReport]:
        report = self.analyze(context.match_id)
        return AgentResult(
            agent_name=self.name,
            match_id=context.match_id,
            input_version=context.world_version(),
            output=report,
            confidence=report.confidence.score,
            evidence=[f"simulations={report.simulation_runs}",
                      f"1X2 {report.result_probability.home_win:.3f}/{report.result_probability.draw:.3f}/{report.result_probability.away_win:.3f}"],
            reasoning="Full pipeline: agents -> world model -> scenarios -> Monte Carlo -> probabilities -> risk -> explanation.",
        )


def _top_scores(batch) -> str:
    counts = batch.score_counts()
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:3]
    return ", ".join(f"{k}:{v / batch.runs:.3f}" for k, v in top)
