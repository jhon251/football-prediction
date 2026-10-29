# DATASET_CONTRACT.md（Dataset Contract v1.0）

## 1. Dataset ID
`HIST_FD_5L_2015_2026`（football-data.co.uk 五大联赛历史数据集）

## 2. Dataset version
`1.0.0-draft`（本契约为设计稿；正式 `1.0.0` 仅在 Dataset Freeze 时产生，见 DATASET_FREEZE_SPEC.md）

## 3. League coverage
E0（英超）/ SP1（西甲）/ I1（意甲）/ D1（德甲）/ F1（法甲）。**不含** SP2/F2/N1/E1 等次级联赛（excluded manifest 已排除）。

## 4. Season coverage
2015-16 ~ 2025-26（11 完整赛季，五联赛齐全）。2026-27 进行中（SP126，7 场）**独立跟踪，不纳入本版本**。

## 5. Sample counts（以 DQ canonical manifest 为准）
| 口径 | 数量 |
|---|---|
| raw（canonical 55 文件） | 19,765 |
| basicQC（剔除 2 条尾部空行） | 19,763 |
| tier3 B365H 完整 | 19,757 |
| tier3 B365H+AvgH（2019-20+） | 12,454 |

## 6. Label definition
- 主 Label：`FTR`（H/D/A）+ `FTHG`/`FTAG`（全场比分）——仅赛后使用。
- 次级 Label（LABEL-ONLY，不作赛前特征）：`HTHG`/`HTAG`/`HTR`。
- Label 一致性已过 DQ（FTR 与比分不一致 0）。

## 7. Feature eligibility
以 `FEATURE_AVAILABILITY_REGISTRY.md` 为准。原则：任何字段未经 registry 批准不得进入特征；赛后统计（HS..AR）**永久禁止**作为 Feature。

## 8. Temporal availability policy
引用 `policy/temporal_availability_policy.md`：
- TIER_DATE_ONLY：2015-16~2018-19（无 Time 列；**禁止伪造 kickoff time**）
- TIER_DATETIME：2019-20~2025-26（Date+Time → zoneinfo → kickoff_utc）

## 9. Leakage policy
引用 `policy/schema_policy.md` 分类（SAFE/CONDITIONAL/UNKNOWN/LABEL/LABEL-ONLY/LEAKAGE-RISK）。核心：12 个赛后统计列禁入 Feature；C 后缀列不因名为 "closing" 自动 SAFE。

## 10. Odds policy
- 非 C 赔率 = **pre-closing**（官方 notes.txt L48）；2015-18 单套赔率无 pre/closing 区分（L3）。
- C 后缀 = **closing**（官方 notes.txt L48），但为**采集时点（周五/周二）收盘快照**，非 kickoff 瞬间价格（L2）。
- 两者均开球前采集（官方 L198）→ 无赛后泄漏；但每列**无逐赔率时间戳** → 在 canonical schema 中以 `odds_timestamp = 采集惯例时点（coarse）+ evidence=notes.txt L198` 记录，resolution 标注 coarse，不得假装精确。

## 11. Lineup policy
- Baseline Dataset **不含任何 lineup**（历史 CSV 无 lineup）。
- Lineup-Enhanced Dataset：仅允许 **DATA-006 `time_safe=True`** 的实时阵容（DIAG-007 §1.2 门槛：`lineup_published_at < kickoff`），且仅 TIER_DATETIME（2019-20+）可 join（L5）。
- `lineups_all.csv`（retroactive，time_safe=False）**禁止**进入 Feature。

## 12. Cross-source join policy
- join 必须经 team normalization 字典（L5）。
- TIER_DATE_ONLY 数据**禁止**强行 DATETIME join。
- join key：`(league, canonical_home, canonical_away, kickoff_date[, kickoff_utc])`（见 team_normalization_and_registry.md）。

## 13. Known limitations（DQ 登记，不得绕过）
L1 2015-18 DATE-LEVEL ｜ L2 C=closing 为采集时点快照 ｜ L3 2015-18 无 pre/closing 区分 ｜ L4 HxG/AxG 不入核心 ｜ L5 跨源 join 需字典 + 分层。

## 14. Immutability & provenance
- 原始 55 个 canonical CSV **不可变**（SHA256 已冻结于 `manifests/sha256_manifest.json`）。
- 派生数据集每行保留 `source_file / source_row / source_hash`。
- 任何数据变化 → 新 Dataset Version，禁止静默覆盖（DATASET_FREEZE_SPEC.md）。
