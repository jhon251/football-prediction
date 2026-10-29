"""EXP-DIAG-EPL-008 (DIAG-008) report generator.

Reads backtest_output/diag_008_xg_validation/{probes,stats}.json and writes
docs/DIAG_008_XG_INCREMENTAL_VALUE.md.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

OUT_DIR = Path("backtest_output/diag_008_xg_validation")
DOC = Path("docs/DIAG_008_XG_INCREMENTAL_VALUE.md")

SOURCE_LABELS = {
    "xg_for_diff": "xG for 差（主队滚动 xG for − 客队滚动 xG for）",
    "xg_against_diff": "xG against 差（主队滚动 xG against − 客队滚动 xG against）",
    "xg_net_diff": "xG 净值差（主队 xG净 − 客队 xG净）",
    "home_xg_for": "home/away 分离：主队滚动 xG for",
    "away_xg_for": "home/away 分离：客队滚动 xG for",
}


def main() -> None:
    stats = json.loads((OUT_DIR / "stats.json").read_text(encoding="utf-8"))
    manifest = json.loads((OUT_DIR / "baseline_manifest_real_epl_base_001.json")
                          .read_text(encoding="utf-8"))
    sources = stats["sources"]
    passed = [k for k, v in sources.items() if v["success"]]

    lines: List[str] = []
    lines.append("# DIAG-008：Understat 滚动 xG/xGA 增量价值验证（EXP-DIAG-EPL-008）")
    lines.append("")
    lines.append("> 唯一目标：判断**严格时间安全**的 Understat rolling xG/xGA 是否能在"
                 "**冻结 Elo** 基础上提供可统计区分的增量预测价值。")
    lines.append("> 纪律：探针框架**逐字复用 DIAG-005**（`exp_diag_005_run.py`），未为 xG "
                 "重新设计；未修改生产模型/config/35 条规则；未调 Elo 参数；未搜索窗口"
                 "（window=10 冻结）；未调整权重；未训练模型；未接入其他数据源；未进入 V1.3。")
    lines.append("")
    lines.append("## 0. 执行摘要与答案")
    lines.append("")
    lines.append("**问题：严格时间安全的 Understat rolling xG/xGA 是否具备 Elo 外增量？**")
    lines.append("")
    if passed:
        lines.append(f"**答案：是（EVIDENCE）—— {len(passed)} 个 xG 特征通过全部预注册判据。**")
        lines.append("（仅报告通过情况：暂不修改生产模型、暂不进入 V1.3。）")
    else:
        lines.append("**答案：INSUFFICIENT EVIDENCE —— 所有 xG 特征均未通过预注册成功标准，"
                     "未发现其具备 Elo 外预测增量。**")
        lines.append("（不使用『接近显著』『有潜力』等替代措辞——正式判定即 INSUFFICIENT EVIDENCE。）")
    lines.append("")
    lines.append(f"- 冻结 Elo 基线 Brier：{stats['elo_brier']:.4f}（380 场）。")
    lines.append(f"- xG 数据：DATA-002 冻结 `rolling_2025.csv`，data_version "
                 f"`{stats['meta']['xg_data_version'][:16]}…`（fingerprint "
                 f"{stats['meta']['xg_fingerprint']}），window=10，严格 datetime<kickoff，"
                 "未重新抓取。")
    lines.append("")
    lines.append("## 1. 方法（与 DIAG-005 完全可比）")
    lines.append("")
    lines.append("- 测试集边界：全部 380 场（与 DIAG-005 相同）。")
    lines.append("- walk-forward：探针展开窗口只用严格先前比赛（与 DIAG-005 相同）。")
    lines.append("- 探针：`(Elo 概率动态三分位 × 特征动态中位数)` 条件频率 + 回退链"
                 "（<20 → elo 分层 <20 → 原 Elo；最小历史 30）。**逐字复用 DIAG-005 代码。**")
    lines.append("- **执行披露（非框架变更）**：置换循环使用同一数学的**纯向量化实现**"
                 "（`exp_diag_008_fast.py`）；每个源在写入结果前都通过与逐字实现的"
                 "**逐场一致性校验**（探针概率 max|Δ|=0.00，fallback 标记完全一致）"
                 "——框架数学零改动，仅执行方式不同。")
    lines.append("- 置换 rng 注记：每个源使用独立的 `rng(default_rng(20240101))` 实例"
                 "（同一预注册 seed 的相同 iid 均匀流；与 DIAG-005 共享游标方式仅"
                 "抽取顺序不同，均为无偏蒙特卡洛估计）。")
    lines.append(f"- 置换：seed {stats['meta']['perm_seed']}，{stats['meta']['n_perm']} 次"
                 "（与 DIAG-005 相同）；主置换 = 源特征值重排，次级 = 结果向量重排（透明参考）。")
    lines.append(f"- 统计口径：三类 Brier、LogLoss、Murphy 信息项 C（与 DIAG-005 相同）。")
    lines.append("")
    lines.append("## 2. 单源结果（全部预注册判据）")
    lines.append("")
    lines.append("| xG 特征 | ΔBrier | ΔLogLoss | Murphy C | 置换 p（源值） | "
                 "置换 p（结果向量，次级） | split-half（前/后） | 一致 | 有效样本 | "
                 "fallback | 判定 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for name, v in sources.items():
        judge = "**EVIDENCE**" if v["success"] else "INSUFFICIENT EVIDENCE"
        lines.append(f"| {SOURCE_LABELS[name]} | {v['d_brier']:+.4f} | "
                     f"{v['d_logloss']:+.4f} | {v['murphy_c']:+.4f} | "
                     f"{v['perm_p_d_brier_source_value']:.4f} | "
                     f"{v['perm_p_d_brier_outcome_vector']:.4f} | "
                     f"{v['split_half_first190']:+.4f}/{v['split_half_last190']:+.4f} | "
                     f"{'是' if v['split_half_consistent'] else '否'} | "
                     f"{v['valid_sample']} | {v['fallback_rate']:.0%} | {judge} |")
    lines.append("")
    lines.append("**成功标准（五项全部满足才算 EVIDENCE）**：")
    lines.append(f"- ΔBrier ≤ {stats['meta']['d_brier_threshold']:.3f}；")
    lines.append(f"- 置换 p < {stats['meta']['alpha_bonferroni']:.4f}（源值置换）；")
    lines.append("- split-half 一致（前/后 190 场 ΔBrier 均 < 0）；")
    lines.append(f"- 有效样本 ≥ {stats['meta']['min_valid_sample']}；")
    lines.append(f"- fallback 率 ≤ {stats['meta']['max_fallback']:.0%}。")
    lines.append("")
    lines.append("注：`xg_against_diff` 的置换 p=0.0040 < 0.0071（该特征与结果的关联在"
                 "置换检验下可检测），但其 ΔBrier=+0.0029 > 0（探针仍**差于** Elo）"
                 "且 split-half 不一致 → 按预注册五项标准仍判 INSUFFICIENT EVIDENCE。"
                 "（如实记录，不用『接近显著』措辞替代正式判定。）")
    lines.append("")
    lines.append("## 3. 组合探针（预注册规则）")
    lines.append("")
    comb = stats["combinations"]
    if comb["computed"]:
        for name, d in comb["detail"].items():
            lines.append(f"- {name}：组合 ΔBrier {d['d_brier_combined']:+.4f}，"
                         f"单源 ΔBrier 之和 {d['sum_of_single_d_brier']:+.4f} → "
                         f"{d['direction']}（仅方向性，非判定）。")
    else:
        lines.append("- 无单源通过成功标准 → 按预注册规则**不执行**组合探针"
                     "（不允许为寻找增益而事后组合特征）。")
    lines.append("")
    lines.append("## 4. 结论")
    lines.append("")
    lines.append("**PRIMARY（证据强）：**")
    if passed:
        lines.extend(f"- {SOURCE_LABELS[k]} 通过全部五项判据"
                     f"（ΔBrier {sources[k]['d_brier']:+.4f}）" for k in passed)
    else:
        lines.append("- （无 —— 无任一 xG 特征达到预注册成功标准）")
    lines.append("**SECONDARY（证据中等）：**")
    lines.append("- 各特征 ΔBrier / Murphy C 与置换 p 见第 2 节表（如实记录，不加工）")
    lines.append("**UNCONFIRMED（证据不足，不猜测）：**")
    if passed:
        lines.append("- （无）")
    else:
        lines.append("- xG/xGA 的 Elo 外增量：INSUFFICIENT EVIDENCE"
                     "（与 DIAG-005 射门统计类代理无增量的结果方向一致；"
                     "无证据 ≠ 证明无用）")
    lines.append("")
    lines.append("**NEXT（仅设计，不执行；不修改生产模型、不进入 V1.3）：**")
    lines.append("1. DIAG-009（设计待定）：跨赛季复测 xG 探针（2024-25 冻结数据隔离保留，"
                 "可作为第二赛季样本）。")
    lines.append("2. DATA-003（设计待定）：首发/伤停数据接入（DIAG-006/007 优先级），"
                 "届时按 DIAG-007 协议做 D7.2/D7.3 验证。")
    lines.append("")
    lines.append("## 5. 可复现")
    lines.append("")
    lines.append(f"- 冻结基线：EXP-REAL-EPL-BASE-001（`{manifest['experiment_id']}`）"
                 "及 EXP-DIAG-EPL-001~005 哈希清单在 "
                 "`backtest_output/diag_008_xg_validation/baseline_manifest_*.json`。")
    lines.append("- 产物：`probes.json`（逐场探针概率+特征+回退标记）、`stats.json`、"
                 "`experiments.jsonl`（EXP-DIAG-EPL-008）。")
    lines.append("- xG 数据 fingerprint：DATA-002 `ae9e746b4654d8ad`（full "
                 "`ae9e746b4654d8addb582bb3acf445ccbf575c72c31ede3f4f93be39f25cfa27`）。")
    lines.append("- 探针框架代码与 DIAG-005 逐字一致（未重新设计）。")

    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"written -> {DOC}")


if __name__ == "__main__":
    main()
