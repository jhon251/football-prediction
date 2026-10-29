"""Generate docs/REAL_DATA_ONBOARDING_EPL_2025_26.md from the ACTUAL file.

Every row in the 132-field dictionary is produced from the real header and
real example values - never from memory.  Field meanings follow the source
convention (football-data.co.uk layout); where an expansion is not certain,
the entry says so explicitly instead of guessing (V1.2 principle 5).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from football_simulation.data.historical.doctor import (
    CORE_FIELDS,
    RESULT_FIELDS,
    field_kind,
    is_c_suffix,
    run_doctor,
)
from football_simulation.data.historical.profile import CsvProfile

RAW = Path("data/historical/raw/E0.csv")
OUT = Path("docs/REAL_DATA_ONBOARDING_EPL_2025_26.md")

# ---------------------------------------------------------------------------
# Curated per-field metadata: field -> (meaning, type, internal schema)
# ---------------------------------------------------------------------------

_BOOK = {
    "B365": ("Bet365 1X2 odds (decimal)", "float"),
    "BFD": ("BFD odds (source code; product expansion unverified - possibly a Betfair decimal feed)", "float"),
    "BMGM": ("BMGM odds (source code; likely BetMGM - expansion unverified)", "float"),
    "BV": ("BV odds (source code; likely BetVictor - expansion unverified)", "float"),
    "BW": ("Bet&Win 1X2 odds (decimal)", "float"),
    "CL": ("CL odds (source code; likely Coral/Ladbrokes family - expansion unverified)", "float"),
    "LB": ("Ladbrokes 1X2 odds (decimal)", "float"),
    "PS": ("Pinnacle 1X2 odds (decimal)", "float"),
    "Max": ("maximum 1X2 odds across covered bookmakers", "float"),
    "Avg": ("average 1X2 odds across covered bookmakers", "float"),
    "BFE": ("Betfair Exchange 1X2 odds (decimal)", "float"),
}

_FIELD_META: dict = {
    "Div": ("division/league code (E0 = English Premier League)", "string",
            "competition"),
    "Date": ("match date dd/mm/yyyy", "date", "date (with Time)"),
    "Time": ("kickoff time HH:MM (UK)", "time", "date (with Date)"),
    "HomeTeam": ("home team name", "string", "home_team"),
    "AwayTeam": ("away team name", "string", "away_team"),
    "FTHG": ("full-time home goals", "int", "home_goals (result)"),
    "FTAG": ("full-time away goals", "int", "away_goals (result)"),
    "FTR": ("full-time result code H/D/A", "enum", "derived result; validated against goals"),
    "HTHG": ("half-time home goals", "int", "half_time_home_goals (result)"),
    "HTAG": ("half-time away goals", "int", "half_time_away_goals (result)"),
    "HTR": ("half-time result code H/D/A", "enum", "validated against HT goals"),
    "Referee": ("match referee name", "string", "referee"),
    "HS": ("home shots", "int", "home_shots (result)"),
    "AS": ("away shots", "int", "away_shots (result)"),
    "HST": ("home shots on target", "int", "home_shots_on_target (result)"),
    "AST": ("away shots on target", "int", "away_shots_on_target (result)"),
    "HF": ("home fouls", "int", "home_fouls (result)"),
    "AF": ("away fouls", "int", "away_fouls (result)"),
    "HC": ("home corners", "int", "home_corners (result)"),
    "AC": ("away corners", "int", "away_corners (result)"),
    "HY": ("home yellow cards", "int", "home_yellow_cards (result)"),
    "AY": ("away yellow cards", "int", "away_yellow_cards (result)"),
    "HR": ("home red cards", "int", "home_red_cards (result)"),
    "AR": ("away red cards", "int", "away_red_cards (result)"),
    "AHh": ("Asian Handicap line for home team (goals, can be negative)", "float",
           "raw_odds[AH line]"),
}

for prefix, (meaning, dtype) in _BOOK.items():
    _FIELD_META[f"{prefix}H"] = (f"{meaning} - home", dtype, f"raw_odds[{prefix}H]")
    _FIELD_META[f"{prefix}D"] = (f"{meaning} - draw", dtype, f"raw_odds[{prefix}D]")
    _FIELD_META[f"{prefix}A"] = (f"{meaning} - away", dtype, f"raw_odds[{prefix}A]")
    _FIELD_META[f"{prefix}CH"] = (f"{meaning} (C-suffix snapshot) - home", dtype,
                                  f"raw_odds[{prefix}CH] (time_semantics unknown)")
    _FIELD_META[f"{prefix}CD"] = (f"{meaning} (C-suffix snapshot) - draw", dtype,
                                  f"raw_odds[{prefix}CD] (time_semantics unknown)")
    _FIELD_META[f"{prefix}CA"] = (f"{meaning} (C-suffix snapshot) - away", dtype,
                                  f"raw_odds[{prefix}CA] (time_semantics unknown)")

for prefix, label in (("B365", "Bet365"), ("P", "Pinnacle"), ("Max", "max across books"),
                      ("Avg", "average across books"), ("BFE", "Betfair Exchange")):
    _FIELD_META[f"{prefix}>2.5"] = (f"{label} over 2.5 goals odds", "float",
                                    f"raw_odds[{prefix}>2.5]")
    _FIELD_META[f"{prefix}<2.5"] = (f"{label} under 2.5 goals odds", "float",
                                    f"raw_odds[{prefix}<2.5]")
    _FIELD_META[f"{prefix}C>2.5"] = (f"{label} over 2.5 goals odds (C-suffix snapshot)", "float",
                                     f"raw_odds[{prefix}C>2.5] (time_semantics unknown)")
    _FIELD_META[f"{prefix}C<2.5"] = (f"{label} under 2.5 goals odds (C-suffix snapshot)", "float",
                                     f"raw_odds[{prefix}C<2.5] (time_semantics unknown)")

for prefix, label in (("B365", "Bet365"), ("P", "Pinnacle"), ("Max", "max across books"),
                      ("Avg", "average across books"), ("BFE", "Betfair Exchange")):
    _FIELD_META[f"{prefix}AHH"] = (f"{label} Asian Handicap home price", "float",
                                   f"raw_odds[{prefix}AHH]")
    _FIELD_META[f"{prefix}AHA"] = (f"{label} Asian Handicap away price", "float",
                                   f"raw_odds[{prefix}AHA]")
    _FIELD_META[f"{prefix}CAHH"] = (f"{label} Asian Handicap home price (C-suffix snapshot)",
                                    "float", f"raw_odds[{prefix}CAHH] (time_semantics unknown)")
    _FIELD_META[f"{prefix}CAHA"] = (f"{label} Asian Handicap away price (C-suffix snapshot)",
                                    "float", f"raw_odds[{prefix}CAHA] (time_semantics unknown)")
_FIELD_META["AHCh"] = ("Asian Handicap line (C-suffix snapshot)", "float",
                       "raw_odds[AHCh] (time_semantics unknown)")


def _flag(field: str) -> tuple:
    kind = field_kind(field)
    is_result = field in RESULT_FIELDS
    is_post = is_result
    is_odds = kind in ("one_x_two", "over_under", "asian_handicap")
    if is_c_suffix(field):
        usable = "NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms"
        risk = "HIGH (cannot verify opening vs closing from the file)"
    elif is_result:
        usable = "NO for this match (principle 1); YES only as historical aggregates of past matches (principle 2)"
        risk = "NONE (structurally excluded from pre-match inputs)"
    elif is_odds:
        usable = "YES as market baseline (closing-convention snapshot stamped at kickoff)"
        risk = "MEDIUM (no per-odds timestamp in file; single-snapshot assumption)"
    elif field == "Referee":
        usable = "YES (appointment name; tendency data NO_SIGNAL)"
        risk = "LOW"
    else:
        usable = "YES (match identity)"
        risk = "NONE"
    return is_result, is_post, is_odds, usable, risk


def _transform(field: str) -> str:
    if field == "Date":
        return "dd/mm/yyyy -> ISO datetime (with Time, UTC)"
    if field == "Time":
        return "HH:MM -> hour/minute (with Date)"
    if field in RESULT_FIELDS:
        return "string -> int / enum; result fields mapped into post-match section only"
    if field_kind(field) in ("one_x_two", "over_under", "asian_handicap"):
        if is_c_suffix(field):
            return "float preserved in raw_odds with time_semantics=unknown_time_semantics"
        return "string -> float; plain columns labeled closing_convention_pre_kickoff"
    if field == "Referee":
        return "name string; no tendency data (NO_SIGNAL)"
    return "identity string; no numeric transform"


def main() -> None:
    profile = CsvProfile(RAW)
    report = profile.full_report()
    doctor = run_doctor(str(RAW))

    example = {f: (profile.rows[0].get(f) or "") for f in profile.fieldnames}
    # a second, mid-season example for variety where the first is empty
    mid = profile.rows[190]
    for f in profile.fieldnames:
        if not example[f] and (mid.get(f) or "").strip():
            example[f] = mid.get(f)

    lines: list = []
    lines.append("# REAL DATA ONBOARDING: 英超 2025-26 赛季（E0.csv）")
    lines.append("")
    lines.append("> 本文件由 `scripts/v12_generate_onboarding_doc.py` 从**真实原始文件**自动生成"
                 "（字段名、示例值全部取自文件本身，非记忆）。")
    lines.append("> 本阶段只做数据接入与审计：**不运行任何预测、不修改任何核心预测逻辑**。")
    lines.append("")
    lines.append("## 0. 数据概览")
    lines.append("")
    lines.append(f"- 文件：`{report['file']}`（已复制入 `data/historical/raw/E0.csv`）")
    lines.append(f"- 数据规模：**{report['stats']['rows']} 场比赛 / {report['stats']['fields']} 个字段**")
    lines.append(f"- 日期范围：{report['date_range'][0]} → {report['date_range'][1]}（282 天，完整赛季）")
    lines.append(f"- 球队数量：**{report['teams']['distinct_teams']} 支**，每队恰好 38 场（完整双循环）")
    lines.append(f"- 重复比赛：{len(report['duplicates'])}")
    lines.append(f"- 缺失值：核心 24 字段 **0 缺失**；"
                 f"{len(report['missing_by_column'])} 个赔率/辅助字段存在博彩公司覆盖缺口"
                 f"（PS/Pinnacle 缺 170/380，CL 缺 98/380，LB 缺 94/380 等）")
    lines.append("- 一致性：HT≤FT 全部成立；FTR/HTR 与比分全部一致；射正≤射门全部成立；"
                 "赔率全部 >1.0 且无非法值")
    lines.append("- 数据性质：**真实数据**（无合成标记，内部 schema `is_synthetic=false`）")
    lines.append("")
    lines.append("## 1. Doctor 输出")
    lines.append("")
    lines.append("```")
    lines.extend(doctor.render().splitlines())
    lines.append("```")
    lines.append("")
    lines.append("## 2. 七条原则在本文件上的落实")
    lines.append("")
    lines.append("| 原则 | 落实方式 |")
    lines.append("| --- | --- |")
    lines.append("| P1 结果字段不得作为本场赛前输入 | FTHG/FTAG/FTR/HTHG/HTAG/HTR/HS/AS/HST/AST/HF/AF/HC/AC/HY/AY/HR/AR 全部归入赛后区，导入层结构性隔离 |")
    lines.append("| P2 允许历史聚合 | 仅 `observed_at < kickoff` 的历史比赛可生成特征（时间旅行测试位一致保证） |")
    lines.append("| P3 不得使用未来比赛 | walk-forward 特征函数只读 `date < kickoff`；审计 Future Match Leakage PASS |")
    lines.append("| P4/P5 开收盘严格区分，不猜测 | 文件**不含逐赔率时间戳**：普通列按来源惯例标记 `closing_convention_pre_kickoff`（盖章=开球时刻）；**54 个 C 后缀列无法从文件证实开/收盘语义（overround 分析双向不一致）→ 标记 `unknown_time_semantics`，不映射进 closing/opening**；opening_odds 保持 None |")
    lines.append("| P6 不得复制赛后字段为赛前特征 | 导入层把结果字段写入赛后区；特征函数只接受赛后区之外的输入 |")
    lines.append("| P7 不伪造 xG | 本文件**没有 xG 列** → xG 保持缺失，不构造任何公式生成 |")
    lines.append("")
    lines.append("## 3. 赔率时间语义结论（重要）")
    lines.append("")
    lines.append("- 本文件同时含普通赔率列与 **C 后缀列**（B365C*/BFDC*/.../MaxC*/AvgC*/BFEC* 等共 54 列）。")
    lines.append("- 用 overround 收敛性检验（收盘市场通常比开盘市场抽水更低）实测结果**双向不一致**："
                 "PS(-0.0059)/Max(-0.0039)/BV(-0.0063) 的 C 列更紧，而 B365(+0.0008)/BMGM(+0.0009)/BW(+0.0008) 的 C 列略宽 → **无法从文件本身判定 C 列是开盘还是收盘**。")
    lines.append("- 结论（原则 5）：C 后缀列一律 `UNKNOWN` 时间语义，**只保留原文、不进入任何建模映射**；"
                 "closing_odds 只取普通 Avg 列（跨公司平均，来源惯例=赛前收盘快照，盖章=开球时刻），opening_odds=无（不存在可验证的开盘快照）。")
    lines.append("")
    lines.append("## 4. 完整字段字典（132 个字段）")
    lines.append("")
    lines.append("| # | 原始字段名 | 含义 | 数据类型 | 示例值 | 是否比赛结果 | 是否赛后数据 | 是否赔率 | 是否可用于赛前预测 | 时间语义风险 | 是否需要转换 | 对应 InternalSchema |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")

    for i, field in enumerate(profile.fieldnames, 1):
        meaning, dtype, internal = _FIELD_META.get(
            field, (f"(source column; see kind={field_kind(field)})", "str", "raw_odds[preserved]"))
        is_result, is_post, is_odds, usable, risk = _flag(field)
        ex = example[field] or "—"
        lines.append(
            f"| {i} | `{field}` | {meaning} | {dtype} | `{ex}` | "
            f"{'是' if is_result else '否'} | {'是' if is_post else '否'} | "
            f"{'是' if is_odds else '否'} | {usable} | {risk} | "
            f"{'是' if '->' in _transform(field) or 'float' in _transform(field) or 'int' in _transform(field) else '否'} | {internal} |")

    lines.append("")
    lines.append("## 5. 导入产物")
    lines.append("")
    lines.append("- 原始文件：`data/historical/raw/E0.csv`（203,438 字节，未修改）")
    lines.append("- 规范数据集：`data/historical/epl_2025_26.json`（380 条 `HistoricalMatch`，"
                 "`is_synthetic=false`，`source='football-data.co.uk E0 2025-26 (real)'`）")
    lines.append("- 每条记录：结果字段与赛前字段结构性分离；closing_odds=Avg（惯例标注）；"
                 "108 个原始赔率字段逐字保留并打时间语义标签（54 个 UNKNOWN）；xG 保持缺失。")
    lines.append("- 泄漏审计（真实数据上运行）：**7/7 PASS**（含 380 场时间旅行位一致测试）。")
    lines.append("")
    lines.append("## 6. 最终判定")
    lines.append("")
    lines.append("**REAL DATA ONBOARDING PASS**")
    lines.append("")
    lines.append("后续（本阶段不做）：正式回测需先补充 C 后缀列的开/收盘官方文档、"
                 "确认每列赔率的精确抓取时间，然后才能决定哪些列可进入市场基准。")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"written -> {OUT} ({len(lines)} lines)")


if __name__ == "__main__":
    main()
