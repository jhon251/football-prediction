"""Risk layer agents: Upset Risk, decomposed Risk, Confidence.

Upset is defined RELATIVE to the pre-match probabilities - never simply
"weak team winning" (spec sections 32-34).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from football_simulation.agents.base import AgentContext, BaseAgent
from football_simulation.models.base import AgentResult, ConfidenceLevel, RiskLevel
from football_simulation.models.data import DataQualityInfo
from football_simulation.models.report import (
    ConfidenceReport,
    ResultProbability,
    RiskComponent,
    RiskReport,
    UpsetRiskReport,
)
from football_simulation.models.world import WorldState


class UpsetRiskAgent(BaseAgent[UpsetRiskReport]):
    name = "UpsetRiskAgent"
    description = "Upset probability/direction/severity relative to pre-match odds."

    def compute(
        self,
        result: ResultProbability,
        world: Optional[WorldState],
        drivers: List[str],
    ) -> UpsetRiskReport:
        p_home = result.home_win
        p_draw = result.draw
        p_away = result.away_win

        favourite = "home" if p_home >= p_away else "away"
        p_fav = max(p_home, p_away)
        p_dog = min(p_home, p_away)

        if p_fav < 0.40:
            # genuinely open game: no real favourite -> upset risk is low, but
            # still report the marginal direction for the user.
            upset_direction = "away_win" if favourite == "home" else "home_win"
            severity = round(min(1.0, (p_fav - p_dog) * 1.6), 3)
            return UpsetRiskReport(
                level=RiskLevel.LOW,
                probability=round(p_dog, 4),
                direction=upset_direction,
                upset_type="open_game",
                severity=severity,
                drivers=[],
            )

        upset_probability = p_dog
        upset_direction = "away_win" if favourite == "home" else "home_win"
        severity = round(min(1.0, (p_fav - p_dog) * 1.6), 3)

        # Severity dominates the level (how big a shock an upset would be),
        # but a truly tiny upset probability cannot be "very high" risk.
        if severity >= 0.65:
            level = RiskLevel.VERY_HIGH
        elif severity >= 0.45:
            level = RiskLevel.HIGH
        elif severity >= 0.25:
            level = RiskLevel.MEDIUM
        else:
            level = RiskLevel.LOW
        if upset_probability < 0.08 and level is RiskLevel.VERY_HIGH:
            level = RiskLevel.HIGH
        if upset_probability < 0.03 and level is RiskLevel.HIGH:
            level = RiskLevel.MEDIUM

        upset_type = "upset" if upset_probability < 0.20 else "moderate_surprise"

        return UpsetRiskReport(
            level=level,
            probability=round(upset_probability, 4),
            direction=upset_direction,
            upset_type=upset_type,
            severity=severity,
            drivers=drivers,
        )

    def drivers(self, world: WorldState) -> List[str]:
        out: List[str] = []
        home_lineup = world.home_lineup
        away_lineup = world.away_lineup
        if home_lineup and home_lineup.key_absences:
            out.append(f"主队缺阵: {', '.join(home_lineup.key_absences[:3])}")
        if away_lineup and away_lineup.key_absences:
            out.append(f"客队缺阵: {', '.join(away_lineup.key_absences[:3])}")
        matchup = world.matchup_state
        if matchup is not None:
            if matchup.transition_risk_home > 0.6:
                out.append("主队高位防线暴露在客队反击之下")
            if matchup.transition_risk_away > 0.6:
                out.append("客队防线暴露在主队反击之下")
            if matchup.set_piece_xg_bonus_away > 0.02:
                out.append("客队定位球优势可能制造意外")
            if matchup.set_piece_xg_bonus_home > 0.02:
                out.append("主队定位球优势可能制造意外")
        if world.fatigue_home > 0.45:
            out.append("主队体能负担较高(密集赛程)")
        if world.fatigue_away > 0.45:
            out.append("客队体能负担较高(密集赛程)")
        if not world.weather_state.known:
            out.append("天气数据缺失可能影响判断")
        return out[:5]

    def run(self, context: AgentContext) -> AgentResult[UpsetRiskReport]:
        if context.knowledge is None or not isinstance(context.knowledge, dict):
            return self.fail(context, "missing knowledge")
        result = context.knowledge.get("result_probability")
        world = context.world
        if result is None:
            return self.fail(context, "missing result probability")
        drivers = self.drivers(world) if world else []
        report = self.compute(result, world, drivers)
        return self.ok(
            context,
            report,
            confidence=0.75,
            evidence=[f"favourite win prob {max(result.home_win, result.away_win):.3f}",
                      f"upset prob {report.probability:.3f} severity {report.severity:.2f}"] + drivers,
            reasoning="Upset risk is defined relative to the model's own pre-match probabilities.",
        )


class RiskAgent(BaseAgent[RiskReport]):
    name = "RiskAgent"
    description = "Decomposed risk: lineup/injury/fatigue/tactical/psychology/referee/weather/model/data."

    def compute(
        self,
        world: WorldState,
        model_uncertainty: float,
        scenario_divergence: float,
        data_quality: Optional[DataQualityInfo],
    ) -> RiskReport:
        components: List[RiskComponent] = []

        lineup_risk = 0.0
        reasons: List[str] = []
        for lineup, label in ((world.home_lineup, "home"), (world.away_lineup, "away")):
            if lineup is None:
                continue
            if not lineup.confirmed:
                lineup_risk = max(lineup_risk, 0.6)
                reasons.append(f"{label} lineup unconfirmed")
            if lineup.key_absences:
                lineup_risk = max(lineup_risk, 0.55)
                reasons.append(f"{label} key absences: {', '.join(lineup.key_absences[:2])}")
            if lineup.backup_goalkeeper:
                lineup_risk = max(lineup_risk, 0.4)
                reasons.append(f"{label} backup goalkeeper")
        components.append(RiskComponent(name="lineup", level=_level(lineup_risk), score=round(lineup_risk, 2), reasons=reasons))

        injury_risk = 0.0
        injury_reasons: List[str] = []
        if world.injury_state.injuries:
            injury_risk = 0.5
            injury_reasons = [f"{len(world.injury_state.injuries)} in-match injuries"]
        pre = world.injury_state.pre_match_absent
        total_absent = sum(len(v) for v in pre.values())
        if total_absent:
            injury_risk = max(injury_risk, 0.5)
            injury_reasons.append(f"{total_absent} players ruled out pre-match")
        components.append(RiskComponent(name="injury", level=_level(injury_risk), score=round(injury_risk, 2), reasons=injury_reasons))

        fatigue_risk = 0.5 * (world.fatigue_home + world.fatigue_away)
        fatigue_reasons = [f"home fatigue {world.fatigue_home:.2f}, away fatigue {world.fatigue_away:.2f}"]
        components.append(RiskComponent(name="fatigue", level=_level(fatigue_risk), score=round(fatigue_risk, 2), reasons=fatigue_reasons))

        matchup = world.matchup_state
        tactical_risk = 0.0
        tactical_reasons: List[str] = []
        if matchup is not None:
            tactical_risk = max(matchup.transition_risk_home, matchup.transition_risk_away) * 0.5
            if tactical_risk > 0.3:
                tactical_reasons.append("transition exposure on at least one side")
            if len(matchup.pattern_names) == 0:
                tactical_reasons.append("no clear tactical pattern identified (uncertainty)")
        components.append(RiskComponent(name="tactical", level=_level(tactical_risk), score=round(tactical_risk, 2), reasons=tactical_reasons))

        psych_risk = 0.0
        psych_reasons: List[str] = []
        for psy, label in ((world.home_psychological_state, "home"), (world.away_psychological_state, "away")):
            if psy.pressure > 0.7:
                psych_risk = max(psych_risk, 0.5)
                psych_reasons.append(f"{label} under high pressure ({psy.pressure:.2f})")
        components.append(RiskComponent(name="psychological", level=_level(psych_risk), score=round(psych_risk, 2), reasons=psych_reasons))

        referee_risk = 0.0
        referee_reasons: List[str] = []
        if not world.referee_state.known:
            referee_risk = 0.55
            referee_reasons.append("referee unknown")
        else:
            if world.referee_state.red_card_tendency > 0.6:
                referee_risk = max(referee_risk, 0.4)
                referee_reasons.append("referee has high red-card tendency")
            if world.referee_state.penalty_tendency > 0.6:
                referee_risk = max(referee_risk, 0.35)
                referee_reasons.append("referee has high penalty tendency")
        components.append(RiskComponent(name="referee", level=_level(referee_risk), score=round(referee_risk, 2), reasons=referee_reasons))

        weather_risk = 0.0
        weather_reasons: List[str] = []
        ws = world.weather_state
        if not ws.known:
            weather_risk = 0.4
            weather_reasons.append("weather unknown")
        elif ws.impact == "high":
            weather_risk = 0.45
            weather_reasons = ws.notes
        elif ws.impact == "medium":
            weather_risk = 0.25
            weather_reasons = ws.notes
        components.append(RiskComponent(name="weather", level=_level(weather_risk), score=round(weather_risk, 2), reasons=weather_reasons))

        components.append(RiskComponent(
            name="model_uncertainty",
            level=_level(model_uncertainty),
            score=round(model_uncertainty, 2),
            reasons=["uncertainty from simulation spread / agent disagreement"],
        ))
        components.append(RiskComponent(
            name="scenario_divergence",
            level=_level(scenario_divergence),
            score=round(scenario_divergence, 2),
            reasons=["scenarios highly dispersed"] if scenario_divergence > 0.5 else [],
        ))
        dq = data_quality
        dq_risk = 1.0 - dq.completeness if dq is not None else 0.5
        components.append(RiskComponent(
            name="data_quality",
            level=_level(dq_risk),
            score=round(dq_risk, 2),
            reasons=dq.unknowns[:3] if dq is not None else ["no data quality info"],
        ))

        weights = {"lineup": 0.16, "injury": 0.12, "fatigue": 0.10, "tactical": 0.14,
                   "psychological": 0.08, "referee": 0.10, "weather": 0.08,
                   "model_uncertainty": 0.10, "scenario_divergence": 0.06, "data_quality": 0.06}
        overall = sum(weights.get(c.name, 0.05) * c.score for c in components)
        return RiskReport(
            overall_risk=_level(overall),
            overall_score=round(overall, 3),
            components=components,
        )

    def run(self, context: AgentContext) -> AgentResult[RiskReport]:
        world = context.world
        if world is None:
            return self.fail(context, "missing world state")
        extra = context.knowledge if isinstance(context.knowledge, dict) else {}
        model_uncertainty = extra.get("model_uncertainty", 0.3)
        scenario_divergence = extra.get("scenario_divergence", 0.3)
        data_quality = extra.get("data_quality")
        report = self.compute(world, model_uncertainty, scenario_divergence, data_quality)
        return self.ok(
            context,
            report,
            confidence=0.7,
            evidence=[f"{c.name}: {c.score:.2f} ({c.level.value})" for c in report.components],
            reasoning="Risk decomposed into 10 components with per-component reasons.",
        )


class ConfidenceAgent(BaseAgent[ConfidenceReport]):
    name = "ConfidenceAgent"
    description = "Confidence from scenario concentration, data completeness, agent agreement and more."

    def compute(
        self,
        scenario_probs: List[float],
        data_quality: Optional[DataQualityInfo],
        agent_agreement: float,
        lineup_certainty: float,
        result: Optional[ResultProbability] = None,
    ) -> ConfidenceReport:
        # scenario concentration: herfindahl of top scenarios
        hhi = sum(p * p for p in scenario_probs) if scenario_probs else 0.0
        concentration = max(0.0, min(1.0, (hhi - 0.04) / 0.3))
        completeness = data_quality.completeness if data_quality else 0.5

        margin = 0.0
        if result is not None:
            margin = max(result.home_win, result.draw, result.away_win) - sorted(
                [result.home_win, result.draw, result.away_win]
            )[1]
        margin_component = max(0.0, min(1.0, margin / 0.25))

        score = (
            0.30 * concentration
            + 0.25 * completeness
            + 0.15 * agent_agreement
            + 0.15 * lineup_certainty
            + 0.15 * margin_component
        )
        reasons = [
            f"scenario concentration {concentration:.2f}",
            f"data completeness {completeness:.2f}",
            f"agent agreement {agent_agreement:.2f}",
            f"lineup certainty {lineup_certainty:.2f}",
            f"result margin component {margin_component:.2f}",
        ]
        if concentration < 0.35:
            reasons.append("scenarios highly dispersed - even a solid 1X2 share may hide uncertainty")
        if completeness < 0.6:
            reasons.append("significant unknown data lowers confidence")

        level = (
            ConfidenceLevel.HIGH if score >= 0.65
            else ConfidenceLevel.MEDIUM if score >= 0.4
            else ConfidenceLevel.LOW
        )
        return ConfidenceReport(
            level=level,
            score=round(score, 3),
            scenario_concentration=round(concentration, 3),
            data_completeness=round(completeness, 3),
            agent_agreement=round(agent_agreement, 3),
            lineup_certainty=round(lineup_certainty, 3),
            reasons=reasons,
        )

    def run(self, context: AgentContext) -> AgentResult[ConfidenceReport]:
        extra = context.knowledge if isinstance(context.knowledge, dict) else {}
        scenario_probs = extra.get("scenario_probs", [])
        data_quality = extra.get("data_quality")
        agent_agreement = extra.get("agent_agreement", 0.5)
        lineup_certainty = extra.get("lineup_certainty", 0.5)
        result = extra.get("result_probability")
        report = self.compute(scenario_probs, data_quality, agent_agreement, lineup_certainty, result)
        return self.ok(
            context,
            report,
            confidence=0.8,
            evidence=report.reasons,
            reasoning="Confidence is NOT max(prob): concentration, completeness, agreement all count.",
        )


def _level(score: float) -> RiskLevel:
    if score < 0.25:
        return RiskLevel.LOW
    if score < 0.5:
        return RiskLevel.MEDIUM
    if score < 0.7:
        return RiskLevel.HIGH
    return RiskLevel.VERY_HIGH
