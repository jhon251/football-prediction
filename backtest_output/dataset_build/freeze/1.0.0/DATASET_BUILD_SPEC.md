# DATASET_BUILD_SPEC.md（构建规范：Baseline + Lineup-Enhanced）

## 0. 总则
- 唯一输入 = DQ canonical manifest（`manifests/canonical_manifest.json` + `sha256_manifest.json`）。
- 原始 CSV 不可变；构建只**读取** + 产出派生文件（下一阶段授权后执行）。
- 每一步都有校验门；任一校验失败 → **STOP 并报告**，不得自行修复。

## 1. 构建流水线（五阶段）

```
S1 验证输入     : 逐文件 sha256(磁盘) == manifest 值 → 55/55 一致
S2 逐行投影     : 按 CANONICAL_SCHEMA 投影 + 行级 provenance
S3 质检门       : 19,763 行；FTR 一致 0 错误；赔率 >1.0；空行剔除 2
S4 分层标注     : tier = DATE_ONLY(2015-18) / DATETIME(2019-20+)
S5 写产物       : baseline.parquet/jsonl + build manifest（freeze）
```

## 2. Temporal Tiers（PHASE 3 正式定义）

| tier | 赛季 | kickoff 表示 | 允许 | 禁止 |
|---|---|---|---|---|
| `TIER_DATE_ONLY` | 2015-16~2018-19（4 季×5 联赛） | `kickoff_date`（无 time） | baseline 特征（日期级）、Label | 伪造 kickoff_time；join DATETIME；用 DATA-006 补历史时间 |
| `TIER_DATETIME` | 2019-20~2025-26（7 季×5 联赛） | `kickoff_utc`（zoneinfo 转换） | baseline + 未来 lineup join | 未经时区测试的 utc 值 |

规则：任何"用其他来源时间覆盖原始 Football-Data 时间"的操作必须留下 provenance 记录；未记录 = 违规。

## 3. Safe Baseline Dataset（PHASE 5 设计）

- 范围：tier BOTH（19,763 行）
- 字段（仅 registry 中 allowed=YES 且非 CONDITIONAL 的 SAFE 部分 + Label）：
  - identity：league/season/home_team/away_team/kickoff_date(/time/utc by tier)
  - feature-eligible：**日期级身份 + 赔率（CONDITIONAL 带证据标签）**——本阶段不生成复杂派生特征（"不做正式特征工程"）
  - label：fthg/ftag/ftr
- 明确**不含**：赛后统计 12 列、HxG/AxG、任何 lineup、半场比分（Label-only 保留但不入 Feature）
- 不依赖 DATA-006；不依赖 DATE→DATETIME 强 join

## 4. Lineup-Enhanced Dataset（PHASE 6 设计，仅规格）

```
Baseline（TIER_DATETIME 子集，2019-20+）
+ DATA-006 time_safe=True lineup（实时捕获）
= Lineup-Enhanced
```
- join key：`(league, canonical_home, canonical_away, kickoff_utc)` —— 必须经 team normalization 字典；DATE_ONLY 行**不参与**。
- lineup 准入条件：`time_safe=True`（即 information_available_time < kickoff，STRICT）。
- missing lineup policy：无匹配 lineup → 该行 lineup 特征 = NULL（DIAG-007 回退规则，禁止插补）。
- partial lineup policy：任一方 xi<11 → 该方 lineup 特征 = NULL 并标 `partial_lineup`（沿用 DATA-006 的 P0-1 防护语义）。
- capture status policy：`lineup_captured`（开球前）可用；`post_kickoff_final_xi`/`window_missed` → 不可用作赛前特征。
- 现在**不导入** DATA-006 数据；仅为规格。

## 5. 产出物（build 后）
1. `baseline_dataset.jsonl`（+ 压缩副本）
2. `baseline_build_manifest.json`（见 FREEZE SPEC）
3. `tier_summary.json`（DATE_ONLY/DATETIME 行数、赔率覆盖率、NULL 统计）
4. `build_log.txt`（每阶段校验结果，append-only）

## 6. 回滚/一致性
- 任何阶段产物带 build 配置指纹；重跑必须逐字节一致（确定性构建）。
- 输入 manifest 变化 → 新 Dataset Version，不覆盖旧产物。
