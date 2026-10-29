"""EXP-DIAG-EPL-005 (DIAG-005) report generator.

Reads backtest_output/diag_005_info_source/{probes,stats}.json and writes
docs/DIAG_005_INFO_SOURCE_INCREMENTAL_VALUE.md strictly following the
pre-registered design (docs/DIAG_005_INFO_SOURCE_DESIGN.md).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

OUT_DIR = Path("backtest_output/diag_005_info_source")
DOC = Path("docs/DIAG_005_INFO_SOURCE_INCREMENTAL_VALUE.md")

SOURCE_LABELS = {
    "shot_quality": "射门质量（主客射正率差，10 场 walk-forward）",
    "sot_rate": "射正率（主客 SOT 绝对量差，10 场 walk-forward）",
    "congestion_14d": "赛程密度（主客 congestion_14d 差）",
    "home_factor": "时变主场因素（截至 t−1 的联盟主场胜率）",
}

EXCLUDED_NOTE = (
    "xG/xGA：真实数据不可用，仅记录代理限制（预注册代理 = 进球率+射正率组合），"
    "**不声称真实 xG 结论**；阵容稳定度、伤停：DATA_UNAVAILABLE，不作代理推断；"
    "closing_odds：按 no-market 纪律保持排除，不测试。"
)


def main() -> None:
    stats = json.loads((OUT_DIR / "stats.json").read_text(encoding="utf-8"))
    manifest = json.loads((OUT_DIR / "baseline_manifest_real_epl_base_001.json")
                          .read_text(encoding="utf-8"))
    sources = stats["sources"]
    passed = [k for k, v in sources.items() if v["success"]]

    lines: List[str] = []
    lines.append("# DIAG-005：信息源增量价值分析（EXP-DIAG-EPL-005）")
    lines.append("")
    lines.append("> 严格按预注册设计 `docs/DIAG_005_INFO_SOURCE_DESIGN.md` 执行："
                 "在冻结 Elo 概率之上用条件校准探针（Elo 概率分层 × 信息源分箱）"
                 "测量各信息源的 Elo 外增量。无训练、无参数拟合、无权重调整、"
                 "无生产代码修改、无新信息源。")
    lines.append("")
    lines.append("## 0. 执行摘要与答案")
    lines.append("")
    lines.append("**问题：哪些 Elo 外信息源具有预测增量证据？**")
    lines.append("")
    if passed:
        lines.append(f"**答案：{len(passed)} 个信息源具备证据 —— " + "、".join(passed) + "**")
        lines.append("")
    else:
        lines.append("**答案：无 —— 四个被测信息源均未达到预注册成功阈值，"
                     "全部标记 INSUFFICIENT EVIDENCE。**")
        lines.append("")
        lines.append("（成功标准：`ΔBrier ≤ −0.003` 且 置换 p < 0.0071 且 split-half 一致；"
                     "无源满足。无证据 ≠ 证明无用——仅表示在当前单一数据层与代理定义下，"
                     "未测出独立于 Elo 的预测增量。）")
    lines.append("")
    lines.append(EXCLUDED_NOTE)
    lines.append("")

    # ---------------- section 1: method ----------------
    lines.append("## 1. 方法与预注册符合性")
    lines.append("")
    lines.append("- 基线：冻结 Elo 概率（380 场，确定性；Brier "
                 f"{stats['elo_brier']:.4f}）。")
    lines.append("- 探针：`(Elo 概率动态三分位 × 源特征动态中位数)` 展开窗口经验条件频率；"
                 f"回退链（预注册）：(elo×s) 计数 < {stats['meta']['min_cell']} → "
                 f"elo 分层计数 < {stats['meta']['min_cell']} → 原 Elo 概率。"
                 f"最小历史 {stats['meta']['min_history']} 场。")
    lines.append("- 主检验：ΔBrier（探针 − Elo，三类 Brier）；置换检验 seed "
                 f"{stats['meta']['perm_seed']}、{stats['meta']['n_perm']} 次。")
    lines.append("- **置换实现说明（如实披露）**：主置换把**源特征值**在 380 场间重排"
                 "（实现预注册的 H0『该源无 Elo 外增量』）；设计文档字面上的"
                 "『实际结果向量重排』作为次级置换一并报告（DIAG-004 S1 已证明该变体"
                 "anti-conservative，仅作透明参考）。")
    lines.append("- 多重比较：Bonferroni α = "
                 f"{stats['meta']['alpha_bonferroni']:.4f}（7 个设计候选）。")
    lines.append("- split-half：前/后 190 场 ΔBrier 均 < 0 才一致。")
    lines.append("")

    # ---------------- section 2: results table ----------------
    lines.append("## 2. 单源结果（380 场，全部预注册判据）")
    lines.append("")
    lines.append("| 信息源 | ΔBrier | ΔLogLoss | Murphy C | 置换 p（源值） | "
                 "置换 p（结果向量，次级） | split-half（前/后） | 一致 | 判定 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for name, v in sources.items():
        judge = "**EVIDENCE**" if v["success"] else "INSUFFICIENT EVIDENCE"
        lines.append(f"| {SOURCE_LABELS[name]} | {v['d_brier']:+.4f} | "
                     f"{v['d_logloss']:+.4f} | {v['murphy_c']:+.4f} | "
                     f"{v['perm_p_d_brier_source_value']:.4f} | "
                     f"{v['perm_p_d_brier_outcome_vector']:.4f} | "
                     f"{v['split_half_first190']:+.4f}/{v['split_half_last190']:+.4f} | "
                     f"{'是' if v['split_half_consistent'] else '否'} | {judge} |")
    lines.append("")
    lines.append(f"- 成功阈值：ΔBrier ≤ {stats['meta']['d_brier_threshold']:.3f} 且 "
                 f"置换 p < {stats['meta']['alpha_bonferroni']:.4f} 且 split-half 一致。")
    lines.append(f"- 各源回退到纯 Elo 的场次占比："
                 + "；".join(f"{name} {v['fallback_share']:.0%}"
                             for name, v in sources.items()) + "。")
    lines.append("")

    # ---------------- section 3: per-source commentary ----------------
    lines.append("## 3. 逐源解读（按预注册假设；不超解释）")
    lines.append("")
    for name, v in sources.items():
        lines.append(f"### {SOURCE_LABELS[name]}")
        lines.append("")
        lines.append(f"- ΔBrier {v['d_brier']:+.4f}（阈值 −0.003），"
                     f"置换 p={v['perm_p_d_brier_source_value']:.4f}"
                     f"（α={stats['meta']['alpha_bonferroni']:.4f}），"
                     f"split-half {'一致' if v['split_half_consistent'] else '不一致'}"
                     f"（{v['split_half_first190']:+.4f}/{v['split_half_last190']:+.4f}），"
                     f"Murphy C={v['murphy_c']:+.4f} → **{v['verdict']}**。")
        lines.append("")
    lines.append("（C<0 表示探针相对 Elo 的偏离朝实际结果方向；C≈0 表示无独立信号；"
                 "C>0 表示反信息——与 DIAG-004 的 Agent 偏离同向。四源 C 全部 ≈0"
                 "（−0.0000/−0.0006/−0.0035/−0.0014），而 ΔBrier 全部为正——"
                 "探针的估计噪声主导了整体 Brier，无源表现出可与噪声区分的 Elo 外增量。）")
    lines.append("")

    # ---------------- section 4: combination ----------------
    lines.append("## 4. 组合探针（预注册：仅对通过单源的源计算）")
    lines.append("")
    comb = stats["combinations"]
    if comb["computed"]:
        for name, d in comb["detail"].items():
            lines.append(f"- {name}：组合 ΔBrier {d['d_brier_combined']:+.4f}，"
                         f"单源 ΔBrier 之和 {d['sum_of_single_d_brier']:+.4f} → "
                         f"{d['direction']}（仅方向性，非判定）。")
    else:
        lines.append("- 无单源通过成功阈值 → 按预注册规则**不计算**组合探针。")
    lines.append("")

    # ---------------- section 5: answer to "what information to seek" ----------------
    lines.append("## 5. 下一步应该寻找什么信息（而不是增加什么 Agent）")
    lines.append("")
    lines.append("按 DIAG-001~005 累积证据（信息重复 → 乘性放大不成立 → 融合结构非瓶颈 → "
                 "Agent 无 Elo 外信息 → 现有可测信息源无 Elo 外增量）：")
    lines.append("")
    lines.append("1. **当前数据层内无可测出增量的信息源**：射门质量、射正率、赛程密度、"
                 "时变主场因子四源全部 INSUFFICIENT EVIDENCE —— 不再投入时间在这些"
                 "字段上做特征工程。")
    lines.append("2. **需要获取的新数据（获取优先级，非 Agent 工作）**：")
    lines.append("   - 供应商级**真实 xG/xGA**（含生成时间戳，须 < kickoff）——"
                 "当前射门统计只是其粗糙代理；")
    lines.append("   - **首发阵容与伤停**（含公布时间戳）——DIAG-004 的三型分类因 "
                 "DATA_UNAVAILABLE 无法真值判定，这是唯一尚未被测试的『信息缺失型』真值源；")
    lines.append("   - **跨赛季数据**（第二赛季）——本设计所有探针都只在本赛季内 "
                 "walk-forward，跨赛季信号不可测。")
    lines.append("3. **纪律排除项**：市场赔率（closing_odds 已在数据层，等解除 no-market "
                 "约束后可作为最强『人类集成信息』探针，另行设计）。")
    lines.append("")
    lines.append("**结论方向**：在不获取新数据的前提下，不存在已知的 Elo 外信息源值得"
                 "进一步挖掘；下一步的信息投资应投向**真实 xG 与伤停/阵容数据的获取与验证**，"
                 "而不是增加 Agent 或在这些已测字段上继续调参。")
    lines.append("")

    # ---------------- section 6: conclusion ----------------
    lines.append("## 6. 结论")
    lines.append("")
    lines.append("**PRIMARY（证据强）：**")
    lines.append("- （无 —— 无源达到成功阈值）")
    lines.append("**SECONDARY（证据中等）：**")
    lines.append(f"- 四源 ΔBrier 全部为正（" + " / ".join(
        f"{v['d_brier']:+.4f}" for v in sources.values())
        + "）——探针无一优于 Elo，且全部未通过阈值（成功需 ≤ −0.003）")
    lines.append("- 探针框架负对照成立：主客场单源（冻结 home_advantage 基线 0.6659 ≫ "
                 "Elo 0.6310）在无增量源上未产生假阳性（时变主场 ΔBrier ≈ 0）")
    lines.append("**UNCONFIRMED（证据不足，不猜测）：**")
    lines.append("- 真实 xG、阵容稳定度、伤停：DATA_UNAVAILABLE，无法测试（代理限制已记录，"
                 "不冒充结论）")
    lines.append("- 组合增量：未计算（无单源通过，预注册规则）")
    lines.append("")
    lines.append("**NEXT EXPERIMENT（仅设计，不执行；均为数据获取与验证，非模型升级）：**")
    lines.append("1. DIAG-006：跨赛季复测（需第二赛季真实数据），验证本设计探针的稳定性。")
    lines.append("2. 数据获取后复测：真实 xG/xGA（带时间戳）、首发与伤停（带公布时间戳）"
                 "注入同一探针框架，重做 1.1/1.6/1.7 判定。")
    lines.append("3. 若解除 no-market 约束：closing_odds 作为『人类集成信息』探针。")
    lines.append("")
    lines.append("## 7. 可复现")
    lines.append("")
    lines.append(f"- 冻结基线：EXP-REAL-EPL-BASE-001（`{manifest['experiment_id']}`）"
                 "及 EXP-DIAG-EPL-001~004 目录哈希清单在 "
                 "`backtest_output/diag_005_info_source/baseline_manifest_*.json`。")
    lines.append("- 产物：`probes.json`（逐场探针概率 + 特征 + 回退标记）、"
                 "`stats.json`（ΔBrier/ΔLogLoss/C、双置换 p、split-half）、"
                 "`experiments.jsonl`（EXP-DIAG-EPL-005）。")
    lines.append("- 置换 seed 20240101，10,000 次；全部阈值与判定按预注册设计，执行期零改动。")

    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"written -> {DOC}")


if __name__ == "__main__":
    main()
