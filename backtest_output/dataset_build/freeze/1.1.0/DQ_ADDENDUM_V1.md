# DQ ADDENDUM V1（对 DATASET QUALIFICATION REPORT 的补充修正）

性质：只读补充，**不覆盖、不修改**原始 DQ 报告（`hist_csv_audit/DATASET_QUALIFICATION_REPORT.md` 保持原样）。
关联：`HIST_FD_5L_2015_2026 v1.0.0`（FROZEN）。

## 修正 1：赔率非法值结论（修正 DQ 中"赔率 ≤0 异常 0"）

DQ V2 曾基于抽样得出"赔率 ≤0 异常 0（仅亚盘让球线负值，合法）"——**该结论不准确**。全量构建发现真实盘口列存在非法价格：

| 统计 | 值 |
|---|---|
| 非法价格单元格总数 | **16** |
| 字面量 `0` | 15 |
| `0.42`（<1.0 不可能为市场价格） | 1 |
| 涉及比赛（(file,row)） | **6**（注：任务描述写"8 场"，以冻结 manifest 实测为准 = 6 场） |
| 原始 CSV | **未修改** |
| v1.0.0 处理 | 按冻结 CANONICAL_SCHEMA 校验门（"赔率 >1.0 否则 NULL"）在 canonical 层置 NULL，记录于 build manifest |

明细（16 单元格）：

| 文件 | 行 | 列 | 值 |
|---|---|---|---|
| E021.csv | 168 | B365C>2.5 | 0 |
| E021.csv | 168 | B365C<2.5 | 0 |
| sp125.csv | 84 | PC>2.5 | 0 |
| sp125.csv | 84 | PC<2.5 | 0 |
| D119.csv | 261 | AvgC>2.5 | 0.42 |
| D124.csv | 295 | P>2.5 / P<2.5 / PC>2.5 / PC<2.5 | 0 ×4 |
| F124.csv | 263 | P>2.5 / P<2.5 / PC>2.5 / PC<2.5 | 0 ×4 |
| F124.csv | 303 | 1XBH / 1XBD / 1XBA | 0 ×3 |

**结论**：该问题已被 v1.0.0 的 canonical/null policy 正确治理（转 NULL + 留痕），**不构成冻结数据集完整性 blocker**。

## 修正 2（新增发现）：季节标签边界缺陷（10 行）

- 根因：v1.0.0 的 `season` 由 kickoff_date 按"8 月为界"启发式推导；COVID 使意甲 2019-20 收官轮推迟至 **2020-08-01/02** 进行，被误标为 `2020-21`。
- 影响：**10 行**（全部 `I119.csv`，即意甲 2019-20 最后一轮）season 标签 +1 年；2019-20 少 10、2020-21 多 10；**tier 不受影响**（两季均 DATETIME）；比赛/比分/赔率/provenance 均正确。
- 建议（未来版本，本轮不执行）：season 应**取源文件赛季**（canonical manifest 的 file→season 映射），而非 kickoff_date 启发式。

## 结论
- 冻结数据集行数、比分、赔率、provenance、指纹均正确完整；上述两项为"标签/单元格级"治理项，均已留痕。
- DQ 需要 V2 正式版还是 ADDENDUM：**ADDENDUM 即可**（两处均为登记级修正，无结构性结论变化；原始 DQ 报告不覆盖，以 ADDENDUM 累积修订）。
