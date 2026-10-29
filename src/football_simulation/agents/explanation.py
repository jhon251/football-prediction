"""Explanation Agent: turns internal state into a human-readable analysis.

Must answer: WHY?  How will it most likely be played?  What helps each side?
Where could the match turn?  When would the prediction fail?  Why upset risk?
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from football_simulation.agents.base import AgentContext, BaseAgent
from football_simulation.models.base import AgentResult, RiskLevel
from football_simulation.models.report import (
    ConfidenceReport,
    ResultProbability,
    RiskReport,
    UpsetRiskReport,
)
from football_simulation.models.scenario import Scenario
from football_simulation.models.world import WorldState


class ExplanationAgent(BaseAgent[str]):
    name = "ExplanationAgent"
    description = "Produces the human-readable match analysis."

    def explain(
        self,
        world: WorldState,
        result: ResultProbability,
        scenarios: List[Scenario],
        upset: UpsetRiskReport,
        risk: RiskReport,
        confidence: ConfidenceReport,
        failure_conditions: List[str],
        matchup: Any,
    ) -> str:
        home = world.home_team_state
        away = world.away_team_state
        lines: List[str] = []
        lines.append(f"# {home.name if home else world.home_team} vs {away.name if away else world.away_team} 赛前推演分析")

        lines.append("")
        lines.append("## 为什么是这个概率？")
        lines.append(
            f"模型通过 {self._fmt_pct(result.home_win)}/{self._fmt_pct(result.draw)}/{self._fmt_pct(result.away_win)} 的分布 "
            f"给出主胜/平局/客胜概率。该分布来自状态驱动的蒙特卡洛模拟：由双方战术对位、阵容、体能、"
            f"心理、裁判与环境共同决定每分钟的事件强度，而非单一预测器输出。"
        )

        lines.append("")
        lines.append("## 比赛最可能怎么踢？")
        if scenarios:
            top = scenarios[0]
            lines.append(f"最可能剧本「{top.name}」({self._fmt_pct(top.probability)}): {top.description}")
            for key_event in top.key_events[:4]:
                lines.append(f"  - {key_event.minute}' {key_event.side.value} {key_event.event_type}")
            if len(scenarios) > 1:
                second = scenarios[1]
                lines.append(f"次可能剧本「{second.name}」({self._fmt_pct(second.probability)}): {second.description}")
        else:
            lines.append("（无剧本数据）")
        if matchup is not None and matchup.analysis:
            lines.append(f"战术对位: {matchup.analysis}")

        lines.append("")
        lines.append("## 支持主队的因素")
        for reason in self._home_factors(world, matchup):
            lines.append(f"  - {reason}")
        lines.append("## 支持客队的因素")
        for reason in self._away_factors(world, matchup):
            lines.append(f"  - {reason}")

        lines.append("")
        lines.append("## 比赛最可能在哪里转折？")
        lines.append(f"  - 首15分钟: 开场强度决定早期进球风险。")
        lines.append(f"  - 60-75分钟: 双方换人窗口，体能曲线开始分化。")
        lines.append(f"  - 75分钟以后: 若比分胶着，落后方将进入高风险搏杀模式。")

        lines.append("")
        lines.append("## 什么情况会让预测失效？")
        for condition in failure_conditions[:5]:
            lines.append(f"  - {condition}")

        lines.append("")
        lines.append("## 为什么存在爆冷风险？")
        lines.append(
            f"爆冷风险等级: {upset.level.value} (方向 {upset.direction}, "
            f"概率 {self._fmt_pct(upset.probability)})。"
        )
        for driver in upset.drivers[:5]:
            lines.append(f"  - {driver}")
        if not upset.drivers:
            lines.append("  - 无显著结构性爆冷驱动因素；风险主要来自比赛本身的随机性。")

        lines.append("")
        lines.append("## 主要风险")
        for component in risk.components:
            if component.score >= 0.3:
                lines.append(f"  - {component.name}: {component.level.value} ({component.score:.2f})")

        lines.append("")
        lines.append(f"## 置信度: {confidence.level.value} ({confidence.score:.2f})")
        for reason in confidence.reasons[:3]:
            lines.append(f"  - {reason}")

        return "\n".join(lines)

    def _home_factors(self, world: WorldState, matchup: Any) -> List[str]:
        factors: List[str] = []
        home = world.home_team_state
        if home is not None:
            factors.append(f"攻击强度 {home.attack_strength:.2f} / 防守 {home.defense_strength:.2f}")
            if home.pressing_style == "high_press":
                factors.append("高位压迫体系可能压制对方出球")
            if home.counter_attack_strength > 0.6:
                factors.append("反击威胁大")
        factors.append("主场优势与球迷支持")
        if matchup is not None and matchup.tactical_advantage_home > 0.1:
            factors.append(f"战术对位占优 (advantage {matchup.tactical_advantage_home:+.2f})")
        return factors

    def _away_factors(self, world: WorldState, matchup: Any) -> List[str]:
        factors: List[str] = []
        away = world.away_team_state
        if away is not None:
            if away.counter_attack_strength > 0.6:
                factors.append("反击速度可能惩罚主队压上")
            if away.set_piece_strength > 0.6:
                factors.append("定位球威胁")
            if away.defense_strength > 0.7:
                factors.append("防守组织稳固")
        if world.fatigue_home > world.fatigue_away + 0.1:
            factors.append("主队体能负担更重")
        if matchup is not None and matchup.tactical_advantage_away > 0.1:
            factors.append(f"战术对位占优 (advantage {matchup.tactical_advantage_away:+.2f})")
        return factors

    @staticmethod
    def _fmt_pct(p: float) -> str:
        return f"{p * 100:.1f}%"

    def run(self, context: AgentContext) -> AgentResult[str]:
        extra = context.knowledge if isinstance(context.knowledge, dict) else {}
        world = context.world
        if world is None:
            return self.fail(context, "missing world state")
        text = self.explain(
            world,
            extra.get("result_probability"),
            extra.get("scenarios", []),
            extra.get("upset_risk"),
            extra.get("risk"),
            extra.get("confidence"),
            extra.get("failure_conditions", []),
            context.matchup,
        )
        return self.ok(
            context,
            text,
            confidence=0.8,
            evidence=["analysis generated from simulation statistics and agent outputs"],
            reasoning="Explanation built from traceable components only (no invented facts).",
        )
