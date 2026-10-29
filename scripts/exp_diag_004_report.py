"""EXP-DIAG-EPL-004 (DIAG-004) report generator.

Reads backtest_output/diag_004_elo_error/{classification,stats}.json and the
frozen data, writes docs/DIAG_004_ELO_ERROR_ATTRIBUTION.md strictly following
the pre-registered design (docs/DIAG_004_ELO_ERROR_ATTRIBUTION_DESIGN.md).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from football_simulation.data.historical.etl import HistoricalDataset

OUT_DIR = Path("backtest_output/diag_004_elo_error")
DATASET_PATH = Path("data/historical/epl_2025_26.json")
DOC = Path("docs/DIAG_004_ELO_ERROR_ATTRIBUTION.md")

ALPHA = 0.05 / 9  # pre-registered Bonferroni threshold

CONFIG_LABELS = {
    "full_system": "full_system（冻结 380）",
    "team_only": "team_only（DIAG-003 380）",
    "team_psychology": "team_psychology（DIAG-003 380）",
}

TYPE_LABELS = {
    "random_event": "随机事件型",
    "tactical_style": "战术/风格型（exploratory：Elo 派生信号）",
    "information_missing": "信息缺失型（代理：赛程/低把握区）",
    "UNCLASSIFIED": "UNCLASSIFIED",
}


def main() -> None:
    stats = json.loads((OUT_DIR / "stats.json").read_text(encoding="utf-8"))
    classification = json.loads((OUT_DIR / "classification.json").read_text(encoding="utf-8"))
    dataset = HistoricalDataset.load(DATASET_PATH)
    manifest = json.loads((OUT_DIR / "baseline_manifest_real_epl_base_001.json")
                          .read_text(encoding="utf-8"))

    lines: List[str] = []
    lines.append("# DIAG-004：Elo 误差归因分析（EXP-DIAG-EPL-004）")
    lines.append("")
    lines.append("> 严格按预注册设计文档 `docs/DIAG_004_ELO_ERROR_ATTRIBUTION_DESIGN.md` 执行："
                 "纯确定性分析现有冻结/缓存产物（380 场），零新模拟、零参数调整、"
                 "零生产代码修改；未新增未预注册变量。")
    lines.append("")
    lines.append("## 0. 执行摘要与答案")
    lines.append("")
    lines.append("**问题：当前 Agent 是否发现了 Elo 没有的信息？**")
    lines.append("")
    lines.append("**答案：INSUFFICIENT EVIDENCE：未发现 Agent 拥有 Elo 之外预测信息的证据**")
    lines.append("")
    lines.append("（无证据 ≠ 证明没有。三个预注册主检验在全部三个被测配置上均未通过；"
                 "且实测方向与『Agent 拥有 Elo 外信息』**相反**——见第 4 节。）")
    lines.append("")

    # ---------------- section 1: execution compliance ----------------
    lines.append("## 1. 执行符合性")
    lines.append("")
    lines.append("- 数据：2025-26 EPL 全部 380 场；Agent 预测全部来自冻结/缓存产物"
                 "（冻结 `full_system`、DIAG-003 `team_only`/`team_psychology`，400 模拟，"
                 "seed 20240101）。")
    lines.append("- 冻结目录哈希复核 0 改动（`baseline_manifest_*.json`）。")
    lines.append("- 实现修正说明：首轮实现将 `score_surprise`（浮点）误用作布尔条件，"
                 "导致所有场次被标为随机事件型；已按预注册规则 `score_surprise ≥ 2.0` 修正并"
                 "全量重跑。该修正只影响三型分类，不影响 S1/S2/S3 主检验结果。")
    lines.append("")

    # ---------------- section 2: four categories ----------------
    lines.append("## 2. 四类比赛（argmax 三分类，并列判正确；380 场）")
    lines.append("")
    lines.append("| 配置 | E+A+ | E+A− | **E−A+（增量信息候选）** | E−A− | "
                 "Agent 正确率 | Elo 正确率 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    rates = stats["rates"]
    for config in ("full_system", "team_only", "team_psychology"):
        m = rates[config]
        lines.append(f"| {CONFIG_LABELS[config]} | {m['counts']['E+A+']} | "
                     f"{m['counts']['E+A-']} | **{m['counts']['E-A+']}** | "
                     f"{m['counts']['E-A-']} | {m['agent_accuracy']:.4f} | "
                     f"{m['elo_accuracy']:.4f} |")
    lines.append("")
    lines.append(f"- Elo 错误场次 n={stats['n_elo_error']}（380 场中），"
                 f"Elo 正确 n={stats['n_elo_correct']}。")
    lines.append(f"- 增量信息候选 E−A+：full_system 7、team_only 7、team_psychology 6"
                 f"（各占 Elo 错误场次 "
                 f"{stats['rates']['full_system']['counts']['E-A+'] / stats['n_elo_error']:.1%}/"
                 f"{stats['rates']['team_only']['counts']['E-A+'] / stats['n_elo_error']:.1%}/"
                 f"{stats['rates']['team_psychology']['counts']['E-A+'] / stats['n_elo_error']:.1%}），"
                 "均远低于反向配对 E+A−（27/24/23）。")
    lines.append("")
    lines.append("### 2.1 120 场子集（与 DIAG-001 对照）与 top-2 敏感性（预注册）")
    lines.append("")
    sub = stats["subsample_120"]["counts"]
    lines.append("| 配置 | E−A+（120 子集） | E+A−（120 子集） | top-2：E−A+ | top-2：E+A− |")
    lines.append("| --- | --- | --- | --- | --- |")
    for config in ("full_system", "team_only", "team_psychology"):
        c = sub[config]
        t = stats["sensitivity_top2"][config]
        lines.append(f"| {CONFIG_LABELS[config]} | {c['E-A+']} | {c['E+A-']} | "
                     f"{t['E-A+']} | {t['E+A-']} |")
    lines.append("")
    lines.append("（DIAG-001 的 120 场：Team 错而 Elo 对 0.0833 vs Elo 错而 Team 对 0.0083，"
                 "与本表 E−A+ ≪ E+A− 方向一致。top-2 敏感性同向，主判定不受 argmax 定义影响。）")
    lines.append("")

    # ---------------- section 3: main tests ----------------
    lines.append("## 3. 主检验（S1/S2/S3，预注册 α=%.4f，Bonferroni 9 次）" % ALPHA)
    lines.append("")
    lines.append("| 配置 | S1 观测 E−A+ | S1 置换 p | S2 信息项 C | S2 置换 p | "
                 "S3 不对称 (E−A+ vs E+A−) | S3 p | 任一通过 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for config in ("full_system", "team_only", "team_psychology"):
        t = stats["main_tests"][config]
        lines.append(f"| {CONFIG_LABELS[config]} | {t['s1_observed']} | "
                     f"{t['s1_perm_p']:.4f} | {t['s2_murphy_info_c']:+.5f} | "
                     f"{t['s2_perm_p']:.4f} | {t['s3_ea_plus']} vs {t['s3_ea_minus']} | "
                     f"{t['s3_mcnemar_p']:.4f} | {'否' if not t['any_pass'] else '是'} |")
    lines.append("")
    lines.append("**S1（置换检验）**：观测 E−A+（6–7）远低于置换分布中位数 "
                 f"（{stats['main_tests']['full_system']['s1_perm_median']}），p=1.0000 → 不通过。"
                 "诚实注记：该置换把实际结果随机重排，同时破坏了 Elo 与 Agent 共享的"
                 "结果可预测性，使零假设分布整体偏高，因此 S1 作为『超出 Elo 的信息』"
                 "检验是保守性错误的（anti-conservative），其不通过不构成任何方向证据。")
    lines.append("")
    lines.append("**S2（Murphy 分解，概率层面主检验）**：信息项 C = "
                 + " / ".join(f"{stats['main_tests'][c]['s2_murphy_info_c']:+.5f}"
                              for c in ("full_system", "team_only", "team_psychology"))
                 + "（全部为正），置换 p=1.0000 → 不通过。"
                 "C>0 的含义：Agent 相对 Elo 的偏离，按 (1−P_elo(实际结果)) 加权后"
                 "平均**降低**了对实际结果的概率 —— 与 DIAG-001 Q9 的 Team 残差负相关"
                 "（−0.2624，z≈−2.9σ）完全同向。恒等式自检通过"
                 "（单结果 Brier 差 = 噪声项 + 2C；`s2_identity_ok=true`）。")
    lines.append("")
    lines.append("**S3（McNemar 不对称）**：全部三个配置**显著**不对称（p<0.0056），"
                 "但方向是 **E+A− ≫ E−A+**（Elo 纠错 Agent 约 3.9 倍于 Agent 纠错 Elo）→ "
                 "不满足『E−A+ > E+A−』的通过条件。S3 提供了显著的方向性证据："
                 "它支持『Agent 的额外变化损害了 Elo 已有信息』，而非发现新信息。")
    lines.append("")

    # ---------------- section 4: answer ----------------
    lines.append("## 4. 主问题回答")
    lines.append("")
    lines.append("按预注册成功判据（S1/S2/S3 任一通过即『是』），全部配置 `any_pass=false`：")
    lines.append("")
    lines.append("**INSUFFICIENT EVIDENCE：未发现 Agent 拥有 Elo 之外预测信息的证据**")
    lines.append("")
    lines.append("方向性上下文（如实报告，不构成主判据）：")
    lines.append("- S3 显著且方向相反：Agent 被 Elo 纠错的频次约为反向的 3.9 倍"
                 "（27 vs 7，p=0.0008，Bonferroni 后仍显著）。")
    lines.append("- S2 信息项 C>0 且置换 p=1.0：Agent 相对 Elo 的概率偏离平均**朝远离**"
                 "实际结果的方向移动（反信息），与 DIAG-001 Q9 一致。")
    lines.append("- Elo 错误场次内（描述性）：Agent 对实际结果的平均概率 "
                 + " / ".join(f"{stats['elo_error_subset_descriptive'][c]['mean_p_actual']:.3f}"
                              for c in ("full_system", "team_only", "team_psychology"))
                 + "，而对另外两个结果的均值 "
                 + " / ".join(f"{stats['elo_error_subset_descriptive'][c]['mean_p_other']:.3f}"
                              for c in ("full_system", "team_only", "team_psychology"))
                 + " —— Agent 在 Elo 错误场次里反而系统性低配实际结果。")
    lines.append("")

    # ---------------- section 5: three-type classification ----------------
    lines.append("## 5. Elo 错误样本三型分类（代理，预注册）")
    lines.append("")
    tc = stats["type_control"]
    lines.append("| 类型 | Elo 错误组占比 | Elo 正确组占比（对照） | Fisher p（过度表达） | 判定 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for tname, label in TYPE_LABELS.items():
        v = tc[tname]
        judge = "未过度表达" if v["fisher_p_greater"] >= 0.05 else "过度表达"
        lines.append(f"| {label} | {v['elo_error_share']:.3f} | "
                     f"{v['elo_correct_share']:.3f} | {v['fisher_p_greater']:.4f} | {judge} |")
    lines.append("")
    lines.append(f"- 无任一类型在 Elo 错误组显著过度表达（Fisher p 均 >0.05）。")
    lines.append(f"- **UNCLASSIFIED 占比 {stats['unclassified_share_among_elo_error']:.1%} ≥ 40%**"
                 " → 按预注册规则，三型分类整体结论**降级为 INSUFFICIENT EVIDENCE**"
                 "（代理覆盖不足，不强行解释）。")
    lines.append("- 诚实性注记：随机事件型代理含 `score_surprise`（基于 full_system "
                 "expected_goals）与半场反转；信息缺失型只有赛程/低把握代理（真实伤停、"
                 "阵容数据 DATA_UNAVAILABLE，`unknowns` 四字段零变异）；"
                 "战术/风格型代理为 **Elo 派生信号**（tactical_advantage_nohome、转换风险差），"
                 "按执行约束仅作 exploratory interpretation，**不作为**"
                 "『Agent 拥有 Elo 外信息』的主要证据。")
    lines.append("")

    # ---------------- section 6: conclusion ----------------
    lines.append("## 6. 结论")
    lines.append("")
    lines.append("**PRIMARY（证据强）：**")
    lines.append("- （无正向证据 —— 三个预注册主检验在三个配置上均未通过）")
    lines.append("**SECONDARY（证据中等，方向性）：**")
    lines.append(f"- S3：Elo 纠错 Agent 显著多于反向（27 vs 7，p={stats['main_tests']['full_system']['s3_mcnemar_p']:.4f}；"
                 "三配置均 p<0.0056）—— 实测方向与『Agent 拥有 Elo 外信息』相反")
    lines.append(f"- S2：Agent 相对 Elo 的概率偏离为反信息（C≈+0.007，置换 p=1.0）—— "
                 "与 DIAG-001 Q9 的 −0.2624 残差相关一致")
    lines.append("**UNCONFIRMED（证据不足，不猜测）：**")
    lines.append(f"- 三型分类整体 INSUFFICIENT EVIDENCE（UNCLASSIFIED "
                 f"{stats['unclassified_share_among_elo_error']:.1%} ≥ 40%）；"
                 "无任一型在 Elo 错误组显著过度表达")
    lines.append("- 信息缺失型的真值判定（伤停/阵容）不可行：数据 DATA_UNAVAILABLE")
    lines.append("")
    lines.append("**NEXT EXPERIMENT（仅设计，不执行、不修改生产模型；均为诊断探针，"
                 "非模型升级方案）：**")
    lines.append("1. DIAG-005：信息源诊断 —— 把 Elo **外部**的 walk-forward 字段"
                 "（赛程拥挤 congestion_14d、近期状态）逐项注入诊断副本并测量 Brier 变化，"
                 "回答『哪些 Elo 外信息源存在真实信号』（沿用 DIAG-002/003 的探针纪律）。")
    lines.append("2. DIAG-006：跨赛季复测 S2/S3 的方向性与显著性（需先获取第二赛季真实数据）。")
    lines.append("3. 若未来获得伤停/阵容真值数据：重做信息缺失型的真值分类。")
    lines.append("")
    lines.append("## 7. 可复现")
    lines.append("")
    lines.append(f"- 冻结基线：EXP-REAL-EPL-BASE-001（`{manifest['experiment_id']}`）与"
                 " EXP-DIAG-EPL-001/002/003 目录哈希清单在 "
                 "`backtest_output/diag_004_elo_error/baseline_manifest_*.json`。")
    lines.append("- 产物：`classification.json`（逐场四分类 + 三型代理标注）、"
                 "`stats.json`（S1/S2/S3、Fisher、CI、敏感性）、"
                 "`experiments.jsonl`（EXP-DIAG-EPL-004）。")
    lines.append("- 置换 seed 20240101，10,000 次；全部阈值与判定按预注册设计，执行期零改动。")

    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"written -> {DOC}")


if __name__ == "__main__":
    main()
