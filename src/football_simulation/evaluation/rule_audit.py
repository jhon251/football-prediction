"""V1.1 Rule Audit.

Every knowledge rule gets a curated audit entry: statement, source, status,
whether it is implemented, its causal direction, overfitting risk, and a
mandatory ``needs_real_data_validation`` flag.

The annotations below are HUMAN AUDIT METADATA - honest assessments of which
claims are football-plausible and which are development-time assumptions.
They never alter rule behavior.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from football_simulation.models.knowledge import KnowledgeRule


class RuleAuditEntry(BaseModel):
    """One audited rule (spec V1.1 section 6 shape + evidence fields)."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    statement: str
    category: str
    source: str
    source_type: str
    status: str
    implemented: bool
    causal_direction: str
    risk_of_overfitting: str  # low | medium | high
    needs_real_data_validation: bool = True
    confidence: float
    evidence_count: int = 0
    verified_matches: int = 0
    success_rate: Optional[float] = None
    counter_examples: int = 0


# ---------------------------------------------------------------------------
# Curated audit annotations: rule_id -> (statement, causal_direction, risk)
# ---------------------------------------------------------------------------

_ANNOTATIONS: Dict[str, tuple] = {
    # -- scoreline / mentality ------------------------------------------------
    "R_MENTALITY_LEAD_TEMPO": (
        "领先球队在防守型教练手下会降低节奏、风险与进攻强度。",
        "scoreline -> coach_reaction -> tempo/risk/attack down",
        "medium",
    ),
    "R_MENTALITY_LEAD_AWAY_TEMPO": (
        "同上（客队镜像规则）。",
        "scoreline -> coach_reaction -> tempo/risk/attack down",
        "medium",
    ),
    "R_MENTALITY_TRAIL_PUSH": (
        "落后球队提高进攻强度与风险倾向（15分钟后开始生效）。",
        "trailing -> attacking_intensity/risk up",
        "medium",
    ),
    "R_MENTALITY_TRAIL_PUSH_AWAY": (
        "同上（客队镜像规则）。",
        "trailing -> attacking_intensity/risk up",
        "medium",
    ),
    "R_TRAIL_DESPERATE_LATE": (
        "75分钟后仍落后将进入高风险搏杀模式。",
        "trailing+late_game -> desperation push",
        "medium",
    ),
    "R_TRAIL_DESPERATE_LATE_AWAY": (
        "同上（客队镜像规则）。",
        "trailing+late_game -> desperation push",
        "medium",
    ),
    "R_LEAD_LATE_GAME_MANAGEMENT": (
        "75分钟后领先的球队降低节奏与风险并回收防线。",
        "leading+late_game -> game management",
        "low",
    ),
    "R_LEAD_LATE_GAME_MANAGEMENT_AWAY": (
        "同上（客队镜像规则）。",
        "leading+late_game -> game management",
        "low",
    ),
    # -- red cards ------------------------------------------------------------
    "R_RED_CARD_HOME_DISADVANTAGE": (
        "少一人作战：进攻产出下降、压迫强度下降、对手压迫上升。",
        "red_card -> chance_creation/attack down",
        "low",
    ),
    "R_RED_CARD_AWAY_DISADVANTAGE": (
        "同上（客队镜像规则）。",
        "red_card -> chance_creation/attack down",
        "low",
    ),
    # -- psychology feedback ---------------------------------------------------
    "R_GOAL_DOWN_MOMENTUM": (
        "丢球使落后方压力上升、领先方信心上升。",
        "conceding -> pressure up / opponent confidence up",
        "medium",
    ),
    "R_GOAL_UP_MOMENTUM": (
        "进球使领先方信心上升、落后方压力上升。",
        "scoring -> confidence up / opponent pressure up",
        "medium",
    ),
    # -- fatigue ----------------------------------------------------------------
    "R_FATIGUE_LATE_DECLINE": (
        "末段高疲劳降低机会创造质量。",
        "fatigue+late_game -> chance_creation down",
        "medium",
    ),
    "R_FATIGUE_LATE_DECLINE_AWAY": (
        "同上（客队镜像规则）。",
        "fatigue+late_game -> chance_creation down",
        "medium",
    ),
    # -- environment -------------------------------------------------------------
    "R_RAIN_EFFECT": (
        "大雨小幅降低双方机会质量。",
        "heavy_rain -> chance_creation slightly down",
        "medium",
    ),
    "R_HEAT_EFFECT": (
        "高温降低可持续的比赛节奏。",
        "heat -> tempo down",
        "medium",
    ),
    "R_WIND_EFFECT": (
        "大风对机会质量有极轻微影响（当前系数接近无效）。",
        "wind -> chance_creation ~neutral",
        "high",
    ),
    # -- psychology mechanics -----------------------------------------------------
    "R_PRESSURE_DECISION_QUALITY": (
        "高压环境下决策质量与冷静度下降。",
        "pressure -> decision_quality/composure down",
        "medium",
    ),
    "R_PRESSURE_DECISION_QUALITY_AWAY": (
        "同上（客队镜像规则）。",
        "pressure -> decision_quality/composure down",
        "medium",
    ),
    "R_HIGH_CONFIDENCE_ATTACK": (
        "高信心小幅提升进攻流畅度。",
        "confidence -> chance_creation up",
        "medium",
    ),
    "R_HIGH_CONFIDENCE_ATTACK_AWAY": (
        "同上（客队镜像规则）。",
        "confidence -> chance_creation up",
        "medium",
    ),
    "R_YELLOW_CARD_CAUTION": (
        "多张黄牌后压迫更谨慎。",
        "bookings -> pressing caution",
        "medium",
    ),
    "R_YELLOW_CARD_CAUTION_AWAY": (
        "同上（客队镜像规则）。",
        "bookings -> pressing caution",
        "medium",
    ),
    "R_MOMENTUM_CONFIDENCE_FEEDBACK": (
        "持续势头反哺信心（与动量本身存在部分重复计算风险）。",
        "momentum -> confidence feedback loop",
        "high",
    ),
    "R_MOMENTUM_CONFIDENCE_FEEDBACK_AWAY": (
        "同上（客队镜像规则）。",
        "momentum -> confidence feedback loop",
        "high",
    ),
    "R_HALF_TIME_RESET": (
        "中场休息将势头部分重置回中性（结构性的比赛机制）。",
        "half_time -> momentum reset",
        "low",
    ),
    "R_HOME_CROWD_SUPPORT": (
        "主场球迷小幅提升主队信心（与主场优势存在部分重复）。",
        "home_crowd -> confidence up",
        "medium",
    ),
    # -- tactical patterns ---------------------------------------------------------
    "TP_HIGH_PRESS_VS_WEAK_BUILDUP": (
        "高压逼抢对出球薄弱的球队形成前场压制与转换威胁。",
        "high_press vs weak_buildup -> pressing success / chance creation",
        "medium",
    ),
    "TP_LOW_BLOCK_VS_POSSESSION": (
        "低位防守压缩空间、降低对手机会质量但让出控球。",
        "low_block vs possession -> chance quality down / possession conceded",
        "medium",
    ),
    "TP_COUNTER_VS_HIGH_LINE": (
        "强反击球队惩罚高位防线（身后空间）。",
        "counter vs high_line -> transition threat up",
        "medium",
    ),
    "TP_WING_ATTACK_VS_NARROW": (
        "边路进攻在窄防守下获得空间与传中机会。",
        "wing_attack vs narrow -> wide chance creation up",
        "medium",
    ),
    "TP_THREE_CB_VS_TWO_STRIKERS": (
        "三中卫对双前锋形成中路人数优势（依赖具体阵型配置）。",
        "3CB vs 2ST -> central danger reduced",
        "medium",
    ),
    "TP_INVERTED_FB_VS_WIDE_PRESS": (
        "内收边卫遭遇宽压迫时出球风险上升（高度推测性）。",
        "inverted FB vs wide press -> buildup risk up",
        "high",
    ),
    "TP_SET_PIECE_EDGE": (
        "定位球强弱错配带来死球威胁加成。",
        "set_piece mismatch -> dead-ball xG up",
        "medium",
    ),
    "TP_MIDFIELD_QUALITY_GAP": (
        "中场质量差带来控球与机会创造优势（与强度模型部分重复）。",
        "midfield gap -> possession/chance creation",
        "medium",
    ),
}


