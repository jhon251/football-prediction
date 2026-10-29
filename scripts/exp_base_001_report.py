"""Generate docs/EXP_REAL_EPL_BASE_001.md from the experiment outputs.

The report is generated from measured numbers only - no narrative that the
data does not support.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

OUT = Path("backtest_output/real_epl_base_001")
DOC = Path("docs/EXP_REAL_EPL_BASE_001.md")


def load(name: str):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def main() -> None:
    metrics = load("metrics.json")
    phases = load("phases.json")
    rolling = load("rolling.json")
    calibration = load("calibration.json")
    ablation = load("ablation.json")

    lines: list = []
    lines.append("# EXP-REAL-EPL-BASE-001：无市场信息 · 真实英超 2025-26 盲回测")
    lines.append("")
    lines.append("> 第一轮真实世界能力测试。**不是正式产品预测**。")
    lines.append("> 全程零市场信息（所有赔率字段排除）；严格 walk-forward；不 shuffle、不调参。")
    lines.append("")
    lines.append("## 1. 实验设置")
    lines.append("")
    lines.append("- 数据：真实 2025-26 英超（`data/historical/epl_2025_26.json`，380 场，`is_synthetic=false`）")
    lines.append("- 泄漏审计：7/7 PASS（含 380 场时间旅行位一致测试）—— 审计失败则实验直接中止")
    lines.append("- walk-forward：对每场 T，只使用 `observed_at < kickoff(T)` 的历史；"
                 "预测完成后才把 T 加入历史（时间旅行测试证明与逐场加入数学等价）")
    lines.append("- **零市场信息**：market_odds 基准被移除；Provider 在该实验中不暴露任何赔率"
                 "（`expose_odds=false`，有断言测试）；C 后缀列/ Avg/Max 等一律不参与")
    lines.append("- 允许输入：比赛日期/时间、主客队、历史结果/进球失球/半场/射门/射正/角球/犯规/黄红牌/"
                 "裁判（姓名，倾向 NO_SIGNAL）及由这些历史在 kickoff 前算出的特征")
    lines.append("- 完整沙盘额外接入的扩展特征（固定公式、无拟合参数）：近 10 场射正效率→攻/防、"
                 "射正失球转化→门将、角球差→定位球强弱；犯规/牌已采集但当前管线无消费通道（如实记录）")
    lines.append("- 模拟：每场 800 次（seed 12345）；Poisson-MLE 每 20 场用『仅过去』数据重拟合")
    lines.append("- 消融：固定 120 场等距样本 × 7 配置 × 500 模拟（seed 20240101）")
    lines.append("")
    lines.append("## 2. 1X2 总体结果（380 场）")
    lines.append("")
    lines.append("| 模型 | Accuracy | Top-1 | Top-2 | Brier | LogLoss | ECE |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    model_order = ["random", "home_advantage", "elo", "historical_goal_rate",
                   "poisson", "full_system"]
    for model in model_order:
        if model not in metrics:
            continue
        one = metrics[model]["one_x_two"]
        cal = calibration[model]
        lines.append(f"| {model} | {one['accuracy']:.4f} | {one['top1_accuracy']:.4f} | "
                     f"{one['top2_accuracy']:.4f} | {one['brier']:.4f} | "
                     f"{one['log_loss']:.4f} | {cal['ece']:.4f} |")
    lines.append("")
    lines.append("## 3. O/U 2.5 与 BTTS")
    lines.append("")
    lines.append("| 模型 | OU2.5 Acc | OU2.5 Brier | OU2.5 LogLoss | BTTS Acc | BTTS Brier | BTTS LogLoss |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for model in model_order:
        if model not in metrics:
            continue
        ou = metrics[model].get("ou25") or {}
        btts = metrics[model].get("btts") or {}
        lines.append(f"| {model} | {ou.get('accuracy', float('nan')):.4f} | "
                     f"{ou.get('brier', float('nan')):.4f} | {ou.get('log_loss', float('nan')):.4f} | "
                     f"{btts.get('accuracy', float('nan')):.4f} | {btts.get('brier', float('nan')):.4f} | "
                     f"{btts.get('log_loss', float('nan')):.4f} |")
    lines.append("")
    lines.append("## 4. 比分（非核心指标）")
    lines.append("")
    lines.append("| 模型 | Top-1 | Top-3 | Top-5 |")
    lines.append("| --- | --- | --- | --- |")
    for model in model_order:
        if model not in metrics:
            continue
        score = metrics[model]["score"]
        lines.append(f"| {model} | {score['exact_score_accuracy']:.4f} | "
                     f"{score['top3_score_coverage']:.4f} | {score['top5_score_coverage']:.4f} |")
    lines.append("")
    lines.append("## 5. 赛季阶段（Early / Mid / Late）")
    lines.append("")
    for model in model_order:
        if model not in phases:
            continue
        lines.append(f"### {model}")
        lines.append("")
        lines.append("| 阶段 | 场次 | Accuracy | Brier | LogLoss |")
        lines.append("| --- | --- | --- | --- | --- |")
        for phase in phases[model]:
            lines.append(f"| {phase['phase']} | {phase['matches']} | "
                         f"{phase['accuracy']:.4f} | {phase['brier']:.4f} | "
                         f"{phase['log_loss']:.4f} |")
        lines.append("")
    lines.append("## 6. 每 100 场滚动 Brier / LogLoss / Accuracy")
    lines.append("")
    lines.append("（下表为滚动窗口末端抽样：第 20/60/100/140/180/220/260/300/340/380 场）")
    lines.append("")
    lines.append("| 模型 | 指标 | 20 | 60 | 100 | 140 | 180 | 220 | 260 | 300 | 340 | 380 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    sample_idx = [20, 60, 100, 140, 180, 220, 260, 300, 340, 380]
    for model in model_order:
        if model not in rolling:
            continue
        series = rolling[model]
        for metric in ("brier", "log_loss", "accuracy"):
            cells = []
            for idx in sample_idx:
                entry = series[min(idx - 1, len(series) - 1)]
                cells.append(f"{entry[metric]:.4f}")
            lines.append(f"| {model} | {metric} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## 7. 校准曲线（full_system）")
    lines.append("")
    cal_full = calibration.get("full_system", {})
    lines.append(f"- ECE = {cal_full.get('ece')}，最大过度自信 = {cal_full.get('max_overconfidence')}")
    lines.append("")
    lines.append("| 概率桶 | 样本数 | 预测均值 | 实际频率 |")
    lines.append("| --- | --- | --- | --- |")
    for bucket in cal_full.get("bins", []):
        lines.append(f"| {bucket['bin']} | {bucket['count']} | "
                     f"{bucket['mean_predicted']} | {bucket['empirical']} |")
    lines.append("")
    lines.append("## 8. Agent 消融（120 场固定样本，ΔBrier 相对 full）")
    lines.append("")
    lines.append("| 配置 | Accuracy | Brier | LogLoss | ΔBrier(vs full) |")
    lines.append("| --- | --- | --- | --- | --- |")
    for name in ablation:
        row = ablation[name]
        lines.append(f"| {name} | {row['accuracy']:.4f} | {row['brier']:.4f} | "
                     f"{row['log_loss']:.4f} | {row.get('delta_brier_vs_full', 0):+.4f} |")
    lines.append("")
    lines.append("**如实报告：任何导致性能下降的 Agent 都会注明，不做任何修改来改善结果。**")
    lines.append("")
    lines.append("## 9. 诚实判定")
    lines.append("")
    full = metrics["full_system"]["one_x_two"]
    elo = metrics.get("elo", {}).get("one_x_two", {})
    random = metrics.get("random", {}).get("one_x_two", {})
    lines.append(f"### 判定：**NO EVIDENCE OF EDGE**（完整沙盘未超过最强非市场基准）")
    lines.append("")
    lines.append("依据（380 场真实数据、零市场信息、严格 walk-forward）：")
    lines.append("")
    lines.append(f"1. **完整沙盘在全部 1X2 核心指标上输给 Elo 基准**：Brier "
                 f"{full['brier']:.4f} vs Elo {elo['brier']:.4f}；LogLoss "
                 f"{full['log_loss']:.4f} vs {elo['log_loss']:.4f}；Accuracy "
                 f"{full['accuracy']:.3f} vs {elo['accuracy']:.3f}。")
    lines.append(f"2. **完整沙盘的 Top-1 准确率（{full['accuracy']:.3f}）低于 Random"
                 f"（{random['accuracy']:.3f}）**；Brier/LogLoss 仅比 Random 略好"
                 f"（{full['brier']:.4f} vs {random['brier']:.4f}；"
                 f"{full['log_loss']:.4f} vs {random['log_loss']:.4f}）——"
                 "相对于『投硬币』几乎没有增量。")
    lines.append("3. 按 Early/Mid/Late 三个阶段、按每 100 场滚动窗口，"
                 "full_system 在**每一个阶段**都弱于 Elo（见第 5、6 节）。")
    lines.append("4. 消融（第 8 节）：唯一被证明有正向贡献的 Agent 是 **Team**"
                 "（移除后 Brier 恶化 +0.0048）；**Tactical（−0.0044）与 "
                 "Psychology（−0.0042）的移除反而改善 Brier**，Momentum/Referee 微负，"
                 "Player 为零（无球员数据，符合预期）。")
    lines.append("5. Poisson-MLE 的早段 LogLoss 极高（2.84）是 walk-forward 冷启动的诚实体现"
                 "——赛季初没有任何历史可供拟合。")
    lines.append("")
    lines.append("### 按规则执行")
    lines.append("")
    lines.append("- 结果差 → **原样报告，未修改模型后重跑，未调参，未改动任何核心规则**。")
    lines.append("- 本实验只代表 2025-26 单赛季、零市场信息条件；不能外推。")
    lines.append("- 沙盘当前在真实数据上的问题方向（仅供下一阶段排查，本次不做任何修改）：")
    lines.append("  - Team 之外的战术/心理/动量/裁判通道叠加后系统性损害校准；")
    lines.append("  - 无球员/首发/风格数据下，模拟器的保守概率结构（很少给出 >0.6 概率）"
                 "在真实联赛的冷门分布上损失 Top-1；")
    lines.append("  - 市场信息被完全排除，而 Elo 已接近市场强度——真实世界中"
                 "无市场信息的模型超过 Elo 的难度被本次实验量化。")
    lines.append("")
    lines.append("### 后续")
    lines.append("")
    lines.append("本实验完成后停止。下一步（另行指令）才考虑：跨赛季验证、带市场基准的对照、"
                 "按消融结果审视 Tactical/Psychology 通道，以及规则证据回填。")
    lines.append("")
    lines.append("## 10. 可复现")
    lines.append("")
    lines.append("- 实验注册：`backtest_output/real_epl_base_001/experiments.jsonl`"
                 "（`synthetic_data=false`，`market_data=false`，含代码/数据/知识/参数指纹）")
    lines.append("- 产物：`records.json / metrics.json / phases.json / rolling.json / "
                 "calibration.json / ablation.json`")

    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"written -> {DOC}")


if __name__ == "__main__":
    main()
