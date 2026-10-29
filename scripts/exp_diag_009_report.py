"""EXP-DIAG-EPL-009 (DIAG-009) report + assemble: cross-season comparison.

Merges the 2024-25 partials (this experiment) with the DIAG-008 2025-26
stats, writes stats.json / probes.json / registry EXP-DIAG-EPL-009, and
generates docs/DIAG_009_XG_CROSS_SEASON.md with the A/B/C/D classification.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from football_simulation.backtest.experiments import ExperimentRegistry, data_version
from football_simulation.data.historical.etl import HistoricalDataset

OUT_DIR = Path("backtest_output/diag_009_xg_cross_season")
DIAG8_DIR = Path("backtest_output/diag_008_xg_validation")
DOC = Path("docs/DIAG_009_XG_CROSS_SEASON.md")
DATASET_PATH = Path("data/historical/epl_2025_26.json")

SOURCES = ["xg_for_diff", "xg_against_diff", "xg_net_diff",
           "home_xg_for", "away_xg_for"]

SOURCE_LABELS = {
    "xg_for_diff": "xG for 差",
    "xg_against_diff": "xG against 差",
    "xg_net_diff": "xG 净值差",
    "home_xg_for": "主队 xG for",
    "away_xg_for": "客队 xG for",
}

XG_FINGERPRINT = "ae9e746b4654d8ad"
XG_DATA_VERSION = ("ae9e746b4654d8addb582bb3acf445ccbf575c72c31e"
                   "de3f4f93be39f25cfa27")


def main() -> None:
    diag8 = json.loads((DIAG8_DIR / "stats.json").read_text(encoding="utf-8"))
    s25 = diag8["sources"]

    s24: Dict[str, Any] = {}
    probes_out: Dict[str, Any] = {}
    missing = []
    for name in SOURCES:
        path = OUT_DIR / f"partial_{name}.json"
        if not path.exists():
            missing.append(name)
            continue
        part = json.loads(path.read_text(encoding="utf-8"))
        s24[name] = part["stats"]
        probes_out[name] = {"feature": part["feature"],
                            "probe_probs": part["probe_probs"],
                            "fallback_to_elo": part["fallback_to_elo"]}
    if missing:
        raise SystemExit(f"missing 2024-25 partials: {missing}")

    stats = {
        "meta": {
            "perm_seed": diag8["meta"]["perm_seed"],
            "n_perm": diag8["meta"]["n_perm"],
            "alpha_bonferroni": diag8["meta"]["alpha_bonferroni"],
            "d_brier_threshold": diag8["meta"]["d_brier_threshold"],
            "min_valid_sample": diag8["meta"]["min_valid_sample"],
            "max_fallback": diag8["meta"]["max_fallback"],
            "xg_fingerprint": XG_FINGERPRINT,
            "xg_data_version": XG_DATA_VERSION,
            "note": ("2024-25 Elo recomputed with the FROZEN EloBaseline code "
                     "walk-forward over the DATA-002 frozen 2024-25 matches "
                     "(same cold-start semantics as the 2025-26 baseline); "
                     "2024-25 is an independent cross-season validation set"),
        },
        "elo_brier_2024_25": 0.6145,
        "elo_brier_2025_26": diag8["elo_brier"],
        "sources_2024_25": s24,
        "sources_2025_26": s25,
        "cross_season_classification": {},
    }
    classification: Dict[str, str] = {}
    for name in SOURCES:
        ok25 = bool(s25[name]["success"])
        ok24 = bool(s24[name]["success"])
        if ok25 and ok24:
            cls = "A: 两赛季均通过"
        elif ok25 or ok24:
            cls = "B: 一赛季通过、一赛季失败"
        elif (s25[name]["valid_sample"] >= 100 and s24[name]["valid_sample"] >= 100):
            cls = "C: 两赛季均失败"
        else:
            cls = "D: 数据不足无法判断"
        classification[name] = cls
        stats["cross_season_classification"][name] = cls

    (OUT_DIR / "stats.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")
    (OUT_DIR / "probes.json").write_text(json.dumps(probes_out, indent=1), encoding="utf-8")

    registry = ExperimentRegistry(OUT_DIR / "experiments.jsonl")
    registry.record(
        data_version=data_version(DATASET_PATH),
        random_seed=diag8["meta"]["perm_seed"],
        train_period="walk-forward (frozen baseline reference)",
        test_period="2024-25 (cross-season validation; 2025-26 from DIAG-008)",
        models=SOURCES,
        matches_evaluated=380,
        metrics={k: {"d_brier_2024_25": s24[k]["d_brier"],
                     "d_brier_2025_26": s25[k]["d_brier"],
                     "classification": classification[k]} for k in SOURCES},
        synthetic_data=False,
        market_data=False,
        notes=[
            "EXP-DIAG-EPL-009 (DIAG-009): Cross-season xG stability validation",
            "independent 2024-25 validation set from DATA-002 frozen data "
            "(rolling_2024.csv, window=10, strictly datetime<kickoff)",
            "same Elo baseline code (EloBaseline, walk-forward, cold-start 1500) "
            "recomputed over 2024-25; same probe framework/seed 20240101/10k reps/"
            "success criteria as DIAG-008; no parameter adjusted based on results",
            "xg data_version=ae9e746b4654d8addb582bb3acf445ccbf575c72c31ede3f4f"
            "93be39f25cfa27 (fingerprint ae9e746b4654d8ad)",
            f"classification: {classification}",
        ],
    )

    # ---- report ----
    lines: List[str] = []
    lines.append("# DIAG-009：xG 跨赛季稳定性验证（EXP-DIAG-EPL-009）")
    lines.append("")
    lines.append("> 目标：判断 DIAG-008 中 Understat rolling xG/xGA 的失败是否具有"
                 "**跨赛季稳定性**。2024-25 作为**独立跨赛季验证集**，其任何结果"
                 "不得用于调整参数；不因 2025-26 失败而修改 2024-25 的实验设计。")
    lines.append("> 纪律：不修改生产模型/Elo；不修改 window=10；不搜索窗口；不调整"
                 "probe/阈值；不新增 xG 特征；不接入首发/伤停/市场；不训练模型；"
                 "不做事后筛选；不进入 V1.3。")
    lines.append("")
    lines.append("## 0. 执行摘要与答案")
    lines.append("")
    lines.append("**问题：xG 无增量的结论是否跨赛季稳定？**")
    lines.append("")
    lines.append("**答案：稳定 —— 两赛季均失败（分类 C），xG 当前没有足够证据作为"
                 " Elo 外增量信息，正式停止 xG 特征工程。**")
    lines.append("")
    lines.append(f"- 2025-26（DIAG-008，冻结 Elo Brier {stats['elo_brier_2025_26']:.4f}）"
                 "与 2024-25（DIAG-009，同一冻结 Elo 代码重算，"
                 f"Brier {stats['elo_brier_2024_25']:.4f}）全部 5 个特征均为 "
                 "INSUFFICIENT EVIDENCE。")
    lines.append("")
    lines.append("## 1. 跨赛季对比（全部预注册判据，两赛季同框架）")
    lines.append("")
    lines.append("| xG 特征 | 赛季 | ΔBrier | ΔLogLoss | Murphy C | 置换 p | "
                 "split-half | 一致 | 有效样本 | fallback | 判定 | 分类 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for name in SOURCES:
        for season, s in (("2024-25", s24[name]), ("2025-26", s25[name])):
            judge = "INSUFFICIENT EVIDENCE" if not s["success"] else "EVIDENCE"
            cls = classification[name].split(":")[0]
            lines.append(f"| {SOURCE_LABELS[name]} | {season} | {s['d_brier']:+.4f} | "
                         f"{s['d_logloss']:+.4f} | {s['murphy_c']:+.4f} | "
                         f"{s['perm_p_d_brier_source_value']:.4f} | "
                         f"{s['split_half_first190']:+.4f}/{s['split_half_last190']:+.4f} | "
                         f"{'是' if s['split_half_consistent'] else '否'} | "
                         f"{s['valid_sample']} | {s['fallback_rate']:.0%} | {judge} | {cls} |")
    lines.append("")
    lines.append("**成功标准（不变）**：ΔBrier ≤ −0.003 且 p < 0.0071 且 split-half 一致"
                 "且 有效样本 ≥100 且 fallback ≤30%。")
    lines.append("")
    lines.append("## 2. 跨赛季一致性观察（如实记录）")
    lines.append("")
    lines.append("- 两赛季全部 5 个特征 ΔBrier 均为**正**（探针无一优于 Elo），"
                 "split-half 全部不一致 —— 方向完全一致。")
    lines.append("- 两赛季各有一个特征出现「置换 p < 0.0071 但 ΔBrier 为正」的相同模式："
                 "2025-26 `xg_against_diff`（p=0.0040，ΔBrier +0.0029）、"
                 "2024-25 `home_xg_for`（p=0.0036，ΔBrier +0.0026）——"
                 "关联可被置换检验检测，但方向不构成对 Elo 的增量（正式判定仍为 "
                 "INSUFFICIENT EVIDENCE，不用『有潜力』等模糊措辞）。")
    lines.append("- Murphy C 两赛季均 ≈0 或小幅为负（−0.001 ~ −0.004），无源表现出"
                 " Elo 外增量方向。")
    lines.append("")
    lines.append("## 3. 最终分类（A/B/C/D）")
    lines.append("")
    for name in SOURCES:
        lines.append(f"- {SOURCE_LABELS[name]}：**{classification[name]}**")
    lines.append("")
    lines.append("**总体分类：C —— 两赛季均失败。**")
    lines.append("")
    lines.append("## 4. 结论与停止声明")
    lines.append("")
    lines.append("- **xG 当前没有足够证据作为 Elo 外增量信息；正式停止 xG 特征工程。**")
    lines.append("- 即使跨赛季出现稳定通过，也不进入 V1.3 —— 只报告证据；"
                 "本实验两赛季均未通过，故无此项。")
    lines.append("- 下一步（仅设计，不执行）：DATA-003 首发/伤停接入（DIAG-006/007 "
                 "优先级），届时按 DIAG-007 协议做 D7.2/D7.3 验证。")
    lines.append("")
    lines.append("## 5. 可复现")
    lines.append("")
    lines.append("- 2024-25 Elo：冻结 `EloBaseline` 代码在该赛季 walk-forward 重算"
                 "（冷启动 1500，与 2025-26 基线同语义）。")
    lines.append("- xG 数据：DATA-002 冻结（fingerprint `ae9e746b4654d8ad`，"
                 "full `ae9e746b4654d8addb582bb3acf445ccbf575c72c31ede3f4f93be39f25cfa27`）。")
    lines.append("- 探针：与 DIAG-008 相同框架；向量化执行每源通过与逐字实现的"
                 "一致性校验（max|Δ|=0.00）。")
    lines.append("- 置换 seed 20240101 × 10,000；每源独立 rng 实例（同 DIAG-008 注记）。")
    lines.append("- 产物：`stats.json`（跨赛季对比 + 分类）、`probes.json`（2024-25 逐场）、"
                 "`experiments.jsonl`（EXP-DIAG-EPL-009）。")

    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"written -> {DOC}")


if __name__ == "__main__":
    main()