def audit_rules(knowledge: Dict[str, Any]) -> List[RuleAuditEntry]:
    """Audit every rule in the default state pack + tactical pattern pack."""
    entries: List[RuleAuditEntry] = []
    for pack_key, category_hint in (("rules", "rules"), ("tactical_patterns", "tactical_patterns")):
        pack = knowledge.get(pack_key)
        if pack is None:
            continue
        for rule in pack.rules:
            statement, causal_direction, overfit = _ANNOTATIONS.get(
                rule.rule_id,
                (rule.description or rule.name, "unassessed", "high"),
            )
            entries.append(
                RuleAuditEntry(
                    rule_id=rule.rule_id,
                    statement=statement,
                    category=rule.category or category_hint,
                    source=rule.source,
                    source_type=rule.source_type,
                    status=rule.status.value,
                    implemented=rule.active,
                    causal_direction=causal_direction,
                    risk_of_overfitting=overfit,
                    needs_real_data_validation=True,
                    confidence=rule.confidence,
                    evidence_count=rule.evidence_count,
                    verified_matches=rule.verified_matches,
                    success_rate=rule.success_rate,
                    counter_examples=rule.counter_examples,
                )
            )
    return entries


def rule_counts(entries: List[RuleAuditEntry]) -> Dict[str, int]:
    """Dashboard counts: validated / tentative / unverified / assumption."""
    counts = {"validated": 0, "tentative": 0, "unverified": 0, "assumption": 0}
    for entry in entries:
        counts[entry.status] = counts.get(entry.status, 0) + 1
        if entry.source_type == "assumption":
            counts["assumption"] += 1
    return counts


def audit_dict(entries: List[RuleAuditEntry]) -> List[Dict[str, Any]]:
    return [e.model_dump() for e in entries]
