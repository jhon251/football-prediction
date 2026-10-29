# -*- coding: utf-8 -*-
"""Derived upset-risk warning from devigged market probabilities.

STATUS: derived reparameterization of the validated market baseline output
(M4/O2 Shin devig), NOT an independently validated signal — same standing
as score_matrix (evidence_level: Derived).

Definition is aligned with football_simulation.agents.risk.UpsetRiskAgent
(System A, spec sections 32-34): upset is defined RELATIVE to the pre-match
probabilities, never "weak team wins". The level thresholds below mirror
System A exactly so the two systems speak the same language:

  favourite  = side with max(p_home, p_away); p_fav / p_dog accordingly
  severity   = min(1, (p_fav - p_dog) * 1.6)
  level      = VERY_HIGH/HIGH/MEDIUM/LOW at severity >= .65/.45/.25 else LOW,
               capped down when the upset probability is tiny (<.08 / <.03)
  open game  = p_fav < 0.40 -> LOW with upset_type "open_game"
  upset prob = p_dog (underdog WIN — System A convention); this module
               additionally reports favourite_fails = 1 - p_fav (draw
               included) as the broader "favourite drops points" view.

Market-only extensions (no lineup/injury data in the frozen pipeline):
extreme cold scorelines and P(underdog by 2+) come from the derived score
matrix; drivers describe market self-uncertainty (entropy, cross-book
dispersion, single-book capture).
"""
from __future__ import annotations

from typing import Any, Optional

MODULE_VERSION = "upset_risk 0.1.0"

_LEVEL_LABELS = {"VERY_HIGH": "极高", "HIGH": "高", "MEDIUM": "中", "LOW": "低"}
_DIRECTION_LABELS = {"home_win": "主胜爆冷", "away_win": "客胜爆冷"}

INVARIANT_NOTE = (
    "level/probability mirror football_simulation UpsetRiskAgent thresholds "
    "applied to the devigged market probabilities; extreme scorelines come "
    "from the derived Dixon-Coles score matrix; descriptive only, not an "
    "independently validated signal; research use, no betting"
)


def derive_upset_risk(p_home: float, p_draw: float, p_away: float,
                      score_matrix: Optional[dict] = None,
                      ftr_entropy_bits: Optional[float] = None,
                      book_dispersion: Optional[float] = None,
                      n_books: Optional[int] = None) -> dict[str, Any]:
    """Derive the upset-risk block. p_* are devigged 1X2 probabilities."""
    p_home, p_draw, p_away = float(p_home), float(p_draw), float(p_away)
    if min(p_home, p_draw, p_away) <= 0:
        raise ValueError("probabilities must be strictly positive")
    s = p_home + p_draw + p_away
    if abs(s - 1.0) > 0.01:
        raise ValueError(f"1X2 probabilities must sum to 1 (got {s:.6f})")
    p_home, p_draw, p_away = p_home / s, p_draw / s, p_away / s

    favourite = "home" if p_home >= p_away else "away"
    p_fav = max(p_home, p_away)
    p_dog = min(p_home, p_away)
    upset_direction = "away_win" if favourite == "home" else "home_win"
    severity = round(min(1.0, (p_fav - p_dog) * 1.6), 4)

    if p_fav < 0.40:
        level, upset_type = "LOW", "open_game"
    else:
        if severity >= 0.65:
            level = "VERY_HIGH"
        elif severity >= 0.45:
            level = "HIGH"
        elif severity >= 0.25:
            level = "MEDIUM"
        else:
            level = "LOW"
        if p_dog < 0.08 and level == "VERY_HIGH":
            level = "HIGH"
        if p_dog < 0.03 and level == "HIGH":
            level = "MEDIUM"
        upset_type = "upset" if p_dog < 0.20 else "moderate_surprise"

    drivers: list[str] = []
    if p_fav < 0.40:
        drivers.append(f"无真正热门（热门概率 {p_fav:.0%} < 40%）——开放对局")
    else:
        drivers.append(
            f"热门 {favourite} 概率 {p_fav:.0%}，冷门方胜率 {p_dog:.0%}"
            f"（severity {severity:.2f}）")
        if 0.40 <= p_fav < 0.55:
            drivers.append("热门优势定价不坚定（边际热门）")
        if severity >= 0.65:
            drivers.append("市场对热门定价优势极大——一旦冷门即属重冷")
    if book_dispersion is not None and book_dispersion > 0.05:
        drivers.append(f"庄家分歧大（dispersion {book_dispersion:.3f} > 0.05）")
    if ftr_entropy_bits is not None and ftr_entropy_bits > 1.45:
        drivers.append(f"结果分布熵高（{ftr_entropy_bits:.2f} bits），市场自身不确定度大")
    if n_books is not None and n_books <= 1:
        drivers.append("单庄家来源，冷门定价缺少交叉验证")

    out: dict[str, Any] = {
        "module_version": MODULE_VERSION,
        "status": "VALID",
        "evidence_level": "Derived",
        "definition": "upset relative to pre-match devigged market probabilities "
                      "(aligned with football_simulation UpsetRiskAgent thresholds)",
        "favourite": favourite,
        "favourite_probability": round(p_fav, 8),
        "level": level,
        "level_label": _LEVEL_LABELS[level],
        "severity": severity,
        "probability": round(p_dog, 8),          # underdog WIN (System A convention)
        "direction": upset_direction,
        "direction_label": _DIRECTION_LABELS[upset_direction],
        "favourite_fails_probability": round(1.0 - p_fav, 8),  # draw included
        "upset_type": upset_type,
        "drivers": drivers[:5],
        "invariant_note": INVARIANT_NOTE,
    }

    if score_matrix and isinstance(score_matrix.get("matrix"), list):
        m = score_matrix["matrix"]
        n = len(m)
        dog_is_away = (favourite == "home")
        cells = []
        by_2 = 0.0
        for h in range(n):
            for a in range(n):
                if dog_is_away and a > h:            # away (dog) wins
                    cells.append(((h, a), float(m[h][a])))
                    if a - h >= 2:
                        by_2 += float(m[h][a])
                elif not dog_is_away and h > a:      # home (dog) wins
                    cells.append(((h, a), float(m[h][a])))
                    if h - a >= 2:
                        by_2 += float(m[h][a])
        cells.sort(key=lambda c: -c[1])
        out["extreme_scores"] = [
            {"score": f"{h}-{a}", "home_goals": h, "away_goals": a,
             "probability": p} for (h, a), p in cells[:3]]
        out["probability_underdog_by_2"] = round(by_2, 8)
        out["extreme_scores_note"] = "冷门方获胜的比分中概率最高者（主-客）"
    return out
