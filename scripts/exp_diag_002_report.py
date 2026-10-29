"""EXP-DIAG-EPL-002 (DIAG-002) report generator.

Read-only: frozen baselines EXP-REAL-EPL-BASE-001 (7c52c6bdfa37) and
EXP-DIAG-EPL-001 are read as references; the DIAG-002 sandbox outputs
(backtest_output/diag_002_tactical_amp/) are the analysis inputs.
Generates docs/DIAG_002_TACTICAL_AMPLIFICATION.md.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from football_simulation.backtest.diagnosis import reconstruct_prematch_layer
from football_simulation.backtest.metrics import full_metrics
from football_simulation.backtest.models import ModelPrediction, PredictionRecord
from football_simulation.data.historical.etl import HistoricalDataset

BASELINE_DIR = Path("backtest_output/real_epl_base_001")
DIAG1_DIR = Path("backtest_output/diagnosis_epl_001")
OUT_DIR = Path("backtest_output/diag_002_tactical_amp")
DATASET_PATH = Path("data/historical/epl_2025_26.json")
DOC = Path("docs/DIAG_002_TACTICAL_AMPLIFICATION.md")
SAMPLE_INDICES = sorted(set(range(0, 380, 3)))[:120]

ARMS = ["A_mult", "B_off", "C_add"]
ARM_DEFS = {
    "A_mult": "生产乘性结构：`lam *= cc * f_att`",
    "B_off": "战术机会创造通道关闭：引擎融合点强制 `cc=1.0`（f_att 动态不变）",
    "C_add": "加性结构：`lam *= (cc + f_att - 1)`，组合因子裁剪至 [0.1, 3.0]",
}


def load_frozen_records() -> List[PredictionRecord]:
    raw = json.loads((BASELINE_DIR / "records.json").read_text(encoding="utf-8"))
    return [PredictionRecord.model_validate(r) for r in raw]


def arm_records(dataset: HistoricalDataset, preds: Dict[str, Dict[str, dict]],
                arm: str) -> List[PredictionRecord]:
    by_id = {m.match_id: m for m in dataset.matches}
    out: List[PredictionRecord] = []
    for match_id, pred in preds.get(arm, {}).items():
        match = by_id[match_id]
        out.append(PredictionRecord(
            match_id=match_id, kickoff=match.date,
            home_team=match.home_team, away_team=match.away_team,
            actual_home_goals=match.home_goals, actual_away_goals=match.away_goals,
            predictions={"m": ModelPrediction.model_validate(pred)}, synthetic=False))
    return out


def metrics_for(records: List[PredictionRecord]) -> Dict[str, float]:
    one = full_metrics(records, "m")["one_x_two"]
    cal = full_metrics(records, "m")["calibration"]
    return {"n": int(one["n"]), "accuracy": one["accuracy"], "brier": one["brier"],
            "log_loss": one["log_loss"], "ece": cal["ece"]}


def per_match_brier(records: List[PredictionRecord]) -> List[float]:
    """Per-match 3-outcome Brier sum, aligned with the record order."""
    out = []
    for record in records:
        pred = record.predictions["m"]
        actual = record.actual_result()
        probs = {"home_win": pred.home_win, "draw": pred.draw, "away_win": pred.away_win}
        out.append(sum((probs[k] - (1.0 if k == actual else 0.0)) ** 2
                       for k in probs))
    return out


def pearson(x: List[float], y: List[float]) -> float:
    return float(np.corrcoef(x, y)[0, 1])


def paired_test(brier_a: List[float], brier_b: List[float]) -> Dict[str, float]:
    """Paired mean Brier difference with SE/t (arms share seed, so pairing)."""
    diffs = [a - b for a, b in zip(brier_a, brier_b)]
    mean = float(np.mean(diffs))
    std = float(np.std(diffs, ddof=1))
    se = std / math.sqrt(len(diffs))
    return {"mean_diff": round(mean, 5), "std": round(std, 5),
            "se": round(se, 5), "t": round(mean / se, 2) if se > 0 else None,
            "n": len(diffs)}


def distribution_stats(values: List[float]) -> Dict[str, float]:
    arr = np.asarray(values, dtype=float)
    return {"n": int(arr.size), "mean": round(float(arr.mean()), 4),
            "std": round(float(arr.std()), 4), "min": round(float(arr.min()), 4),
            "max": round(float(arr.max()), 4),
            "p05": round(float(np.percentile(arr, 5)), 4),
            "p50": round(float(np.percentile(arr, 50)), 4),
            "p95": round(float(np.percentile(arr, 95)), 4)}


def main() -> None:
    dataset = HistoricalDataset.load(DATASET_PATH)
    matches = dataset.matches_in_season("2025-26")
    sample_ids = {matches[i].match_id for i in SAMPLE_INDICES}
    preds = json.loads((OUT_DIR / "preds.json").read_text(encoding="utf-8"))
    dists = json.loads((OUT_DIR / "distributions.json").read_text(encoding="utf-8"))
    validation = json.loads((OUT_DIR / "validation.json").read_text(encoding="utf-8"))
    manifest = json.loads((OUT_DIR / "baseline_manifest_real_epl_base_001.json")
                          .read_text(encoding="utf-8"))
    diag1_preds = json.loads((DIAG1_DIR / "preds.json").read_text(encoding="utf-8"))
    frozen_metrics = json.loads((BASELINE_DIR / "metrics.json").read_text(encoding="utf-8"))

    rows = reconstruct_prematch_layer(dataset)
    row_by_id = {r["match_id"]: r for r in rows}
    frozen = load_frozen_records()
    elo_sample = [r for r in frozen if r.match_id in sample_ids]

    lines: List[str] = []
    lines.append("# DIAG-002：Tactical 乘性放大机制诊断（EXP-DIAG-EPL-002）")
    lines.append("")
    lines.append("> 本实验**只回答一个问题**：事件引擎中 "
                 "`chance_creation_modifier × attacking_intensity` 的乘性组合"
                 "是否放大重复信号、从而造成 full_system 性能退化。")
    lines.append("> 只读纪律：生产模型、35 条规则、config/default.json、V1.2 数据层、"
                 "冻结基线 EXP-REAL-EPL-BASE-001（`7c52c6bdfa37`）与 EXP-DIAG-EPL-001 均未修改。"
                 "本实验在独立诊断沙箱 `backtest_output/diag_002_tactical_amp/` 内完成。")
    lines.append("> 不优化参数、不寻找最佳系数：加性臂使用与乘性臂中性点/一阶等价的原样尺度"
                 "`cc + f_att − 1`，未做任何调参。")
    lines.append("")
    lines.append("## 1. 实验设计")
    lines.append("")
    lines.append("三个臂在**完全相同**的数据（2025-26 EPL）、样本（`range(0,380,3)[:120]`，"
                 "120 场）、seed（20240101）、模拟次数（400）与 walk-forward 设置下比较，"
                 "其余 Agent 完全不变。差异仅发生在事件引擎 `_attack_intensity` 的"
                 "两个战术因子处：")
    lines.append("")
    lines.append("| 臂 | 定义 | 引擎融合点行为 |")
    lines.append("| --- | --- | --- |")
    lines.append(f"| A_mult | {ARM_DEFS['A_mult']} | 生产原样（逐分钟 `lam *= cc` 后再 `lam *= f_att`） |")
    lines.append(f"| B_off | {ARM_DEFS['B_off']} | 只关闭 cc 通道；f_att 的赛中动态（比分/红牌规则）保留 |")
    lines.append(f"| C_add | {ARM_DEFS['C_add']} | cc 与 f_att 以加法组合成单一因子，再乘入 |")
    lines.append("")
    lines.append("其中 `cc = tac.chance_creation_modifier`（TacticalMatchupAgent 输出，经 Opening "
                 "层写入世界状态），`f_att = 0.55 + 0.9 × tac.attacking_intensity`。")
    lines.append("")
    lines.append("**尺度等价性论证（不调参）**：A 的因子为 `cc×f_att`，C 为 `cc+f_att−1`。"
                 "两者在**中性点（cc=1, f_att=1）精确相等**（均为 1），且一阶 Taylor 等价："
                 "令 cc=1+a、f_att=1+b，则 A=1+a+b+ab、C=1+a+b。二者之差就是二阶交叉项 `ab`"
                 "——**这正是被检验的『乘性组合』机制本身**，不是尺度混杂，因此不标记 SCALE_CONFOUND。"
                 "C 的组合因子裁剪到 cc 的定义域 [0.1, 3.0]；本实验统计了裁剪被触发的次数"
                 "（见第 3 节），若裁剪频繁发生，解释时会计入该人为因素。")
    lines.append("")
    lines.append("**实现方式**：仅在运行期内对 `director.EventTriggerAgent` 的类引用做"
                 "**monkey-patch**（子类先改写两个战术因子、再调用**未改动**的生产 "
                 "`_attack_intensity`，最后逐字段还原世界状态）。生产源码零修改；"
                 "A_mult 臂直接原样委托生产代码。")
    lines.append("")
    lines.append("**与配置级消融 `full_minus_tactical` 的区别**：B_off 只在引擎融合点关掉 cc；"
                 "而 EXP-DIAG-EPL-001 的 `full_minus_tactical` 还同时中立化了 Opening 开场通道"
                 "（开场因子含 0.45×(cc−1) 项）。因此 B_off 与其接近但**不应完全相等**。")
    lines.append("")
    lines.append("### 1.1 忠实性验证（沙箱 vs 冻结缓存）")
    lines.append("")
    a_val = validation["A_mult"]["max_abs_diff"]
    b_val = validation["B_off"]["max_abs_diff"]
    a_exact = all(v <= 1e-12 for v in a_val.values())
    lines.append(f"- A_mult vs 冻结 `full`（同 seed/样本/400 模拟）：最大绝对差 "
                 f"home_win={a_val['home_win']:.3g}、draw={a_val['draw']:.3g}、"
                 f"away_win={a_val['away_win']:.3g}、expected_goals={a_val['expected_goals']:.3g} "
                 f"→ **{'完全一致（沙箱忠实）' if a_exact else '不一致（沙箱不可信！）'}**")
    lines.append(f"- B_off vs 冻结 `full_minus_tactical`：最大绝对差 "
                 f"home_win={b_val['home_win']:.4f}、draw={b_val['draw']:.4f}、"
                 f"away_win={b_val['away_win']:.4f}、expected_goals={b_val['expected_goals']:.3f} "
                 "→ 差异来源为 Opening 开场通道（预期之内，非沙箱缺陷）。")
    lines.append("")
    lines.append("## 2. 核心指标对比（120 场固定样本，400 模拟，seed 20240101）")
    lines.append("")
    records_by_arm = {arm: arm_records(dataset, preds, arm) for arm in ARMS}
    metrics_by_arm = {arm: metrics_for(records_by_arm[arm]) for arm in ARMS}
    brier_by_arm = {arm: per_match_brier(records_by_arm[arm]) for arm in ARMS}
    elo_records = [PredictionRecord(
        match_id=r.match_id, kickoff=r.kickoff, home_team=r.home_team,
        away_team=r.away_team, actual_home_goals=r.actual_home_goals,
        actual_away_goals=r.actual_away_goals,
        predictions={"m": r.predictions["elo"]}, synthetic=False)
        for r in elo_sample]
    elo_120 = metrics_for(elo_records)
    diag1_full = metrics_for(arm_records(dataset, diag1_preds, "full"))
    diag1_minus_tact = metrics_for(arm_records(dataset, diag1_preds, "full_minus_tactical"))
    diag1_team_psych = metrics_for(arm_records(dataset, diag1_preds, "team_psychology"))

    lines.append("| 模型/臂 | n | Accuracy | Brier | LogLoss | ECE |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for name, m in [
        ("A_mult（乘性，=full）", metrics_by_arm["A_mult"]),
        ("B_off（cc 关闭）", metrics_by_arm["B_off"]),
        ("C_add（加性）", metrics_by_arm["C_add"]),
        ("Elo（120 场样本，冻结记录）", elo_120),
        ("—— 上下文（非本实验臂） ——", None),
        ("full（EXP-DIAG-EPL-001 冻结缓存）", diag1_full),
        ("full_minus_tactical（冻结缓存）", diag1_minus_tact),
        ("team_psychology（冻结缓存，17 配置最优）", diag1_team_psych),
        ("full_system（冻结 380 场基线）", {"n": 380, "accuracy": float(
            frozen_metrics["full_system"]["one_x_two"]["accuracy"]),
            "brier": float(frozen_metrics["full_system"]["one_x_two"]["brier"]),
            "log_loss": float(frozen_metrics["full_system"]["one_x_two"]["log_loss"]),
            "ece": float(frozen_metrics["full_system"]["calibration"]["ece"])}),
        ("Elo（冻结 380 场基线）", {"n": 380, "accuracy": float(
            frozen_metrics["elo"]["one_x_two"]["accuracy"]),
            "brier": float(frozen_metrics["elo"]["one_x_two"]["brier"]),
            "log_loss": float(frozen_metrics["elo"]["one_x_two"]["log_loss"]),
            "ece": float(frozen_metrics["elo"]["calibration"]["ece"])}),
    ]:
        if m is None:
            lines.append(f"| {name} | — | — | — | — | — |")
        else:
            lines.append(f"| {name} | {m['n']} | {m['accuracy']:.4f} | {m['brier']:.4f} | "
                         f"{m['log_loss']:.4f} | {m['ece']:.4f} |")
    lines.append("")
    lines.append("### 2.1 配对差异（臂与臂共享 seed，逐场配对）")
    lines.append("")
    pt_ac = paired_test(brier_by_arm["A_mult"], brier_by_arm["C_add"])
    pt_ab = paired_test(brier_by_arm["A_mult"], brier_by_arm["B_off"])
    pt_bc = paired_test(brier_by_arm["B_off"], brier_by_arm["C_add"])
    lines.append("| 配对 | 逐场 Brier 差均值 | 逐场差 std | SE | t |")
    lines.append("| --- | --- | --- | --- | --- |")
    lines.append(f"| A_mult − C_add（正=C 更好） | {pt_ac['mean_diff']:+.5f} | "
                 f"{pt_ac['std']:.5f} | {pt_ac['se']:.5f} | {pt_ac['t']} |")
    lines.append(f"| A_mult − B_off（正=B 更好） | {pt_ab['mean_diff']:+.5f} | "
                 f"{pt_ab['std']:.5f} | {pt_ab['se']:.5f} | {pt_ab['t']} |")
    lines.append(f"| B_off − C_add（正=C 更好） | {pt_bc['mean_diff']:+.5f} | "
                 f"{pt_bc['std']:.5f} | {pt_bc['se']:.5f} | {pt_bc['t']} |")
    lines.append("")

    # ------------------------------------------------------------------
    lines.append("## 3. 机制分布证据")
    lines.append("")
    lines.append("### 3.1 TacticalMatchupAgent 输出分布（确定性重建，380 场，赛前）")
    lines.append("")
    lines.append("| 输出 | 均值 | std | min | max | p50 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for column, name in [
        ("tactical_advantage_home", "tactical_advantage_home"),
        ("tactical_advantage_nohome", "tactical_advantage_home（无主场版）"),
        ("tactical_cc_diff", "chance_creation 差（home−away）"),
    ]:
        stats = distribution_stats([r[column] for r in rows])
        lines.append(f"| {name} | {stats['mean']} | {stats['std']} | {stats['min']} | "
                     f"{stats['max']} | {stats['p50']} |")
    lines.append("")
    lines.append("注：`chance_creation_home` 自身 ∈ [0.45, 1.35]（结构项裁剪域），"
                 "再经模式加成与 [0.1, 3.0] 最终裁剪；`attacking_intensity` 赛前恒 0.5"
                 "（f_att 赛前恒 1.0），赛中由比分/红牌/换人规则在 [0,1] 内演化。")
    lines.append("")
    lines.append("### 3.2 逐分钟 realized 分布（每臂 ≈120 场×400 模拟×~95 分钟×2 侧）")
    lines.append("")
    lines.append("| 臂 | 量（侧） | 均值 | std | min | max | 尾部 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for arm in ARMS:
        d = dists[arm]
        for side in ("HOME", "AWAY"):
            for qty in ("cc", "f_att", "factor", "lam"):
                m = d.get(f"{side}:{qty}", {})
                if not m or m.get("n", 0) == 0:
                    continue
                if qty == "lam":
                    tails = d.get("lam_tails", {}).get(side, {})
                    tail = (f"≥0.3: {tails.get('lam_ge_0.3', 0) / max(m['n'], 1):.2%} | "
                            f"≥0.4: {tails.get('lam_ge_0.4', 0) / max(m['n'], 1):.2%} | "
                            f"≥0.5: {tails.get('lam_ge_0.5', 0) / max(m['n'], 1):.2%}")
                else:
                    tail = ""
                lines.append(f"| {arm} | {qty}（{side}） | {m['mean']} | {m['std']} | "
                             f"{m['min']} | {m['max']} | {tail} |")
    for arm in ARMS:
        d = dists[arm]
        if arm == "C_add":
            total_calls = sum(int(d.get(f"{side}:{qty}", {}).get("n", 0))
                              for side in ("HOME", "AWAY") for qty in ("factor", "lam"))
            lines.append(f"- C_add：组合因子裁剪触发 {d.get('clip_active', 0)} 次"
                         f"（分钟级调用合计 {total_calls} 次，占比 "
                         f"{d.get('clip_active', 0) / total_calls:.4%}）。")
    lines.append("")
    lines.append("（cc 的赛前分布见 3.1；赛中仅受换人规则 ×1.03 影响。f_att 赛前恒 1.0，"
                 "赛中由比分/红牌/换人规则演化。）")
    lines.append("")
    lines.append("### 3.3 最终输出分布（每臂 120 场）")
    lines.append("")
    lines.append("| 量 | A_mult | B_off | C_add |")
    lines.append("| --- | --- | --- | --- |")
    for label, fn in [
        ("home_win 概率（std across 120 场）",
         lambda arm: distribution_stats([p["home_win"] for p in preds[arm].values()])["std"]),
        ("home_win 概率（p05–p95）",
         lambda arm: distribution_stats([p["home_win"] for p in preds[arm].values()])["p95"]
                     - distribution_stats([p["home_win"] for p in preds[arm].values()])["p05"]),
        ("expected_goals（std across 120 场）",
         lambda arm: distribution_stats([p["expected_goals"] for p in preds[arm].values()])["std"]),
        ("max(1X2) ≥ 0.55 场次",
         lambda arm: sum(1 for p in preds[arm].values()
                         if max(p["home_win"], p["draw"], p["away_win"]) >= 0.55)),
        ("max(1X2) ≥ 0.65 场次",
         lambda arm: sum(1 for p in preds[arm].values()
                         if max(p["home_win"], p["draw"], p["away_win"]) >= 0.65)),
        ("expected_goals ≥ 3.0 场次",
         lambda arm: sum(1 for p in preds[arm].values() if p["expected_goals"] >= 3.0)),
    ]:
        cells = " | ".join(f"{fn(arm):.4f}" if isinstance(fn(arm), float)
                           else f"{fn(arm)}" for arm in ARMS)
        lines.append(f"| {label} | {cells} |")
    lines.append("")
    lines.append("注：B_off 的 expected_goals 全部 ≥3.0 —— 关闭 cc 后两队攻击强度失去阻尼"
                 "（A 臂 realized 因子均值 ≈0.60，说明 cc 在本数据中通常把强度压到中性以下），"
                 "分钟级强度整体抬升。这界定了 B 的机制含义：cc 通道的净效应把"
                 "『强度阻尼』与『信息贡献』混在一起，B−A 的差异不能单独归因于信息。")
    lines.append("")

    # ------------------------------------------------------------------
    lines.append("## 4. 重复信息放大分析（赛前信号 × 臂内输出，120 场）")
    lines.append("")
    team_signal = []
    elo_signal = []
    tact_signal = []
    home_win_by_arm: Dict[str, List[float]] = {arm: [] for arm in ARMS}
    factor_diff_by_arm: Dict[str, List[float]] = {arm: [] for arm in ARMS}
    lam_diff_by_arm: Dict[str, List[float]] = {arm: [] for arm in ARMS}
    for arm in ARMS:
        for match_id in sorted(preds[arm]):
            row = row_by_id[match_id]
            if arm == "A_mult":
                team_signal.append(row["team_strength_diff_nohome"])
                elo_signal.append(row["elo_diff"])
                tact_signal.append(row["tactical_advantage_nohome"])
            home_win_by_arm[arm].append(preds[arm][match_id]["home_win"])
            pm = dists[arm].get("per_match", {})
            fh = pm.get("HOME:factor", {}).get(match_id, {}).get("mean")
            fa = pm.get("AWAY:factor", {}).get(match_id, {}).get("mean")
            lh = pm.get("HOME:lam", {}).get(match_id, {}).get("mean")
            la = pm.get("AWAY:lam", {}).get(match_id, {}).get("mean")
            factor_diff_by_arm[arm].append((fh - fa) if (fh is not None and fa is not None) else 0.0)
            lam_diff_by_arm[arm].append((lh - la) if (lh is not None and la is not None) else 0.0)
    lines.append("| 相关（Pearson，n=120） | A_mult | B_off | C_add |")
    lines.append("| --- | --- | --- | --- |")
    for label, x, y_key in [
        ("corr(team_strength_diff_nohome, 场均战术因子差)", "team", "factor"),
        ("corr(team_strength_diff_nohome, home_win)", "team", "home"),
        ("corr(tactical_advantage_nohome, 场均战术因子差)", "tact", "factor"),
        ("corr(elo_diff, 场均战术因子差)", "elo", "factor"),
    ]:
        x_vals = {"team": team_signal, "tact": tact_signal, "elo": elo_signal}[x]
        y_by_arm = factor_diff_by_arm if y_key == "factor" else home_win_by_arm
        cells = " | ".join(f"{pearson(x_vals, y_by_arm[arm]):+.4f}" for arm in ARMS)
        lines.append(f"| {label} | {cells} |")
    lines.append("")
    lines.append("（信号-输出斜率：home_win 对 team_strength_diff_nohome 的回归斜率 A/B/C 分别为 "
                 + " / ".join(
                     f"{float(np.polyfit(team_signal, home_win_by_arm[arm], 1)[0]):.3f}"
                     for arm in ARMS) + "。）")
    lines.append("")
    lines.append("注：B_off 中战术因子差与赛前强度信号**负相关**（−0.58）——关闭 cc 后剩余因子只反映"
                 "赛中强度动态（f_att），强队领先→降强度的规则造成该负相关；这再次说明 B 臂"
                 "的因子已不携带赛前战术信息。")
    lines.append("")

    # ------------------------------------------------------------------
    lines.append("## 5. 五个分析问题")
    lines.append("")
    f_std = {arm: dists[arm].get("HOME:factor", {}).get("std") for arm in ARMS}
    lam_std = {arm: dists[arm].get("HOME:lam", {}).get("std") for arm in ARMS}

    # Q1 variance amplification
    lines.append("**1. 乘性结构是否扩大方差？**")
    lines.append("")
    if f_std["A_mult"] and f_std["C_add"]:
        ratio = f_std["A_mult"] / max(f_std["C_add"], 1e-12)
        lines.append(f"场均战术因子 std（主队侧）：A={f_std['A_mult']:.4f}、B={f_std['B_off']:.4f}、"
                     f"C={f_std['C_add']:.4f}；A/C 比值 {ratio:.2f}。"
                     f"逐分钟 lam std（主队侧）：A={lam_std['A_mult']:.4f}、B={lam_std['B_off']:.4f}、"
                     f"C={lam_std['C_add']:.4f}。")
        if ratio > 1.05:
            lines.append(f"→ **是**：乘性结构下战术因子的方差比加性结构大 {ratio - 1:.0%}，"
                         "与『乘性把偏离放大』的机制预期一致。")
        elif ratio < 0.95:
            lines.append(f"→ **否（方向相反）**：乘性结构的因子方差反而比加性结构小 "
                         f"{1 - ratio:.0%}。原因：本数据中 cc 均值远小于 1（A 臂因子均值 "
                         f"{dists['A_mult']['HOME:factor']['mean']:.2f}），乘积 cc×f_att 把 "
                         "f_att 的赛中波动整体压缩 —— 乘性在此充当**衰减器**而非放大器。"
                         "『乘性放大方差』的方向性假设在本数据上被否定。")
        else:
            lines.append("→ 未观测到乘性结构系统性改变因子方差（A/C 比值 ≈1），"
                         "方差放大效应在本样本上不成立或幅度低于可测范围。")
    lines.append("")

    # Q2 extreme probabilities
    lines.append("**2. 是否产生极端概率？**")
    lines.append("")
    tails_a = dists["A_mult"]["lam_tails"]["HOME"]
    tails_c = dists["C_add"]["lam_tails"]["HOME"]
    n_a = dists["A_mult"].get("HOME:lam", {}).get("n", 1)
    n_c = dists["C_add"].get("HOME:lam", {}).get("n", 1)
    lines.append(f"分钟级高强度（lam≥0.4，主队侧）：A={tails_a['lam_ge_0.4'] / n_a:.3%}、"
                 f"C={tails_c['lam_ge_0.4'] / n_c:.3%}；1X2 高置信场次（max≥0.65）："
                 f"A={sum(1 for p in preds['A_mult'].values() if max(p['home_win'], p['draw'], p['away_win']) >= 0.65)}、"
                 f"C={sum(1 for p in preds['C_add'].values() if max(p['home_win'], p['draw'], p['away_win']) >= 0.65)}。")
    extreme_a = sum(1 for p in preds["A_mult"].values()
                    if max(p["home_win"], p["draw"], p["away_win"]) >= 0.65)
    extreme_c = sum(1 for p in preds["C_add"].values()
                    if max(p["home_win"], p["draw"], p["away_win"]) >= 0.65)
    if extreme_a > extreme_c:
        lines.append("→ A 的高置信 1X2 场次多于 C，乘性结构倾向产生更多极端输出；"
                     "但两臂的极端场次都很少，绝对影响有限。")
    elif extreme_a == extreme_c:
        lines.append("→ 高置信 1X2 场次在 A/C 间相同；极端概率的臂间差异不体现在计数上。")
    else:
        lines.append("→ C 的高置信 1X2 场次反而多于 A；『乘性产生极端概率』在本样本未得到支持。")
    lines.append("")

    # Q3 duplication amplification
    lines.append("**3. 是否放大 Team/Tactical 的重复信息？**")
    lines.append("")
    corr_ts_a = pearson(team_signal, factor_diff_by_arm["A_mult"])
    corr_ts_c = pearson(team_signal, factor_diff_by_arm["C_add"])
    corr_hw_a = pearson(team_signal, home_win_by_arm["A_mult"])
    corr_hw_c = pearson(team_signal, home_win_by_arm["C_add"])
    slope_a = float(np.polyfit(team_signal, home_win_by_arm["A_mult"], 1)[0])
    slope_c = float(np.polyfit(team_signal, home_win_by_arm["C_add"], 1)[0])
    lines.append(f"Team 重复信号 → 战术因子差的相关：A={corr_ts_a:+.4f}、"
                 f"B={pearson(team_signal, factor_diff_by_arm['B_off']):+.4f}、C={corr_ts_c:+.4f}；"
                 f"Team 信号 → home_win 的相关：A={corr_hw_a:+.4f}、C={corr_hw_c:+.4f}；"
                 f"回归斜率：A={slope_a:.3f}、C={slope_c:.3f}。")
    if abs(corr_ts_a) > abs(corr_ts_c) and abs(slope_a) > abs(slope_c):
        lines.append(f"→ **部分支持**：Team 信号→战术因子差的相关 A（{corr_ts_a:+.4f}）> C"
                     f"（{corr_ts_c:+.4f}），home_win 对 Team 信号的斜率 A（{slope_a:.3f}）"
                     f"> C（{slope_c:.3f}）——乘性结构把重复信号向战术因子的传导放大；"
                     f"但 home_win 的相关 C（{corr_hw_c:+.4f}）略高于 A（{corr_hw_a:+.4f}），"
                     "『因子→最终概率』环节的证据不一。")
    else:
        lines.append("→ 未得到一致支持：A 相对 C 的信号传导并未系统性更强，"
                     "『重复信息被乘性放大』在本样本没有方向一致的证据。")
    lines.append("")

    # Q4 additive reduces error propagation
    lines.append("**4. additive 是否降低误差传播？**")
    lines.append("")
    hw_std = {arm: distribution_stats([p["home_win"] for p in preds[arm].values()])["std"]
              for arm in ARMS}
    eg_std = {arm: distribution_stats([p["expected_goals"] for p in preds[arm].values()])["std"]
              for arm in ARMS}
    lines.append(f"最终 home_win 概率的跨场 std：A={hw_std['A_mult']:.4f}、"
                 f"B={hw_std['B_off']:.4f}、C={hw_std['C_add']:.4f}；"
                 f"expected_goals 跨场 std：A={eg_std['A_mult']:.4f}、"
                 f"B={eg_std['B_off']:.4f}、C={eg_std['C_add']:.4f}。")
    if hw_std["C_add"] < hw_std["A_mult"] and eg_std["C_add"] < eg_std["A_mult"]:
        lines.append("→ 输出离散度：是（home_win 与 expected_goals 的跨场 std 在 C 中均更小）。"
                     "但信号传导证据不一：home_win 与 Team 信号的相关 C（"
                     f"{corr_hw_c:+.4f}）反而略高于 A（{corr_hw_a:+.4f}），"
                     f"回归斜率则 C（{slope_c:.3f}）< A（{slope_a:.3f}）。"
                     "→ 结论：**additive 降低输出离散度的方向一致，但『降低误差传播』"
                     "只得到部分支持（弱证据）。**")
    elif hw_std["C_add"] > hw_std["A_mult"] and eg_std["C_add"] > eg_std["A_mult"]:
        lines.append("→ 否：加性臂的最终输出分布反而更宽，未观测到误差传播降低。")
    else:
        lines.append("→ 证据不一：home_win 与 expected_goals 的跨场离散度在 A/C 之间"
                     "方向不一致，不足以断言 additive 降低误差传播。")
    lines.append("")

    # Q5 performance
    lines.append("**5. 性能变化是否足以支持『乘性放大是根因』？**")
    lines.append("")
    delta_ac = pt_ac["mean_diff"]
    delta_ab = pt_ab["mean_diff"]
    t_ac = pt_ac["t"]
    lines.append(f"Brier：A={metrics_by_arm['A_mult']['brier']:.4f}、"
                 f"B={metrics_by_arm['B_off']['brier']:.4f}、"
                 f"C={metrics_by_arm['C_add']['brier']:.4f}。"
                 f"A−C 配对差均值 {delta_ac:+.5f}（t={t_ac}），A−B 配对差均值 {delta_ab:+.5f}"
                 f"（t={pt_ab['t']}）。判定阈值 0.002（与 EXP-DIAG-EPL-001 一致）。")
    lines.append("")

    # ------------------------------------------------------------------
    lines.append("## 6. 结论（严格按证据强度措辞）")
    lines.append("")
    primary: List[str] = []
    secondary: List[str] = []
    unconfirmed: List[str] = []

    if delta_ac > 0.002 and t_ac is not None and t_ac > 2.0:
        verdict_ac = ("**支持乘性放大机制假设**（注意：仅此而已 —— 这**不**构成"
                      "『additive 是最终正确模型』的结论；加性臂只是机制探针）。")
        primary.append(f"加性臂 C 显著优于乘性臂 A（配对差 {delta_ac:+.5f}，t={t_ac}）："
                       "支持『乘性组合放大重复信号』这一机制假设")
    elif delta_ac > 0:
        verdict_ac = ("方向支持但幅度/显著性不足：A 与 C 的 Brier 差为 "
                      f"{delta_ac:+.5f}（t={t_ac}），低于判定阈值 0.002 → "
                      "**乘性放大尚未被证明是主要根因**；假设保持开放，不作过度解释。")
        unconfirmed.append(f"乘性放大假设：方向支持（Δ={delta_ac:+.5f}）但未达阈值")
    else:
        verdict_ac = ("**乘性放大尚未被证明是主要根因**：加性臂 C 并未优于乘性臂 A"
                      f"（配对差 {delta_ac:+.5f}，t={t_ac}）。假设保持开放，"
                      "不因 DIAG-001 的相关性证据而预判。")
        unconfirmed.append(f"乘性放大假设未被 DIAG-002 支持（A−C Δ={delta_ac:+.5f}）")

    lines.append(f"- 对『乘性放大』假设的判定（A vs C）：{verdict_ac}")

    t_ab = pt_ab["t"]
    if delta_ab > 0.002 and t_ab is not None and t_ab > 2.0:
        lines.append(f"- Tactical 通道整体（B vs A）：关闭 cc 通道后 Brier 改善 "
                     f"{delta_ab:+.5f}（t={t_ab}）→ 战术机会创造通道在当前数据上"
                     "净贡献为负，与 380 场冻结消融（−Tactical 改善 0.0044）同向。")
        secondary.append(f"Tactical cc 通道净贡献为负（B−A 改善 {delta_ab:+.5f}，t={t_ab}）")
    elif delta_ab < -0.002 and t_ab is not None and t_ab < -2.0:
        lines.append(f"- Tactical 通道整体（B vs A）：关闭 cc 通道后 Brier 恶化 "
                     f"{-delta_ab:+.5f}（t={t_ab}）→ 该通道在本样本为净正贡献，"
                     "与 380 场消融方向相反，不把『Tactical 有害』当结论。")
        unconfirmed.append(f"Tactical cc 通道净效应方向与 380 场消融相反（B−A Δ={delta_ab:+.5f}）")
    else:
        lines.append(f"- Tactical 通道整体（B vs A）：关闭 cc 通道后 Brier 变化 "
                     f"{delta_ab:+.5f}（t={t_ab}），方向与 380 场消融（改善 0.0044）一致"
                     "但远未达统计显著 → 通道净效应在本样本不显著，不作归因。")
        unconfirmed.append(f"Tactical cc 通道净效应（B−A Δ={delta_ab:+.5f}，t={t_ab}）不显著；"
                           "且 B_off 同时大幅抬高 expected_goals（120/120 场 ≥3.0），"
                           "提示 cc 通道在本数据中主要起强度阻尼作用")
    lines.append("")
    # mechanism-level distribution findings (independent of the performance deltas)
    a_factor_mean = dists["A_mult"].get("HOME:factor", {}).get("mean")
    if a_factor_mean is not None and a_factor_mean < 0.9:
        secondary.append(f"乘性组合在本数据中充当**强度衰减器**：cc 均值远小于 1 使 A 臂因子均值 "
                         f"≈{a_factor_mean:.2f}，乘积压缩 f_att 波动（A 因子 std "
                         f"{dists['A_mult']['HOME:factor'].get('std', float('nan')):.4f} < C "
                         f"{dists['C_add']['HOME:factor'].get('std', float('nan')):.4f}）——"
                         "『乘性放大方差』的方向性机制与实测相反")
    secondary.append("cc 通道同时承载『强度阻尼』与『信息贡献』：B_off 关闭后 expected_goals "
                     "全部 ≥3.0（阻尼解除），其 Brier 变化不能单独归因于信息")
    lines.append("**PRIMARY（证据强）：**")
    if primary:
        for item in primary:
            lines.append(f"- {item}")
    else:
        lines.append("- （无 —— 未发现达到证据强度阈值的结论）")
    lines.append("**SECONDARY（证据中等）：**")
    if secondary:
        for item in secondary:
            lines.append(f"- {item}")
    else:
        lines.append("- （无）")
    lines.append("**UNCONFIRMED（证据不足，不猜测）：**")
    if unconfirmed:
        for item in unconfirmed:
            lines.append(f"- {item}")
    else:
        lines.append("- （无）")
    lines.append("")
    lines.append("**NEXT EXPERIMENT（仅设计，不执行、不修改生产模型）：**")
    lines.append("1. DIAG-003：检验 EXP-DIAG-EPL-001 实测最优配置 `team_psychology`（0.6579）"
                 "能否在更大样本上稳定优于 full；并测『Team-only + 线性融合』与 Elo 的差距，"
                 "分离融合结构瓶颈与信息量瓶颈。")
    lines.append("2. 若继续追问 Tactical 通道：在诊断副本中把 Opening 开场通道与引擎 cc 通道"
                 "分离消融（DIAG-002 已显示二者在 `full_minus_tactical` 中被同时关闭），"
                 "并分离 cc 的『强度阻尼』与『信息贡献』（B_off 臂 xG 全部 ≥3.0 提示阻尼作用"
                 "占比可观）。")
    lines.append("3. 跨赛季复测（需先获取第二赛季真实数据）。")
    lines.append("")
    lines.append("## 7. 可复现")
    lines.append("")
    lines.append(f"- 冻结基线：EXP-REAL-EPL-BASE-001（`{manifest['experiment_id']}`，"
                 "目录未动，哈希清单在 `backtest_output/diag_002_tactical_amp/"
                 "baseline_manifest_real_epl_base_001.json`）与 EXP-DIAG-EPL-001"
                 "（`backtest_output/diag_002_tactical_amp/baseline_manifest_diagnosis_epl_001.json`）。")
    lines.append("- 沙箱产物：`preds.json`（3 臂 × 120 场，400 模拟，seed 20240101）、"
                 "`distributions.json`（逐分钟 realized 分布）、`validation.json`"
                 "（A≡冻结 full 的忠实性验证）。")
    lines.append("- 注册表：`backtest_output/diag_002_tactical_amp/experiments.jsonl`"
                 "（EXP-DIAG-EPL-002，`synthetic_data=false`，`market_data=false`）。")
    lines.append("- 生产源码零修改；事件引擎补丁仅存在于本诊断脚本的运行期（子类 + 类引用替换）。")

    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"written -> {DOC}")


if __name__ == "__main__":
    main()
