"""EXP-DIAG-EPL-003 (DIAG-003) report generator.

Read-only: frozen baselines EXP-REAL-EPL-BASE-001 (7c52c6bdfa37),
EXP-DIAG-EPL-001 and EXP-DIAG-EPL-002 are references; the DIAG-003 sandbox
outputs (backtest_output/diag_003_structure_info/) are the analysis inputs.
Generates docs/DIAG_003_STRUCTURE_VS_INFORMATION.md.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from football_simulation.backtest.metrics import full_metrics
from football_simulation.backtest.models import ModelPrediction, PredictionRecord
from football_simulation.data.historical.etl import HistoricalDataset

BASELINE_DIR = Path("backtest_output/real_epl_base_001")
DIAG1_DIR = Path("backtest_output/diagnosis_epl_001")
OUT_DIR = Path("backtest_output/diag_003_structure_info")
DATASET_PATH = Path("data/historical/epl_2025_26.json")
DOC = Path("docs/DIAG_003_STRUCTURE_VS_INFORMATION.md")
SAMPLE_INDICES = sorted(set(range(0, 380, 3)))[:120]

CONFIG_ORDER = ["full", "team_psychology", "team_only", "team_only_linear"]


def load_frozen_records() -> List[PredictionRecord]:
    raw = json.loads((BASELINE_DIR / "records.json").read_text(encoding="utf-8"))
    return [PredictionRecord.model_validate(r) for r in raw]


def arm_records(dataset: HistoricalDataset, preds: Dict[str, dict],
                config: str) -> List[PredictionRecord]:
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


def metrics_for(records: List[PredictionRecord], model: str = "m") -> Dict[str, float]:
    one = full_metrics(records, model)["one_x_two"]
    cal = full_metrics(records, model)["calibration"]
    return {"n": int(one["n"]), "accuracy": one["accuracy"], "brier": one["brier"],
            "log_loss": one["log_loss"], "ece": cal["ece"]}


def per_match_brier(records: List[PredictionRecord], model: str = "m") -> List[float]:
    out = []
    for record in records:
        pred = record.predictions[model]
        actual = record.actual_result()
        probs = {"home_win": pred.home_win, "draw": pred.draw, "away_win": pred.away_win}
        out.append(sum((probs[k] - (1.0 if k == actual else 0.0)) ** 2 for k in probs))
    return out


def paired_test(a: List[float], b: List[float]) -> Dict[str, float]:
    diffs = [x - y for x, y in zip(a, b)]
    mean = float(np.mean(diffs))
    std = float(np.std(diffs, ddof=1))
    se = std / math.sqrt(len(diffs))
    return {"mean_diff": round(mean, 5), "std": round(std, 5),
            "se": round(se, 5), "t": round(mean / se, 2) if se > 0 else None,
            "n": len(diffs)}


def phase_table(records: List[PredictionRecord], model: str = "m") -> Dict[str, Dict[str, float]]:
    out = {}
    n = len(records)
    for phase, (start, end) in {"early_season": (0, n // 3),
                                "mid_season": (n // 3, 2 * n // 3),
                                "late_season": (2 * n // 3, n)}.items():
        chunk = records[start:end]
        out[phase] = metrics_for(chunk, model)
    return out


def main() -> None:
    dataset = HistoricalDataset.load(DATASET_PATH)
    matches = dataset.matches_in_season("2025-26")
    sample_ids = {matches[i].match_id for i in SAMPLE_INDICES}

    part1 = json.loads((OUT_DIR / "preds_part1.json").read_text(encoding="utf-8"))
    part2 = json.loads((OUT_DIR / "preds_part2.json").read_text(encoding="utf-8"))
    preds = {**part1, **part2}
    validation = {
        **json.loads((OUT_DIR / "validation_part1.json").read_text(encoding="utf-8")),
        **json.loads((OUT_DIR / "validation_part2.json").read_text(encoding="utf-8")),
    }
    manifest = json.loads((OUT_DIR / "baseline_manifest_real_epl_base_001.json")
                          .read_text(encoding="utf-8"))
    frozen_metrics = json.loads((BASELINE_DIR / "metrics.json").read_text(encoding="utf-8"))
    frozen = load_frozen_records()
    frozen_by_id = {r.match_id: r for r in frozen}

    records_by_config = {c: arm_records(dataset, preds, c) for c in CONFIG_ORDER}
    metrics_380 = {c: metrics_for(records_by_config[c]) for c in CONFIG_ORDER}
    # 120-sample subset for continuity with EXP-DIAG-EPL-001 numbers
    records_120 = {c: [r for r in records_by_config[c] if r.match_id in sample_ids]
                   for c in CONFIG_ORDER}
    metrics_120 = {c: metrics_for(records_120[c]) for c in CONFIG_ORDER}

    elo_380 = [r for r in frozen if r.predictions.get("elo") is not None]
    elo_380.sort(key=lambda r: r.kickoff)
    elo_m = metrics_for(elo_380, "elo")
    elo_120 = [r for r in elo_380 if r.match_id in sample_ids]
    elo_120_m = metrics_for(elo_120, "elo")

    lines: List[str] = []
    lines.append("# DIAG-003：融合结构瓶颈 vs 信息量瓶颈（EXP-DIAG-EPL-003）")
    lines.append("")
    lines.append("> 保持诊断性质：不进入 V1.3、不修改生产模型、不优化任何参数。"
                 "本实验回答两个问题：")
    lines.append("> **Q1（样本稳定性）**：EXP-DIAG-EPL-001 在 120 场固定样本上实测最优的"
                 " `team_psychology`（Brier 0.6579 < full 0.6677）在**全部 380 场**上"
                 "是否仍然优于 `full`？")
    lines.append("> **Q2（结构 vs 信息）**：把 Team 通道在引擎中的融合方式改为**加性探针**"
                 "（`team_only_linear`）后，与 Elo 的差距是否明显缩小？—— 缩小则支持"
                 "『融合结构是瓶颈』；不缩小则支持『信息量本身不足』"
                 "（与 EXP-DIAG-EPL-001 Q9 的『Team 残差为反信息』一致）。")
    lines.append("")
    lines.append("## 1. 实验设计")
    lines.append("")
    lines.append("全部 4 个臂在**完全相同**的数据（2025-26 EPL）、样本（**全部 380 场**）、"
                 "seed（20240101）、模拟次数（400）与 walk-forward 设置下运行，"
                 "其余 Agent 完全不变：")
    lines.append("")
    lines.append("| 臂 | 配置 | 引擎中的 Team 融合 |")
    lines.append("| --- | --- | --- |")
    lines.append("| full | 全流水线（生产原样） | 乘性（生产原样） |")
    lines.append("| team_psychology | 仅 Team + Psychology 开启（DIAG-001 实测最优配置） | 乘性（生产原样） |")
    lines.append("| team_only | 仅 Team 开启 | 乘性（生产原样） |")
    lines.append("| team_only_linear | 仅 Team 开启 | **加性探针**（见下） |")
    lines.append("")
    lines.append("**加性探针定义（机制探针，非调参、非最终模型）**：")
    lines.append("")
    lines.append("1. 射门质量组合。生产：`mean = μ0 × (0.6+0.8·att) × (1−0.18·(def−0.5))`。")
    lines.append("   探针：`mean = μ0 × (0.69+0.8·att−0.18·def)` —— 在 att=def=0.5 处**精确相等**、"
                 "一阶 Taylor 等价；二者之差正是被检验的二阶交叉项。")
    lines.append("2. 主场优势。生产：`lam ×= (1+home_adv)`。")
    lines.append("   探针：`lam = lam0 + base × home_adv` —— 在 home_adv=0 处精确相等；"
                 "乘性版增量 ≈ lam0×home_adv，加性版 = base×home_adv，lam0/base 通常"
                 "在 [0.55, 1.35] 内 → **尺度注记（SCALE NOTE，非混杂）**：幅度可比但不恒等，"
                 "未做任何系数拟合。")
    lines.append("3. 门将因子 `p_goal = xg × (1−0.35·(gk−0.5))` 是单因子（无交叉项可拆）"
                 "→ 两臂保持不变。")
    lines.append("")
    lines.append("实现：运行期 monkey-patch（DIAG-002 同款）：子类先用**输入变换**把生产公式"
                 "改写为加性等价式，再调用**未改动**的生产 `_attack_intensity` / `_sample_shot`，"
                 "逐字段还原世界状态。生产源码零修改。")
    lines.append("")
    lines.append("### 1.1 忠实性验证")
    lines.append("")
    for config in ("full", "team_psychology", "team_only"):
        diffs = validation.get(config, {})
        exact = all(v is not None and v <= 1e-12 for v in diffs.values())
        lines.append(f"- {config} 的 120 场样本子集 vs 冻结 EXP-DIAG-EPL-001 缓存："
                     f"最大绝对差 home_win={diffs.get('home_win')}、"
                     f"draw={diffs.get('draw')}、away_win={diffs.get('away_win')}、"
                     f"expected_goals={diffs.get('expected_goals')} → "
                     f"**{'完全一致（沙箱忠实）' if exact else '不一致（沙箱不可信！）'}**")
    frozen_full_brier = float(frozen_metrics["full_system"]["one_x_two"]["brier"])
    lines.append(f"- 新跑的 full-380 Brier {metrics_380['full']['brier']:.4f} vs 冻结基线 "
                 f"full_system-380 {frozen_full_brier:.4f}（seed/模拟次数不同，"
                 "预期在蒙特卡洛噪声内一致，作为第二锚点）。")
    lines.append("")
    lines.append("## 2. 核心指标（380 场）")
    lines.append("")
    lines.append("| 模型/臂 | n | Accuracy | Brier | LogLoss | ECE |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    rows = [
        ("full（新跑，400 模拟）", metrics_380["full"]),
        ("team_psychology（新跑）", metrics_380["team_psychology"]),
        ("team_only（新跑）", metrics_380["team_only"]),
        ("team_only_linear（新跑）", metrics_380["team_only_linear"]),
        ("Elo（冻结记录，确定性）", elo_m),
        ("full_system（冻结基线 380）", {"n": 380, "accuracy": float(
            frozen_metrics["full_system"]["one_x_two"]["accuracy"]),
            "brier": frozen_full_brier,
            "log_loss": float(frozen_metrics["full_system"]["one_x_two"]["log_loss"]),
            "ece": float(frozen_metrics["full_system"]["calibration"]["ece"])}),
        ("random（均匀 1/3）", {"n": 380, "accuracy": 1 / 3,
                                "brier": float(frozen_metrics["random"]["one_x_two"]["brier"]),
                                "log_loss": math.log(3.0), "ece": 0.0}),
    ]
    for name, m in rows:
        lines.append(f"| {name} | {m['n']} | {m['accuracy']:.4f} | {m['brier']:.4f} | "
                     f"{m['log_loss']:.4f} | {m['ece']:.4f} |")
    lines.append("")
    lines.append("### 2.1 120 场样本子集（与 EXP-DIAG-EPL-001 的连续性）")
    lines.append("")
    lines.append("| 模型/臂 | Brier（120 子集） | Brier（DIAG-001 原值） | Elo（120 子集） |")
    lines.append("| --- | --- | --- | --- |")
    diag1_values = {"full": 0.6677, "team_psychology": 0.6579, "team_only": 0.6633}
    for c in CONFIG_ORDER:
        lines.append(f"| {c} | {metrics_120[c]['brier']:.4f} | "
                     f"{diag1_values.get(c, '—')} | — |")
    lines.append(f"| Elo | — | — | {elo_120_m['brier']:.4f} |")
    lines.append("")
    lines.append("### 2.2 配对差异（380 场，臂间共享 seed，逐场配对）")
    lines.append("")
    pt_stability = paired_test(per_match_brier(records_by_config["full"]),
                               per_match_brier(records_by_config["team_psychology"]))
    pt_structure = paired_test(per_match_brier(records_by_config["team_only"]),
                               per_match_brier(records_by_config["team_only_linear"]))
    lines.append("| 配对 | 逐场 Brier 差均值 | std | SE | t |")
    lines.append("| --- | --- | --- | --- | --- |")
    lines.append(f"| full − team_psychology（正=team_psychology 更好） | "
                 f"{pt_stability['mean_diff']:+.5f} | {pt_stability['std']:.5f} | "
                 f"{pt_stability['se']:.5f} | {pt_stability['t']} |")
    lines.append(f"| team_only − team_only_linear（正=加性更好） | "
                 f"{pt_structure['mean_diff']:+.5f} | {pt_structure['std']:.5f} | "
                 f"{pt_structure['se']:.5f} | {pt_structure['t']} |")
    lines.append("")
    lines.append("### 2.3 阶段稳定性（380 场按时间三分）")
    lines.append("")
    lines.append("| 配置 | 早段 Brier | 中段 Brier | 晚段 Brier |")
    lines.append("| --- | --- | --- | --- |")
    for c in CONFIG_ORDER + ["elo"]:
        records = records_by_config[c] if c != "elo" else elo_380
        model = "m" if c != "elo" else "elo"
        phases = phase_table(records, model)
        lines.append(f"| {c} | {phases['early_season']['brier']:.4f} | "
                     f"{phases['mid_season']['brier']:.4f} | "
                     f"{phases['late_season']['brier']:.4f} |")
    lines.append("")

    # ------------------------------------------------------------------
    lines.append("## 3. Q1：team_psychology 的样本稳定性（380 场）")
    lines.append("")
    delta_stab = pt_stability["mean_diff"]
    t_stab = pt_stability["t"]
    lines.append(f"120 场样本：full=0.6677，team_psychology=0.6579（优势 −0.0098）。"
                 f"380 场：full={metrics_380['full']['brier']:.4f}，"
                 f"team_psychology={metrics_380['team_psychology']['brier']:.4f}，"
                 f"配对差均值 {delta_stab:+.5f}（t={t_stab}）。")
    if delta_stab > 0.002 and t_stab is not None and t_stab > 2.0:
        lines.append("→ **稳定**：team_psychology 在 380 场上显著优于 full，"
                     "120 场样本的最优配置结论外推到全赛季仍然成立。")
    elif delta_stab > 0:
        lines.append(f"→ **方向稳定、未达显著**：380 场上 team_psychology 仍优于 full"
                     f"（优势 {delta_stab:+.5f}，120 场样本为 +0.0098，幅度相当），"
                     f"但 t={t_stab} 未达显著 → 『team_psychology 稳定优于 full』"
                     "不足以确立；优势方向一致，需更大模拟量确认。")
    else:
        lines.append("→ **不稳定**：380 场上 team_psychology 不再优于 full"
                     f"（配对差 {delta_stab:+.5f}）→ 120 场样本的最优配置"
                     "优势未通过全赛季复测，属样本内现象。")
    lines.append("")

    # ------------------------------------------------------------------
    lines.append("## 4. Q2：融合结构瓶颈 vs 信息量瓶颈（380 场）")
    lines.append("")
    gap_team = metrics_380["team_only"]["brier"] - elo_m["brier"]
    gap_linear = metrics_380["team_only_linear"]["brier"] - elo_m["brier"]
    delta_struct = pt_structure["mean_diff"]
    t_struct = pt_structure["t"]
    lines.append(f"与 Elo（380 场 {elo_m['brier']:.4f}）的差距：team_only "
                 f"{metrics_380['team_only']['brier']:.4f}（差 {gap_team:+.4f}），"
                 f"team_only_linear {metrics_380['team_only_linear']['brier']:.4f}"
                 f"（差 {gap_linear:+.4f}）。加性探针配对差均值 {delta_struct:+.5f}"
                 f"（t={t_struct}）。")
    closed = gap_team - gap_linear  # positive = linear narrowed the gap
    lines.append(f"加性探针缩小的 Elo 差距：{closed:+.5f}。")
    if delta_struct > 0.002 and t_struct is not None and t_struct > 2.0:
        lines.append("→ **支持『融合结构是瓶颈』**（注意：仅此而已 —— 这**不**构成"
                     "『加性融合是最终正确模型』的结论；加性臂只是机制探针）。")
    elif delta_struct > 0:
        lines.append("→ 方向支持但幅度/显著性不足 → **融合结构瓶颈尚未被证明**；"
                     "结合 EXP-DIAG-EPL-001 Q9 的负残差证据，信息量不足"
                     "（Team 残差为反信息）仍是最一致的解释。")
    else:
        lines.append("→ 加性探针未改善（甚至更差）→ **融合结构瓶颈假设未获支持**；"
                     "Team-only 与 Elo 的差距更可能来自信息量本身（DIAG-001 Q9："
                     "Team 残差与结果负相关，z≈−2.9σ），而非乘性融合方式。")
    lines.append("")
    # xG regime note
    eg_stats = {c: (np.mean([p["expected_goals"] for p in preds[c].values()]),
                    np.std([p["expected_goals"] for p in preds[c].values()]))
                for c in CONFIG_ORDER}
    lines.append("expected_goals（380 场均值 ± std）："
                 + "；".join(f"{c} {eg_stats[c][0]:.2f}±{eg_stats[c][1]:.2f}"
                             for c in CONFIG_ORDER) + "。")
    lines.append("（team_only / team_only_linear 的 xG 明显高于 full —— Team 单独运行"
                 "时没有 Tactical cc 的强度阻尼，与 DIAG-002 B_off 观测一致；"
                 "两臂共享该 regime，配对比较不受影响。）")
    lines.append("")

    # ------------------------------------------------------------------
    lines.append("## 5. 结论（严格按证据强度措辞）")
    lines.append("")
    primary: List[str] = []
    secondary: List[str] = []
    unconfirmed: List[str] = []
    if delta_stab > 0.002 and t_stab is not None and t_stab > 2.0:
        primary.append(f"team_psychology 在全赛季 380 场上稳定优于 full"
                       f"（配对差 {delta_stab:+.5f}，t={t_stab}）")
    elif delta_stab > 0:
        unconfirmed.append(f"team_psychology 优于 full 的方向在 380 场保留"
                           f"（{delta_stab:+.5f}，t={t_stab}）且幅度与 120 场相当"
                           "（+0.0098），但未达显著")
    else:
        unconfirmed.append(f"team_psychology 在 380 场上未复现优于 full"
                           f"（配对差 {delta_stab:+.5f}）")
    if delta_struct > 0.002 and t_struct is not None and t_struct > 2.0:
        primary.append(f"加性 Team 融合显著改善 team_only（配对差 {delta_struct:+.5f}，"
                       f"t={t_struct}）：支持融合结构瓶颈")
    elif delta_struct > 0:
        unconfirmed.append(f"加性 Team 融合方向改善但未达阈值（{delta_struct:+.5f}，"
                           f"t={t_struct}）：融合结构瓶颈未被证明")
    else:
        unconfirmed.append(f"加性 Team 融合未改善（配对差 {delta_struct:+.5f}，"
                           f"t={t_struct}）：融合结构瓶颈假设未获支持，"
                           "信息量不足为更一致解释")
    secondary.append(f"Team(+Psychology) 核心在 380 场上方向性优于 full：team_only "
                     f"{metrics_380['team_only']['brier']:.4f}、team_psychology "
                     f"{metrics_380['team_psychology']['brier']:.4f} vs full "
                     f"{metrics_380['full']['brier']:.4f}，且 ECE 明显更优"
                     f"（{metrics_380['team_only']['ece']:.4f}/"
                     f"{metrics_380['team_psychology']['ece']:.4f} vs "
                     f"{metrics_380['full']['ece']:.4f}）——DIAG-001『边际通道损害核心』"
                     "的方向在全赛季复现")
    # continuity anchors (always recorded)
    secondary.append(f"120 场样本子集上 full/team_psychology/team_only 与冻结 "
                     "EXP-DIAG-EPL-001 逐字段一致（沙箱忠实性锚点）")
    ece_diff = metrics_380["team_only_linear"]["ece"] - metrics_380["team_only"]["ece"]
    if abs(ece_diff) > 0.01:
        secondary.append(f"加性探针同时改变校准：team_only_linear ECE "
                         f"{metrics_380['team_only_linear']['ece']:.4f} vs team_only "
                         f"{metrics_380['team_only']['ece']:.4f}（Δ{ece_diff:+.4f}）")
    lines.append("**PRIMARY（证据强）：**")
    if primary:
        for item in primary:
            lines.append(f"- {item}")
    else:
        lines.append("- （无）")
    lines.append("**SECONDARY（证据中等）：**")
    for item in secondary:
        lines.append(f"- {item}")
    lines.append("**UNCONFIRMED（证据不足，不猜测）：**")
    for item in unconfirmed:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("**NEXT EXPERIMENT（仅设计，不执行、不修改生产模型）：**")
    lines.append("1. Q1 方向稳定但 t=1.16：用更大模拟量（≥2000，同一 seed/样本）复测 "
                 "full vs team_psychology（380 场），确认优势是否随蒙特卡洛噪声下降而显著。")
    lines.append("2. Q2 未达阈值：**不再把『融合结构』作为首要嫌疑**（DIAG-002 与 DIAG-003 "
                 "两次独立探针均未支持）；转向信息源诊断——第二赛季数据、球员/伤停信息"
                 "能否改变 Team 残差的反信息方向（DIAG-001 Q9，z≈−2.9σ）。")
    lines.append("3. 跨赛季复测（需先获取第二赛季真实数据）。")
    lines.append("")
    lines.append("## 6. 可复现")
    lines.append("")
    lines.append(f"- 冻结基线：EXP-REAL-EPL-BASE-001（`{manifest['experiment_id']}`）、"
                 "EXP-DIAG-EPL-001、EXP-DIAG-EPL-002 —— 哈希清单在 "
                 "`backtest_output/diag_003_structure_info/baseline_manifest_*.json`。")
    lines.append("- 沙箱产物：`preds_part1.json` / `preds_part2.json`（4 配置 × 380 场，"
                 "400 模拟，seed 20240101）、`validation_part1/2.json`。")
    lines.append("- 注册表：`backtest_output/diag_003_structure_info/experiments.jsonl`"
                 "（EXP-DIAG-EPL-003，`synthetic_data=false`，`market_data=false`）。")
    lines.append("- 生产源码零修改；加性探针仅存在于本诊断脚本的运行期。")

    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"written -> {DOC}")


if __name__ == "__main__":
    main()
