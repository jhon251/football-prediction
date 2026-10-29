# SEASON_BOUNDARY_ADDENDUM.md（季节边界复核）

性质：只读研究，不修改 v1.0.0。关联：`DQ_ADDENDUM_V1` 修正 2。

## 1. 确认：source filename season 是 canonical authority
- 是。`I119.csv` = 意甲 **2019-20** 赛季文件（文件本身语义无歧义）；`season` 应由源文件（canonical manifest 的 file→season 映射）决定，而非 kickoff_date 启发式。

## 2. 受影响比赛（10 条，全部 I119.csv 意甲 2019-20 收官轮）
COVID 使 2019-20 意甲最后一轮推迟到 2020-08-01/02 进行：

| kickoff_date | 对阵 | dataset season | source season |
|---|---|---|---|
| 2020-08-01 | Atalanta v Inter | 2020-21 | 2019-20 |
| 2020-08-01 | Brescia v Sampdoria | 2020-21 | 2019-20 |
| 2020-08-01 | Juventus v Roma | 2020-21 | 2019-20 |
| 2020-08-01 | Milan v Cagliari | 2020-21 | 2019-20 |
| 2020-08-01 | Napoli v Lazio | 2020-21 | 2019-20 |
| 2020-08-02 | Bologna v Torino | 2020-21 | 2019-20 |
| 2020-08-02 | Genoa v Verona | 2020-21 | 2019-20 |
| 2020-08-02 | Lecce v Parma | 2020-21 | 2019-20 |
| 2020-08-02 | Sassuolo v Udinese | 2020-21 | 2019-20 |
| 2020-08-02 | Spal v Fiorentina | 2020-21 | 2019-20 |

（完整机器可读：`SEASON_BOUNDARY_CASES.json`）

## 3. 影响评估
- season 标签 +1 年（2019-20 少 10、2020-21 多 10）；**tier 不受影响**（两季均 DATETIME）；比分/赔率/provenance 正确；Frozen 行数不变。

## 4. v1.1.0 migration plan（设计，不执行）
1. 新增构建规则：`season` 取自 canonical manifest 的 `file→season` 映射（源文件权威），不再用 kickoff_date 启发式。
2. 重跑 S2-S5 → 产生 v1.1.0（X.Y.Z 中 Z 级修正，符合 DATASET_FREEZE_SPEC 版本规则）。
3. v1.0.0 **不修改、不解冻**；v1.1.0 为独立新版本。
4. 需授权后才执行。
