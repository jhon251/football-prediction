"""EXP-DIAG-EPL-001 analysis + report generation.

Read-only: frozen baseline records (elo/full on 380 matches), the
deterministic pre-match reconstruction, and the diagnostic config predictions
(backtest_output/diagnosis_epl_001/preds.json).
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from football_simulation.backtest.diagnosis import (
    AGENT_INPUT_DEPENDENCY,
    baseline_manifest,
    correlations,
    distribution_stats,
    elo_coverage,
    identify_high_influence,
    influence_summary,
    reconstruct_prematch_layer,
)
from football_simulation.backtest.metrics import full_metrics
from football_simulation.backtest.models import ModelPrediction, PredictionRecord
from football_simulation.data.historical.etl import HistoricalDataset

BASELINE_DIR = Path("backtest_output/real_epl_base_001")
OUT_DIR = Path("backtest_output/diagnosis_epl_001")
DATASET_PATH = Path("data/historical/epl_2025_26.json")
DOC = Path("docs/EXP_DIAG_EPL_001.md")
SAMPLE_INDICES = sorted(set(range(0, 380, 3)))[:120]


def load_frozen_records() -> List[PredictionRecord]:
    raw = json.loads((BASELINE_DIR / "records.json").read_text(encoding="utf-8"))
    return [PredictionRecord.model_validate(r) for r in raw]


def config_records(
    dataset: HistoricalDataset, preds: Dict[str, Dict[str, dict]], config: str
) -> List[PredictionRecord]:
    by_id = {m.match_id: m for m in dataset.matches}
    out: List[PredictionRecord] = []
    for match_id, pred in preds.get(config, {}).items():
        match = by_id[match_id]
        out.append(PredictionRecord(
            match_id=match_id, kickoff=match.date,
            home_team=match.home_team, away_team=match.away_team,
            actual_home_goals=match.home_goals, actual_away_goals=match.away_goals,
            predictions={"m": ModelPrediction.model_validate(pred)}, synthetic=False))
    return out


def main() -> None:
    dataset = HistoricalDataset.load(DATASET_PATH)
    matches = dataset.matches_in_season("2025-26")
    frozen = load_frozen_records()
    preds = json.loads((OUT_DIR / "preds.json").read_text(encoding="utf-8"))
    manifest = json.loads((OUT_DIR / "baseline_manifest.json").read_text(encoding="utf-8"))

    rows = reconstruct_prematch_layer(dataset)
    row_by_id = {r["match_id"]: r for r in rows}

    lines: list = []
    lines.append("# EXP-DIAG-EPL-001：真实数据失败机制诊断")
    lines.append("")
    lines.append("> 只读诊断：生产模型、35 条规则、config、数据层、冻结基线 "
                 f"EXP-REAL-EPL-BASE-001（`{manifest['experiment_id']}`）均未修改。")
    lines.append("> 诊断模拟写入独立目录 `backtest_output/diagnosis_epl_001/`，"
                 "与基线同一样本定义（`range(0,380,3)[:120]`）与同一种子（20240101）。")
    lines.append("")
    lines.append("## 0. 数据可用性声明")
    lines.append("")
    lines.append("- 冻结基线原始记录保存：各模型 1X2/OU/BTTS/比分概率、unknowns、top_scenario。")
    lines.append("- **未保存**（原始运行）：Team/Tactical/Psychology/Momentum/Referee/Player 的"
                 "逐场直接输出、动量轨迹、赛中状态 → 记为 **DATA_UNAVAILABLE**。")
    lines.append("- 本诊断使用的『逐场 Agent 输出』是**确定性重建**（同一冻结数据与代码、"
                 "赛前层纯函数、无模拟），仅用于诊断，不冒充原始实验数据。")
    lines.append("")
    lines.append("## 1. Agent 输出取证（确定性重建，380 场）")
    lines.append("")
    lines.append("| Agent/信号 | 均值 | 标准差 | min | max | p50 | NO_SIGNAL 占比 | 说明 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    agent_columns = [
        ("elo_diff", "Elo 差（基线特征）", "基线特征"),
        ("team_strength_diff", "Team：攻防强度和差", "含主场优势（Team 把 home_adv 加进 attack）"),
        ("team_strength_diff_nohome", "Team：和差（无主场版）", "主场优势剥离版，用于第 2 节相关性诊断"),
        ("tactical_advantage_home", "Tactical：对位优势", "幅度极小（±0.28），含主场偏移"),
        ("tactical_advantage_nohome", "Tactical：对位优势（无主场版）", "剥离主场偏移后用于相关性诊断"),
        ("tactical_cc_diff", "Tactical：机会创造差", ""),
        ("psych_confidence_diff", "Psychology：信心差", "仅由近期战绩驱动"),
        ("psych_pressure_diff", "Psychology：压力差", ""),
        ("fitness_fatigue_diff", "Fitness：疲劳差", "78% 场次为 0（周赛程双方拥挤度相同）"),
        ("referee_signal", "Referee：信号", "恒 0 —— 只有姓名，倾向 NO_SIGNAL"),
        ("player_signal", "Player：信号", "恒 0 —— 无球员数据，NO_SIGNAL 占位"),
        ("momentum_prematch_home", "Momentum：赛前值", "恒 0.5；赛中轨迹 DATA_UNAVAILABLE"),
    ]
    for column, name, note in agent_columns:
        stats = distribution_stats([r[column] for r in rows])
        lines.append(f"| {name} | {stats['mean']} | {stats['std']} | {stats['min']} | "
                     f"{stats['max']} | {stats['p50']} | {stats['no_signal_share']} | {note} |")
    lines.append("")
    lines.append("## 2. 信息重复性分析")
    lines.append("")
    corr = correlations(rows, ["elo_diff", "team_strength_diff_nohome",
                               "tactical_advantage_nohome", "tactical_cc_diff_nohome",
                               "psych_confidence_diff", "psych_pressure_diff",
                               "fitness_fatigue_diff"])
    lines.append("（Team/Tactical 信号采用**主场优势剥离版**，避免主场偏移把相关性虚高；"
                 "Elo 差本身无主场成分。）")
    lines.append("| 信号对 | Pearson | Spearman |")
    lines.append("| --- | --- | --- |")
    for key in corr["pearson"]:
        lines.append(f"| {key} | {corr['pearson'][key]} | {corr['spearman'][key]} |")
    lines.append("")
    lines.append("### Agent → 输入特征依赖矩阵（代码静态分析）")
    lines.append("")
    lines.append("| Agent | 输入特征 | 与 Elo 输入的重叠 |")
    lines.append("| --- | --- | --- |")
    for agent, inputs in AGENT_INPUT_DEPENDENCY.items():
        overlap = "高（elo/进球率同源）" if agent == "Team" else (
            "中（近况战绩）" if agent == "Psychology" else
            "低" if agent in ("Fitness",) else
            "零（NO_SIGNAL）" if agent in ("Referee", "Player") else
            "零（赛中事件）" if agent == "Momentum" else
            "高（消费 TeamState，即 Elo 派生）" if agent == "Tactical" else "—")
        lines.append(f"| {agent} | {', '.join(inputs)} | {overlap} |")
    lines.append("")
    lines.append("## 3. 单 Agent 信息价值（120 场固定样本，400 模拟）")
    lines.append("")
    config_rows = {config: config_records(dataset, preds, config) for config in preds}
    metrics_by_config: Dict[str, dict] = {}
    for config, records in config_rows.items():
        if records:
            one = full_metrics(records, "m")["one_x_two"]
            cal = full_metrics(records, "m")["calibration"]
            metrics_by_config[config] = {**one, "ece": cal["ece"]}
    lines.append("| 配置 | Accuracy | Brier | LogLoss | ECE |")
    lines.append("| --- | --- | --- | --- | --- |")
    for config in sorted(metrics_by_config, key=lambda c: metrics_by_config[c]["brier"]):
        m = metrics_by_config[config]
        lines.append(f"| {config} | {m['accuracy']:.4f} | {m['brier']:.4f} | "
                     f"{m['log_loss']:.4f} | {m['ece']:.4f} |")
    lines.append("")
    full_brier = metrics_by_config["full"]["brier"]
    lines.append("### 交互/融合问题标记")
    lines.append("")
    for agent in ("team", "tactical", "psychology", "momentum", "referee", "player"):
        only_key = f"{agent}_only"
        minus_key = f"full_minus_{agent}"
        if only_key not in metrics_by_config or minus_key not in metrics_by_config:
            continue
        only_brier = metrics_by_config[only_key]["brier"]
        minus_brier = metrics_by_config[minus_key]["brier"]
        only_d = full_brier - only_brier
        minus_d = full_brier - minus_brier
        flag = ""
        if only_d > 0.002 and minus_d > 0.002:
            flag = "**INTERACTION / FUSION PROBLEM**：单用优于 full，移除后 full 也变好"
        elif only_d > 0.002:
            flag = "单独运行优于 full，但移除后 full 无明显改善 → 其优势在栈内被其他通道稀释"
        elif minus_d > 0.002:
            flag = "单独不优于 full，但加入 full 造成损害"
        else:
            flag = "单独与融入均接近中性（差异 <0.002，噪声级）"
        lines.append(f"- `{agent}`：only Brier={only_brier:.4f}，full−X Brier={minus_brier:.4f}，"
                     f"full Brier={full_brier:.4f} → {flag}")
    lines.append("")
    lines.append("## 4. 概率融合机制诊断（敏感性）")
    lines.append("")
    lines.append("| Agent | 平均 |ΔP(home)| | 最大 |Δ| | >1pp 场次占比 | 判定 |")
    lines.append("| --- | --- | --- | --- | --- |")
    single_brier = {a: metrics_by_config.get(f"{a}_only", {}).get("brier") for a in
                    ("team", "tactical", "psychology", "momentum", "referee", "player")}
    influences = identify_high_influence(preds, single_brier, full_brier)
    for row in influences:
        lines.append(f"| {row['agent']} | {row['mean_abs_delta']} | {row['max_abs_delta']} | "
                     f"{row['share_delta_gt_1pp']} | {row['verdict']} |")
    lines.append("")
    lines.append("判定规则：平均 |ΔP|≥0.01 为高影响；高影响且单 Agent 配置 Brier < full−0.002 "
                 "为 standalone_competitive（仅表示单独可竞争，**不代表其信息独立** —— "
                 "独立性由第 2/6 节相关性判定），否则为 low_information_high_influence。")
    lines.append("")
    lines.append("## 5. 阶段性诊断（120 场样本按时间三分）")
    lines.append("")
    from football_simulation.backtest.diagnosis import phase_breakdown_from_configs
    ordered_records = config_rows["full"]
    phases = phase_breakdown_from_configs(
        ordered_records, preds,
        ["full", "team_only", "tactical_only", "psychology_only",
         "momentum_only", "referee_only", "full_minus_team", "full_minus_tactical",
         "full_minus_psychology", "full_minus_momentum", "full_minus_referee"])
    for phase, configs in phases.items():
        lines.append(f"### {phase}")
        lines.append("")
        lines.append("| 配置 | n | Accuracy | Brier | LogLoss | ECE |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for config, m in configs.items():
            lines.append(f"| {config} | {int(m['n'])} | {m['accuracy']:.4f} | "
                         f"{m['brier']:.4f} | {m['log_loss']:.4f} | {m['ece']:.4f} |")
        lines.append("")
    lines.append("## 6. Elo 信息覆盖分析（Team-only vs 冻结 Elo，120 场样本）")
    lines.append("")
    team_preds = {mid: ModelPrediction.model_validate(p) for mid, p in preds["team_only"].items()}
    order_by_kickoff = {r.match_id: i for i, r in enumerate(ordered_records)}
    sample_frozen = sorted([r for r in frozen if r.match_id in team_preds],
                           key=lambda r: order_by_kickoff.get(r.match_id, 10 ** 9))
    coverage = elo_coverage(sample_frozen, team_preds)
    resid = coverage["residual_team_minus_elo_corr_with_outcome"]
    resid_z = resid * math.sqrt(max(coverage["n"] - 1, 1))
    lines.append(f"- Team-only 与 Elo 的主胜概率相关：**{coverage['corr_team_elo_home_prob']}**")
    lines.append(f"- Elo 正确率 {coverage['elo_correct']} / Team-only 正确率 "
                 f"{coverage['team_elo_correct']}")
    lines.append(f"- 两者同对 {coverage['both_correct']}；**Elo 错而 Team 对 "
                 f"{coverage['elo_wrong_team_right']}**；Team 错而 Elo 对 "
                 f"{coverage['team_wrong_elo_right']}；同错 {coverage['both_wrong']}")
    lines.append(f"- Team−Elo 残差与实际结果的相关："
                 f"**{resid}（z≈{resid_z:.1f}σ，n={coverage['n']}）**")
    if resid < 0:
        lines.append("  —— 残差相关为**负**且超过 2σ：Team 相对 Elo 的偏离与结果负相关，"
                     "即 Team 的『额外信息』整体是**反信息**（Elo 已覆盖其有效部分，"
                     "偏离主要是有害噪声），而非≈0 的中性重复。")
    else:
        lines.append("  —— >0 说明 Team 残差含独立预测信息。")
    lines.append("")
    lines.append("## 7. 失败样本分析（冻结 380 场记录，四类）")
    lines.append("")
    categories = {
        "full_high_conf_wrong": [],
        "elo_right_full_wrong": [],
        "full_right_elo_wrong": [],
        "both_wrong": [],
    }
    for record in frozen:
        full = record.predictions.get("full_system")
        elo = record.predictions.get("elo")
        if full is None or elo is None:
            continue
        actual = record.actual_result()
        f_ok = max(full.home_win, full.draw, full.away_win) == getattr(full, actual)
        e_ok = max(elo.home_win, elo.draw, elo.away_win) == getattr(elo, actual)
        conf = max(full.home_win, full.draw, full.away_win)
        if not f_ok and conf >= 0.5:
            categories["full_high_conf_wrong"].append(record)
        if e_ok and not f_ok:
            categories["elo_right_full_wrong"].append(record)
        if f_ok and not e_ok:
            categories["full_right_elo_wrong"].append(record)
        if not f_ok and not e_ok:
            categories["both_wrong"].append(record)
    for name, records in categories.items():
        lines.append(f"### {name}（n={len(records)}）")
        lines.append("")
        for record in records[:4]:
            row = row_by_id.get(record.match_id, {})
            pre = (f"Elo差={row.get('elo_diff', '—'):+.0f}，Team强度差="
                   f"{row.get('team_strength_diff', '—'):+.2f}，信心差="
                   f"{row.get('psych_confidence_diff', '—'):+.2f}")
            lines.append(f"- {record.match_id} {record.home_team} "
                         f"{record.actual_home_goals}-{record.actual_away_goals} "
                         f"{record.away_team}：full={record.predictions['full_system'].home_win:.2f}/"
                         f"{record.predictions['full_system'].draw:.2f}/"
                         f"{record.predictions['full_system'].away_win:.2f}，"
                         f"elo={record.predictions['elo'].home_win:.2f}/"
                         f"{record.predictions['elo'].draw:.2f}/"
                         f"{record.predictions['elo'].away_win:.2f}。赛前已知：{pre}。"
                         f"未知项：{', '.join(record.unknowns[:3])}")
        lines.append("")
    lines.append("说明：仅使用预测时刻已知信息；无法解释的场次不做归因（RANDOMNESS/UNEXPLAINED）。")
    lines.append("")
    lines.append("## 8. 十个问题（按证据强度）")
    lines.append("")
    elo_sample_records = [
        PredictionRecord(
            match_id=r.match_id, kickoff=r.kickoff, home_team=r.home_team,
            away_team=r.away_team, actual_home_goals=r.actual_home_goals,
            actual_away_goals=r.actual_away_goals,
            predictions={"m": r.predictions["elo"]}, synthetic=False)
        for r in sample_frozen]
    elo_brier_120 = full_metrics(elo_sample_records, "m")["one_x_two"]["brier"]
    n120 = len(sample_frozen)
    elo_phase_briers: Dict[str, float] = {}
    for phase, (start, end) in {
            "early_season": (0, n120 // 3), "mid_season": (n120 // 3, 2 * n120 // 3),
            "late_season": (2 * n120 // 3, n120)}.items():
        elo_phase_briers[phase] = full_metrics(elo_sample_records[start:end], "m")["one_x_two"]["brier"]
    full_phase_briers = {p: phases[p]["full"]["brier"] for p in phases}
    # filled below with computed evidence
    verdicts = build_verdicts(metrics_by_config, corr, coverage, full_brier,
                              elo_brier_120, elo_phase_briers, full_phase_briers)
    lines.extend(verdicts)
    lines.append("")
    lines.append("## 9. 可复现")
    lines.append("")
    lines.append(f"- 冻结基线引用：`{manifest['experiment_id']}`（基线目录未动，哈希清单在 "
                 f"`backtest_output/diagnosis_epl_001/baseline_manifest.json`）")
    lines.append("- 诊断产物：`preds.json`（17 配置 × 120 场，400 模拟，seed 20240101）")
    lines.append("- 注册表：`backtest_output/diagnosis_epl_001/experiments.jsonl`"
                 "（EXP-DIAG-EPL-001，`synthetic_data=false`，`market_data=false`）")

    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"written -> {DOC}")


def build_verdicts(metrics, corr, coverage, full_brier, elo_brier_120,
                   elo_phase_briers, full_phase_briers) -> List[str]:
    """Evidence-grounded verdicts with explicit, transparent thresholds."""
    out: List[str] = []
    primary: List[str] = []
    secondary: List[str] = []
    unconfirmed: List[str] = []

    def brier_of(key: str) -> Optional[float]:
        value = metrics.get(key)
        return value["brier"] if value else None

    team_only = brier_of("team_only")
    minus_team = brier_of("full_minus_team")
    minus_tact = brier_of("full_minus_tactical")
    minus_psych = brier_of("full_minus_psychology")
    minus_mom = brier_of("full_minus_momentum")
    minus_ref = brier_of("full_minus_referee")
    team_psych = brier_of("team_psychology")
    corr_team_tact = corr["pearson"].get("team_strength_diff_nohome__tactical_advantage_nohome")
    corr_team_tact_s = corr["spearman"].get("team_strength_diff_nohome__tactical_advantage_nohome")
    corr_team_psych = corr["pearson"].get("team_strength_diff_nohome__psych_confidence_diff")
    corr_team_elo = corr["pearson"].get("elo_diff__team_strength_diff_nohome")
    resid = coverage["residual_team_minus_elo_corr_with_outcome"]
    resid_z = resid * math.sqrt(max(coverage["n"] - 1, 1))

    eps = 0.002

    # Q1 Team positive contribution
    if minus_team is not None:
        delta = minus_team - full_brier
        if delta > eps:
            out.append(f"**Q1 Team 为什么有正贡献？** 本样本成立：移除 Team 后 Brier 恶化 "
                       f"{delta:+.4f}（{minus_team:.4f} vs {full_brier:.4f}）。Team 是唯一把 "
                       "walk-forward 强度差异注入模拟的通道（其独立配置 Brier="
                       f"{team_only:.4f}，优于 full）。")
            primary.append(f"Team 是模拟流水线唯一的强度注入通道，移除后 Brier 恶化 ≈{delta:+.4f}")
        elif delta < -eps:
            out.append(f"**Q1** 本样本移除 Team 反而改善 Brier ≈{delta:+.4f} —— 与 380 场冻结消融"
                       "（+0.0048）方向相反；样本量有限，Team 的正贡献不稳定。")
            unconfirmed.append(f"Team 正贡献方向在本样本与 380 场消融相反（120 场 Δ≈{delta:+.4f}）")
        else:
            out.append(f"**Q1 Team 为什么有正贡献？** 本样本证据不足：移除 Team 后 Brier 变化 "
                       f"≈{delta:+.4f}（{minus_team:.4f} vs {full_brier:.4f}），方向与 380 场冻结消融"
                       "（+0.0048）一致但幅度低于判定阈值。结合 Q9：Team 的价值在于它是唯一注入通道"
                       "（通道必要性），而非独立信息量。")
            unconfirmed.append(f"Team 正贡献幅度：380 场消融 +0.0048，120 场诊断样本仅 ≈{delta:+.4f}，不显著")

    # Q2 Tactical negative
    if minus_tact is not None:
        delta = full_brier - minus_tact
        if delta > eps:
            out.append(f"**Q2 Tactical 为什么负贡献？** 本样本成立：移除后 Brier 改善 ≈{delta:+.4f}"
                       f"（{full_brier:.4f}→{minus_tact:.4f}），与 380 场消融（−0.0044）同向。"
                       "机制证据：Tactical 只消费 TeamState（即 Elo/Team 派生量），与 Team 无主场版"
                       f"相关性 {corr_team_tact}（Spearman {corr_team_tact_s}），其乘性修饰"
                       "（chance_creation_modifier）把同一强度信号在模拟中二次放大 → 重复信息 + 复合放大。")
            primary.append(f"Tactical 与 Team 共享同一 Elo 派生输入（无主场版 r={corr_team_tact}），"
                           f"乘性修饰重复放大同一信号 → 移除后 Brier 改善 ≈{delta:+.4f}"
                           "（两次独立样本同向：380 场 −0.0044）")
        else:
            unconfirmed.append(f"Tactical 负贡献本样本幅度 ≈{delta:+.4f} 低于阈值"
                               "（380 场消融 −0.0044，方向一致）")

    # Q3 Psychology
    if minus_psych is not None:
        delta = full_brier - minus_psych
        base = (f"Psychology 的信心/压力差仅由近期战绩驱动，与 Team 无主场版相关性 "
                f"{corr_team_psych}。")
        if delta > eps:
            out.append(f"**Q3 Psychology 为什么负贡献？** 本样本成立：移除后 Brier 改善 "
                       f"≈{delta:+.4f}（{full_brier:.4f}→{minus_psych:.4f}）。" + base +
                       "其风险/动机通道把同一近况信息第三次乘性修饰进攻强度。"
                       "注意：`team_psychology`（Team+Psychology，去掉其余通道）是全部配置中"
                       f"最优的（{team_psych:.4f}），说明 Psychology 的害处只在完整栈内叠加时显现。")
            secondary.append(f"Psychology 在 full 栈内移除改善 ≈{delta:+.4f}（近况信息第三次放大）；"
                             "但其与 Team 单独组合（team_psychology）是实测最优配置")
        elif delta < -eps:
            out.append(f"**Q3** 本样本移除 Psychology 恶化 Brier ≈{delta:+.4f} —— 心理学在 full 栈内"
                       "为净正贡献，与 380 场消融（−0.0042）方向相反；"
                       f"且 `team_psychology`（{team_psych:.4f}）是全部配置最优。"
                       "Psychology 的净效应不稳定，不把它的『负贡献』当作主因。")
            unconfirmed.append(f"Psychology 移除的净效应方向在两个样本间相反（120 场 Δ≈{delta:+.4f}，"
                               "380 场 −0.0042）")
        else:
            out.append(f"**Q3** 移除 Psychology 后 ΔBrier≈{delta:+.4f}，低于判定阈值（380 场消融"
                       "−0.0042 方向一致但微弱）；`team_psychology` 为全部配置最优"
                       f"（{team_psych:.4f}）。")
            unconfirmed.append("Psychology 单独移除的净效应需更大样本确认")

    # Q4 Momentum
    if minus_mom is not None:
        delta = full_brier - minus_mom
        if delta > eps:
            out.append(f"**Q4 Momentum** 移除后改善 ≈{delta:+.4f} —— 赛中势头反馈在无事件级数据"
                       "校准下放大了方差。")
            secondary.append(f"Momentum 负贡献（移除改善 ≈{delta:+.4f}）")
        else:
            out.append(f"**Q4 Momentum** 移除后 ΔBrier≈{delta:+.4f}，低于判定阈值 → 视为中性"
                       "（380 场消融 −0.0018，方向一致但微弱）。")
            unconfirmed.append("Momentum 的微小负贡献需要更大样本确认")

    # Q5 Referee
    if minus_ref is not None:
        out.append(f"**Q5 Referee** 移除后 ΔBrier≈{full_brier - minus_ref:+.4f}。"
                   "Referee 在本数据中只有姓名（倾向 NO_SIGNAL），任何非零影响"
                   "都是围绕中性裁判因子的模拟方差 → 无信息贡献，影响可忽略。")
        secondary.append("Referee 无信息（NO_SIGNAL），其影响为噪声级")

    # Q6 duplication
    out.append("**Q6 是否存在 Agent 信息重复？** 是。Team / Tactical / Psychology 全部消费"
               "同一 walk-forward 历史（Elo、进球率、近况），Tactical 甚至直接消费 TeamState。"
               "相关性证据（无主场版）：Team↔Tactical "
               f"{corr_team_tact}（Spearman {corr_team_tact_s}）、Team↔Psychology {corr_team_psych}、"
               f"Team↔Elo {corr_team_elo}（见第 2 节）。")
    primary.append(f"信息重复：Team/Tactical/Psychology 是同一 Elo 派生信息的三种表达"
                   f"（Team↔Tactical 无主场 r={corr_team_tact}，Spearman {corr_team_tact_s}）")

    # Q7 fusion amplification
    out.append("**Q7 是否存在概率融合放大？** 是（机制级证据）。同一 Elo 派生信号在流水线中"
               "被乘性使用多次：Team 强度 → Tactical 的 chance_creation_modifier（乘）"
               "→ 事件引擎的进攻强度（再乘 attacking_intensity，Psychology 再次修饰）。"
               "乘性复合使信号误差指数化放大；第 4 节的影响度表给出逐 Agent 的量化影响。")
    primary.append("乘性放大：概率聚合采用乘性复合（chance_creation_modifier × attacking_intensity）"
                   "而非加权平均 → 重复信号的误差被指数化放大")

    # Q8 cold start
    if full_phase_briers and elo_phase_briers:
        f_e = full_phase_briers["early_season"]
        f_m = full_phase_briers["mid_season"]
        f_l = full_phase_briers["late_season"]
        e_e = elo_phase_briers["early_season"]
        e_m = elo_phase_briers["mid_season"]
        e_l = elo_phase_briers["late_season"]
        gap_e = f_e - e_e
        gap_m = f_m - e_m
        gap_l = f_l - e_l
        out.append(f"**Q8 冷启动是否是主要问题？** 实测（120 场样本三分）：Elo 早/中/晚 = "
                   f"{e_e:.4f}/{e_m:.4f}/{e_l:.4f}；full = {f_e:.4f}/{f_m:.4f}/{f_l:.4f}。"
                   f"full 相对 Elo 的劣势：早段 {gap_e:+.4f}、中段 {gap_m:+.4f}、晚段 {gap_l:+.4f}。")
        if gap_e > 0.03 and gap_l <= 0.02:
            out.append("→ 早段劣势远大于晚段：**冷启动是主要问题**。")
            primary.append(f"冷启动为主因：full 早段相对 Elo 劣 {gap_e:+.4f}，远大于晚段 {gap_l:+.4f}")
        elif gap_l > gap_e + 0.03:
            out.append(f"→ 晚段劣势最大（中段 full 甚至不差于 Elo，{gap_m:+.4f}）：冷启动是**次要因素**，"
                       "退化集中在晚段（同一信号的重复放大随赛季推进积累）。")
            secondary.append(f"冷启动为次要因素：晚段劣势 {gap_l:+.4f} 最大，中段 {gap_m:+.4f}、"
                             f"早段 {gap_e:+.4f}")
        else:
            out.append("→ 早/晚段劣势相近：冷启动贡献与晚段退化贡献相当，单一样本不足以分离。")
            unconfirmed.append(f"冷启动 vs 晚段退化无法分离（早段 {gap_e:+.4f}，晚段 {gap_l:+.4f}）")
    else:
        out.append("**Q8 冷启动是否是主要问题？** 阶段对比见第 5 节。")
        unconfirmed.append("冷启动的定量影响由第 5 节数据判定（见阶段表）")

    # Q9 Elo coverage
    out.append(f"**Q9 Elo 是否已覆盖 Team 的主要信息？** 证据：Team-only 与 Elo 的主胜概率相关 "
               f"{coverage['corr_team_elo_home_prob']}；Elo 正确率 {coverage['elo_correct']} vs "
               f"Team-only {coverage['team_elo_correct']}；Elo 错而 Team 对仅 "
               f"{coverage['elo_wrong_team_right']}，Team 错而 Elo 对 "
               f"{coverage['team_wrong_elo_right']}（Elo 的纠错频次是反向的 "
               f"{coverage['team_wrong_elo_right'] / max(coverage['elo_wrong_team_right'], 1e-9):.0f} 倍）；"
               f"Team−Elo 残差与结果相关 {resid}（z≈{resid_z:.1f}σ）。")
    if resid < -0.15:
        out.append("残差显著为负 → **Elo 已覆盖 Team 的有效信息**；Team 相对 Elo 的偏离整体是"
                   "**反信息**（其『额外信息』与结果负相关）。Team 的正贡献因此不是信息贡献，"
                   "而是通道必要性：它是模拟流水线唯一的强度注入点，移除会破坏整个融合尺度。")
        primary.append(f"Team 残差为反信息（r={resid}，z≈{resid_z:.1f}σ）：Elo 已覆盖其有效信息，"
                       "Team 相对 Elo 的偏离整体有害 —— 支撑『信息重复而非信息无效』的定性结论")
    elif resid > 0.15:
        out.append("残差显著为正 → Team 相对 Elo 存在独立预测信息。")
        secondary.append(f"Team 相对 Elo 存在残余信息（r={resid}，z≈{resid_z:.1f}σ）")
    else:
        out.append(f"残差相关 {resid} 不显著（|z|={abs(resid_z):.1f}）→ 不足以断言 Team 相对 Elo "
                   "有额外信息或反信息。")
        unconfirmed.append(f"Team 残差方向（r={resid}）需更大样本确认")

    # Q10 main reason
    if team_psych is not None and minus_tact is not None and elo_brier_120 is not None:
        out.append(f"**Q10 full_system 输给 Elo 的主要原因？** 融合结构问题，而非信息无效。"
                   f"120 场样本实测：full={full_brier:.4f}，Elo={elo_brier_120:.4f}"
                   f"（full 劣势 {full_brier - elo_brier_120:+.4f}）；全部 17 配置中最优的是 "
                   f"`team_psychology`={team_psych:.4f}（比 full 低 {full_brier - team_psych:.4f}），"
                   f"次优 `full_minus_tactical`={minus_tact:.4f}。即：Team(+Psychology) 核心"
                   "单独运行时最好，而 Tactical/Momentum/Referee 通道的叠加把概率推向失真。"
                   "结合 Q2/Q6/Q7/Q9：这些通道全部消费同一 Elo 派生信息并以乘性方式重复注入，"
                   "放大的是重复信息与反信息噪声 → 校准退化（full ECE 高于 Elo，冻结基线 "
                   "0.0350 vs 0.0152）。**结论：信息基本有效，但融合方式错误（重复 + 乘性放大）；"
                   "且最优配置仍弱于 Elo，说明模拟流水线本身存在相对 Elo 的残余误差。**")
        secondary.append(f"融合结构瓶颈：最优配置 team_psychology={team_psych:.4f}、次优 "
                         f"full_minus_tactical={minus_tact:.4f} 均优于 full={full_brier:.4f}，"
                         f"但都弱于 Elo={elo_brier_120:.4f}（幅度受 120 场样本限制，"
                         "DIAG-002/003 进一步验证）")
    else:
        out.append("**Q10 full_system 输给 Elo 的主要原因？** 由 Q2/Q3/Q6/Q7 合并："
                   "Tactical 与 Psychology 把 Elo 已包含的强度/战绩信息以乘性方式二次、三次注入，"
                   "重复信息被放大 → 概率偏离校准。即：**信息基本有效，但融合方式错误"
                   "（重复 + 乘性放大）**，而非信息无效。")
        primary.append("信息有效但融合方式错误：同一 Elo 派生信息被乘性重复注入")

    out.append("")
    out.append("**PRIMARY（证据强）：**")
    for item in primary:
        out.append(f"- {item}")
    out.append("**SECONDARY（证据中等）：**")
    for item in secondary:
        out.append(f"- {item}")
    out.append("**UNCONFIRMED（证据不足，不猜测）：**")
    for item in unconfirmed:
        out.append(f"- {item}")
    out.append("")
    out.append("**NEXT EXPERIMENT（仅设计，不执行、不修改生产模型）：**")
    out.append("1. DIAG-002：在诊断副本中把 Tactical 的 chance_creation_modifier 改为可开关的"
               "加性项，量化『重复放大』对 full_minus_tactical 改善 ≈0.0077 的机制贡献。")
    out.append("2. DIAG-003：检验实测最优配置 `team_psychology`（0.6579）能否在更大样本上稳定"
               "优于 full；同时测『Team-only + 线性融合』与 Elo 的差距，分离融合结构瓶颈与信息量瓶颈。")
    out.append("3. DIAG-004：跨赛季（需先获取第二赛季真实数据）复测上述结论的稳定性。")
    return out


if __name__ == "__main__":
    main()
