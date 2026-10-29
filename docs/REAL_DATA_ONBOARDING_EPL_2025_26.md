# REAL DATA ONBOARDING: 英超 2025-26 赛季（E0.csv）

> 本文件由 `scripts/v12_generate_onboarding_doc.py` 从**真实原始文件**自动生成（字段名、示例值全部取自文件本身，非记忆）。
> 本阶段只做数据接入与审计：**不运行任何预测、不修改任何核心预测逻辑**。

## 0. 数据概览

- 文件：`data\historical\raw\E0.csv`（已复制入 `data/historical/raw/E0.csv`）
- 数据规模：**380 场比赛 / 132 个字段**
- 日期范围：2025-08-15 → 2026-05-24（282 天，完整赛季）
- 球队数量：**20 支**，每队恰好 38 场（完整双循环）
- 重复比赛：0
- 缺失值：核心 24 字段 **0 缺失**；56 个赔率/辅助字段存在博彩公司覆盖缺口（PS/Pinnacle 缺 170/380，CL 缺 98/380，LB 缺 94/380 等）
- 一致性：HT≤FT 全部成立；FTR/HTR 与比分全部一致；射正≤射门全部成立；赔率全部 >1.0 且无非法值
- 数据性质：**真实数据**（无合成标记，内部 schema `is_synthetic=false`）

## 1. Doctor 输出

```
Football Data Doctor
====================
schema: PASS
  132 fields, all 24 core fields present; 380 rows
missing data: PASS
  core fields complete; 56 odds/aux columns have partial bookmaker coverage (max 170 missing)
duplicate data: PASS
  0 duplicate matches
date validity: PASS
  2025-08-15 .. 2026-05-24 (282 days, valid EPL season span)
team consistency: PASS
  20 teams x 38 matches (balanced double round-robin)
odds validity: PASS
  106 odds fields, all values > 1.0 where present, no non-numeric values
temporal validity: PASS
  HT<=FT for every match; FTR/HTR codes agree with goals; shots>=shots-on-target
leakage risks: PASS
  identified risks: C-suffix semantics UNKNOWN, no odds timestamps, result fields co-located; all handled by the import/snapshot layer, none silently
synthetic flag: PASS
  file carries no synthetic label; treated as REAL data (is_synthetic=false in the internal schema)
xg policy: PASS
  no xG columns in the file; xG stays MISSING (no fake xG will be constructed)
real data status: PASS
  REAL EPL 2025-26 data (380 matches); onboarding gate 'historical_data' = ONBOARDED for this file; formal backtesting still NOT run in this phase
====================
Warnings:
  - bookmaker coverage gap: PSH missing 170/380
  - bookmaker coverage gap: PSD missing 170/380
  - bookmaker coverage gap: PSA missing 170/380
  - bookmaker coverage gap: P>2.5 missing 170/380
  - bookmaker coverage gap: P<2.5 missing 170/380
  - bookmaker coverage gap: PAHH missing 170/380
  - bookmaker coverage gap: PAHA missing 170/380
  - bookmaker coverage gap: PSCH missing 170/380
  - 54 C-suffix odds columns exist; their opening/closing semantics CANNOT be verified from the file (overround analysis inconclusive) -> treated as time-semantics UNKNOWN and excluded from closing/opening mapping (principle 5)
  - no per-odds timestamps in the file: every odds column must be treated as a single pre-kickoff snapshot at the source's convention (closing), never as an intraday series
  - result fields (FTHG..AR) share the file with pre-match fields: the import layer structurally separates them; features must only use matches with date < kickoff (time-travel test enforces this)

Real Data Status:
  is_synthetic = false (real CSV, no synthetic label; source-convention real data)
  REAL_DATA_READY gate 'historical_data': ONBOARDED (raw file + profile + field dictionary)

REAL DATA ONBOARDING PASS
```

## 2. 七条原则在本文件上的落实

| 原则 | 落实方式 |
| --- | --- |
| P1 结果字段不得作为本场赛前输入 | FTHG/FTAG/FTR/HTHG/HTAG/HTR/HS/AS/HST/AST/HF/AF/HC/AC/HY/AY/HR/AR 全部归入赛后区，导入层结构性隔离 |
| P2 允许历史聚合 | 仅 `observed_at < kickoff` 的历史比赛可生成特征（时间旅行测试位一致保证） |
| P3 不得使用未来比赛 | walk-forward 特征函数只读 `date < kickoff`；审计 Future Match Leakage PASS |
| P4/P5 开收盘严格区分，不猜测 | 文件**不含逐赔率时间戳**：普通列按来源惯例标记 `closing_convention_pre_kickoff`（盖章=开球时刻）；**54 个 C 后缀列无法从文件证实开/收盘语义（overround 分析双向不一致）→ 标记 `unknown_time_semantics`，不映射进 closing/opening**；opening_odds 保持 None |
| P6 不得复制赛后字段为赛前特征 | 导入层把结果字段写入赛后区；特征函数只接受赛后区之外的输入 |
| P7 不伪造 xG | 本文件**没有 xG 列** → xG 保持缺失，不构造任何公式生成 |

## 3. 赔率时间语义结论（重要）

- 本文件同时含普通赔率列与 **C 后缀列**（B365C*/BFDC*/.../MaxC*/AvgC*/BFEC* 等共 54 列）。
- 用 overround 收敛性检验（收盘市场通常比开盘市场抽水更低）实测结果**双向不一致**：PS(-0.0059)/Max(-0.0039)/BV(-0.0063) 的 C 列更紧，而 B365(+0.0008)/BMGM(+0.0009)/BW(+0.0008) 的 C 列略宽 → **无法从文件本身判定 C 列是开盘还是收盘**。
- 结论（原则 5）：C 后缀列一律 `UNKNOWN` 时间语义，**只保留原文、不进入任何建模映射**；closing_odds 只取普通 Avg 列（跨公司平均，来源惯例=赛前收盘快照，盖章=开球时刻），opening_odds=无（不存在可验证的开盘快照）。

## 4. 完整字段字典（132 个字段）

| # | 原始字段名 | 含义 | 数据类型 | 示例值 | 是否比赛结果 | 是否赛后数据 | 是否赔率 | 是否可用于赛前预测 | 时间语义风险 | 是否需要转换 | 对应 InternalSchema |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `Div` | division/league code (E0 = English Premier League) | string | `E0` | 否 | 否 | 否 | YES (match identity) | NONE | 否 | competition |
| 2 | `Date` | match date dd/mm/yyyy | date | `15/08/2025` | 否 | 否 | 否 | YES (match identity) | NONE | 是 | date (with Time) |
| 3 | `Time` | kickoff time HH:MM (UK) | time | `20:00` | 否 | 否 | 否 | YES (match identity) | NONE | 是 | date (with Date) |
| 4 | `HomeTeam` | home team name | string | `Liverpool` | 否 | 否 | 否 | YES (match identity) | NONE | 否 | home_team |
| 5 | `AwayTeam` | away team name | string | `Bournemouth` | 否 | 否 | 否 | YES (match identity) | NONE | 否 | away_team |
| 6 | `FTHG` | full-time home goals | int | `4` | 是 | 是 | 否 | NO for this match (principle 1); YES only as historical aggregates of past matches (principle 2) | NONE (structurally excluded from pre-match inputs) | 是 | home_goals (result) |
| 7 | `FTAG` | full-time away goals | int | `2` | 是 | 是 | 否 | NO for this match (principle 1); YES only as historical aggregates of past matches (principle 2) | NONE (structurally excluded from pre-match inputs) | 是 | away_goals (result) |
| 8 | `FTR` | full-time result code H/D/A | enum | `H` | 是 | 是 | 否 | NO for this match (principle 1); YES only as historical aggregates of past matches (principle 2) | NONE (structurally excluded from pre-match inputs) | 是 | derived result; validated against goals |
| 9 | `HTHG` | half-time home goals | int | `1` | 是 | 是 | 否 | NO for this match (principle 1); YES only as historical aggregates of past matches (principle 2) | NONE (structurally excluded from pre-match inputs) | 是 | half_time_home_goals (result) |
| 10 | `HTAG` | half-time away goals | int | `0` | 是 | 是 | 否 | NO for this match (principle 1); YES only as historical aggregates of past matches (principle 2) | NONE (structurally excluded from pre-match inputs) | 是 | half_time_away_goals (result) |
| 11 | `HTR` | half-time result code H/D/A | enum | `H` | 是 | 是 | 否 | NO for this match (principle 1); YES only as historical aggregates of past matches (principle 2) | NONE (structurally excluded from pre-match inputs) | 是 | validated against HT goals |
| 12 | `Referee` | match referee name | string | `A Taylor` | 否 | 否 | 否 | YES (appointment name; tendency data NO_SIGNAL) | LOW | 否 | referee |
| 13 | `HS` | home shots | int | `19` | 是 | 是 | 否 | NO for this match (principle 1); YES only as historical aggregates of past matches (principle 2) | NONE (structurally excluded from pre-match inputs) | 是 | home_shots (result) |
| 14 | `AS` | away shots | int | `10` | 是 | 是 | 否 | NO for this match (principle 1); YES only as historical aggregates of past matches (principle 2) | NONE (structurally excluded from pre-match inputs) | 是 | away_shots (result) |
| 15 | `HST` | home shots on target | int | `10` | 是 | 是 | 否 | NO for this match (principle 1); YES only as historical aggregates of past matches (principle 2) | NONE (structurally excluded from pre-match inputs) | 是 | home_shots_on_target (result) |
| 16 | `AST` | away shots on target | int | `3` | 是 | 是 | 否 | NO for this match (principle 1); YES only as historical aggregates of past matches (principle 2) | NONE (structurally excluded from pre-match inputs) | 是 | away_shots_on_target (result) |
| 17 | `HF` | home fouls | int | `7` | 是 | 是 | 否 | NO for this match (principle 1); YES only as historical aggregates of past matches (principle 2) | NONE (structurally excluded from pre-match inputs) | 是 | home_fouls (result) |
| 18 | `AF` | away fouls | int | `10` | 是 | 是 | 否 | NO for this match (principle 1); YES only as historical aggregates of past matches (principle 2) | NONE (structurally excluded from pre-match inputs) | 是 | away_fouls (result) |
| 19 | `HC` | home corners | int | `6` | 是 | 是 | 否 | NO for this match (principle 1); YES only as historical aggregates of past matches (principle 2) | NONE (structurally excluded from pre-match inputs) | 是 | home_corners (result) |
| 20 | `AC` | away corners | int | `7` | 是 | 是 | 否 | NO for this match (principle 1); YES only as historical aggregates of past matches (principle 2) | NONE (structurally excluded from pre-match inputs) | 是 | away_corners (result) |
| 21 | `HY` | home yellow cards | int | `1` | 是 | 是 | 否 | NO for this match (principle 1); YES only as historical aggregates of past matches (principle 2) | NONE (structurally excluded from pre-match inputs) | 是 | home_yellow_cards (result) |
| 22 | `AY` | away yellow cards | int | `2` | 是 | 是 | 否 | NO for this match (principle 1); YES only as historical aggregates of past matches (principle 2) | NONE (structurally excluded from pre-match inputs) | 是 | away_yellow_cards (result) |
| 23 | `HR` | home red cards | int | `0` | 是 | 是 | 否 | NO for this match (principle 1); YES only as historical aggregates of past matches (principle 2) | NONE (structurally excluded from pre-match inputs) | 是 | home_red_cards (result) |
| 24 | `AR` | away red cards | int | `0` | 是 | 是 | 否 | NO for this match (principle 1); YES only as historical aggregates of past matches (principle 2) | NONE (structurally excluded from pre-match inputs) | 是 | away_red_cards (result) |
| 25 | `B365H` | Bet365 1X2 odds (decimal) - home | float | `1.3` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[B365H] |
| 26 | `B365D` | Bet365 1X2 odds (decimal) - draw | float | `6` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[B365D] |
| 27 | `B365A` | Bet365 1X2 odds (decimal) - away | float | `8.5` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[B365A] |
| 28 | `BFDH` | BFD odds (source code; product expansion unverified - possibly a Betfair decimal feed) - home | float | `1.3` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[BFDH] |
| 29 | `BFDD` | BFD odds (source code; product expansion unverified - possibly a Betfair decimal feed) - draw | float | `6` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[BFDD] |
| 30 | `BFDA` | BFD odds (source code; product expansion unverified - possibly a Betfair decimal feed) - away | float | `9.5` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[BFDA] |
| 31 | `BMGMH` | BMGM odds (source code; likely BetMGM - expansion unverified) - home | float | `1.29` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[BMGMH] |
| 32 | `BMGMD` | BMGM odds (source code; likely BetMGM - expansion unverified) - draw | float | `6.5` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[BMGMD] |
| 33 | `BMGMA` | BMGM odds (source code; likely BetMGM - expansion unverified) - away | float | `9` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[BMGMA] |
| 34 | `BVH` | BV odds (source code; likely BetVictor - expansion unverified) - home | float | `1.3` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[BVH] |
| 35 | `BVD` | BV odds (source code; likely BetVictor - expansion unverified) - draw | float | `6` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[BVD] |
| 36 | `BVA` | BV odds (source code; likely BetVictor - expansion unverified) - away | float | `8.5` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[BVA] |
| 37 | `BWH` | Bet&Win 1X2 odds (decimal) - home | float | `1.32` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[BWH] |
| 38 | `BWD` | Bet&Win 1X2 odds (decimal) - draw | float | `5.5` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[BWD] |
| 39 | `BWA` | Bet&Win 1X2 odds (decimal) - away | float | `7.5` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[BWA] |
| 40 | `CLH` | CL odds (source code; likely Coral/Ladbrokes family - expansion unverified) - home | float | `1.33` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[CLH] |
| 41 | `CLD` | CL odds (source code; likely Coral/Ladbrokes family - expansion unverified) - draw | float | `5.75` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[CLD] |
| 42 | `CLA` | CL odds (source code; likely Coral/Ladbrokes family - expansion unverified) - away | float | `8` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[CLA] |
| 43 | `LBH` | Ladbrokes 1X2 odds (decimal) - home | float | `1.33` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[LBH] |
| 44 | `LBD` | Ladbrokes 1X2 odds (decimal) - draw | float | `5.75` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[LBD] |
| 45 | `LBA` | Ladbrokes 1X2 odds (decimal) - away | float | `7.5` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[LBA] |
| 46 | `PSH` | Pinnacle 1X2 odds (decimal) - home | float | `1.28` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[PSH] |
| 47 | `PSD` | Pinnacle 1X2 odds (decimal) - draw | float | `6.56` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[PSD] |
| 48 | `PSA` | Pinnacle 1X2 odds (decimal) - away | float | `9.07` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[PSA] |
| 49 | `MaxH` | maximum 1X2 odds across covered bookmakers - home | float | `1.34` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[MaxH] |
| 50 | `MaxD` | maximum 1X2 odds across covered bookmakers - draw | float | `6.5` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[MaxD] |
| 51 | `MaxA` | maximum 1X2 odds across covered bookmakers - away | float | `9.5` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[MaxA] |
| 52 | `AvgH` | average 1X2 odds across covered bookmakers - home | float | `1.31` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[AvgH] |
| 53 | `AvgD` | average 1X2 odds across covered bookmakers - draw | float | `5.96` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[AvgD] |
| 54 | `AvgA` | average 1X2 odds across covered bookmakers - away | float | `8.31` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[AvgA] |
| 55 | `BFEH` | Betfair Exchange 1X2 odds (decimal) - home | float | `1.34` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[BFEH] |
| 56 | `BFED` | Betfair Exchange 1X2 odds (decimal) - draw | float | `6.6` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[BFED] |
| 57 | `BFEA` | Betfair Exchange 1X2 odds (decimal) - away | float | `9.4` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[BFEA] |
| 58 | `B365>2.5` | Bet365 over 2.5 goals odds | float | `1.36` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[B365>2.5] |
| 59 | `B365<2.5` | Bet365 under 2.5 goals odds | float | `3.2` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[B365<2.5] |
| 60 | `P>2.5` | Pinnacle over 2.5 goals odds | float | `1.37` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[P>2.5] |
| 61 | `P<2.5` | Pinnacle under 2.5 goals odds | float | `3.26` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[P<2.5] |
| 62 | `Max>2.5` | max across books over 2.5 goals odds | float | `1.38` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[Max>2.5] |
| 63 | `Max<2.5` | max across books under 2.5 goals odds | float | `3.3` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[Max<2.5] |
| 64 | `Avg>2.5` | average across books over 2.5 goals odds | float | `1.35` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[Avg>2.5] |
| 65 | `Avg<2.5` | average across books under 2.5 goals odds | float | `3.13` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[Avg<2.5] |
| 66 | `BFE>2.5` | Betfair Exchange over 2.5 goals odds | float | `1.4` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[BFE>2.5] |
| 67 | `BFE<2.5` | Betfair Exchange under 2.5 goals odds | float | `3.4` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[BFE<2.5] |
| 68 | `AHh` | Asian Handicap line for home team (goals, can be negative) | float | `-1.5` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[AH line] |
| 69 | `B365AHH` | Bet365 Asian Handicap home price | float | `1.83` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[B365AHH] |
| 70 | `B365AHA` | Bet365 Asian Handicap away price | float | `2.03` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[B365AHA] |
| 71 | `PAHH` | Pinnacle Asian Handicap home price | float | `1.9` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[PAHH] |
| 72 | `PAHA` | Pinnacle Asian Handicap away price | float | `2.03` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[PAHA] |
| 73 | `MaxAHH` | max across books Asian Handicap home price | float | `1.83` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[MaxAHH] |
| 74 | `MaxAHA` | max across books Asian Handicap away price | float | `2.06` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[MaxAHA] |
| 75 | `AvgAHH` | average across books Asian Handicap home price | float | `1.78` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[AvgAHH] |
| 76 | `AvgAHA` | average across books Asian Handicap away price | float | `1.99` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[AvgAHA] |
| 77 | `BFEAHH` | Betfair Exchange Asian Handicap home price | float | `1.9` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[BFEAHH] |
| 78 | `BFEAHA` | Betfair Exchange Asian Handicap away price | float | `2.08` | 否 | 否 | 是 | YES as market baseline (closing-convention snapshot stamped at kickoff) | MEDIUM (no per-odds timestamp in file; single-snapshot assumption) | 是 | raw_odds[BFEAHA] |
| 79 | `B365CH` | Bet365 1X2 odds (decimal) (C-suffix snapshot) - home | float | `1.29` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[B365CH] (time_semantics unknown) |
| 80 | `B365CD` | Bet365 1X2 odds (decimal) (C-suffix snapshot) - draw | float | `6.25` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[B365CD] (time_semantics unknown) |
| 81 | `B365CA` | Bet365 1X2 odds (decimal) (C-suffix snapshot) - away | float | `9` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[B365CA] (time_semantics unknown) |
| 82 | `BFDCH` | BFD odds (source code; product expansion unverified - possibly a Betfair decimal feed) (C-suffix snapshot) - home | float | `1.3` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[BFDCH] (time_semantics unknown) |
| 83 | `BFDCD` | BFD odds (source code; product expansion unverified - possibly a Betfair decimal feed) (C-suffix snapshot) - draw | float | `6` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[BFDCD] (time_semantics unknown) |
| 84 | `BFDCA` | BFD odds (source code; product expansion unverified - possibly a Betfair decimal feed) (C-suffix snapshot) - away | float | `9.5` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[BFDCA] (time_semantics unknown) |
| 85 | `BMGMCH` | BMGM odds (source code; likely BetMGM - expansion unverified) (C-suffix snapshot) - home | float | `1.3` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[BMGMCH] (time_semantics unknown) |
| 86 | `BMGMCD` | BMGM odds (source code; likely BetMGM - expansion unverified) (C-suffix snapshot) - draw | float | `6.25` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[BMGMCD] (time_semantics unknown) |
| 87 | `BMGMCA` | BMGM odds (source code; likely BetMGM - expansion unverified) (C-suffix snapshot) - away | float | `9` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[BMGMCA] (time_semantics unknown) |
| 88 | `BVCH` | BV odds (source code; likely BetVictor - expansion unverified) (C-suffix snapshot) - home | float | `1.29` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[BVCH] (time_semantics unknown) |
| 89 | `BVCD` | BV odds (source code; likely BetVictor - expansion unverified) (C-suffix snapshot) - draw | float | `6` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[BVCD] (time_semantics unknown) |
| 90 | `BVCA` | BV odds (source code; likely BetVictor - expansion unverified) (C-suffix snapshot) - away | float | `9` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[BVCA] (time_semantics unknown) |
| 91 | `BWCH` | Bet&Win 1X2 odds (decimal) (C-suffix snapshot) - home | float | `1.31` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[BWCH] (time_semantics unknown) |
| 92 | `BWCD` | Bet&Win 1X2 odds (decimal) (C-suffix snapshot) - draw | float | `5.75` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[BWCD] (time_semantics unknown) |
| 93 | `BWCA` | Bet&Win 1X2 odds (decimal) (C-suffix snapshot) - away | float | `8` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[BWCA] (time_semantics unknown) |
| 94 | `CLCH` | CL odds (source code; likely Coral/Ladbrokes family - expansion unverified) (C-suffix snapshot) - home | float | `1.3` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[CLCH] (time_semantics unknown) |
| 95 | `CLCD` | CL odds (source code; likely Coral/Ladbrokes family - expansion unverified) (C-suffix snapshot) - draw | float | `6` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[CLCD] (time_semantics unknown) |
| 96 | `CLCA` | CL odds (source code; likely Coral/Ladbrokes family - expansion unverified) (C-suffix snapshot) - away | float | `8` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[CLCA] (time_semantics unknown) |
| 97 | `LBCH` | Ladbrokes 1X2 odds (decimal) (C-suffix snapshot) - home | float | `1.3` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[LBCH] (time_semantics unknown) |
| 98 | `LBCD` | Ladbrokes 1X2 odds (decimal) (C-suffix snapshot) - draw | float | `5.75` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[LBCD] (time_semantics unknown) |
| 99 | `LBCA` | Ladbrokes 1X2 odds (decimal) (C-suffix snapshot) - away | float | `8` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[LBCA] (time_semantics unknown) |
| 100 | `PSCH` | Pinnacle 1X2 odds (decimal) (C-suffix snapshot) - home | float | `1.29` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[PSCH] (time_semantics unknown) |
| 101 | `PSCD` | Pinnacle 1X2 odds (decimal) (C-suffix snapshot) - draw | float | `6.55` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[PSCD] (time_semantics unknown) |
| 102 | `PSCA` | Pinnacle 1X2 odds (decimal) (C-suffix snapshot) - away | float | `9.75` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[PSCA] (time_semantics unknown) |
| 103 | `MaxCH` | maximum 1X2 odds across covered bookmakers (C-suffix snapshot) - home | float | `1.31` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[MaxCH] (time_semantics unknown) |
| 104 | `MaxCD` | maximum 1X2 odds across covered bookmakers (C-suffix snapshot) - draw | float | `6.6` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[MaxCD] (time_semantics unknown) |
| 105 | `MaxCA` | maximum 1X2 odds across covered bookmakers (C-suffix snapshot) - away | float | `9.5` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[MaxCA] (time_semantics unknown) |
| 106 | `AvgCH` | average 1X2 odds across covered bookmakers (C-suffix snapshot) - home | float | `1.29` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[AvgCH] (time_semantics unknown) |
| 107 | `AvgCD` | average 1X2 odds across covered bookmakers (C-suffix snapshot) - draw | float | `6.02` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[AvgCD] (time_semantics unknown) |
| 108 | `AvgCA` | average 1X2 odds across covered bookmakers (C-suffix snapshot) - away | float | `8.68` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[AvgCA] (time_semantics unknown) |
| 109 | `BFECH` | Betfair Exchange 1X2 odds (decimal) (C-suffix snapshot) - home | float | `1.32` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[BFECH] (time_semantics unknown) |
| 110 | `BFECD` | Betfair Exchange 1X2 odds (decimal) (C-suffix snapshot) - draw | float | `6.8` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[BFECD] (time_semantics unknown) |
| 111 | `BFECA` | Betfair Exchange 1X2 odds (decimal) (C-suffix snapshot) - away | float | `10` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[BFECA] (time_semantics unknown) |
| 112 | `B365C>2.5` | Bet365 over 2.5 goals odds (C-suffix snapshot) | float | `1.36` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[B365C>2.5] (time_semantics unknown) |
| 113 | `B365C<2.5` | Bet365 under 2.5 goals odds (C-suffix snapshot) | float | `3.2` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[B365C<2.5] (time_semantics unknown) |
| 114 | `PC>2.5` | Pinnacle over 2.5 goals odds (C-suffix snapshot) | float | `1.41` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[PC>2.5] (time_semantics unknown) |
| 115 | `PC<2.5` | Pinnacle under 2.5 goals odds (C-suffix snapshot) | float | `2.95` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[PC<2.5] (time_semantics unknown) |
| 116 | `MaxC>2.5` | max across books over 2.5 goals odds (C-suffix snapshot) | float | `1.4` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[MaxC>2.5] (time_semantics unknown) |
| 117 | `MaxC<2.5` | max across books under 2.5 goals odds (C-suffix snapshot) | float | `3.2` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[MaxC<2.5] (time_semantics unknown) |
| 118 | `AvgC>2.5` | average across books over 2.5 goals odds (C-suffix snapshot) | float | `1.36` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[AvgC>2.5] (time_semantics unknown) |
| 119 | `AvgC<2.5` | average across books under 2.5 goals odds (C-suffix snapshot) | float | `3.05` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[AvgC<2.5] (time_semantics unknown) |
| 120 | `BFEC>2.5` | Betfair Exchange over 2.5 goals odds (C-suffix snapshot) | float | `1.41` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[BFEC>2.5] (time_semantics unknown) |
| 121 | `BFEC<2.5` | Betfair Exchange under 2.5 goals odds (C-suffix snapshot) | float | `3.4` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[BFEC<2.5] (time_semantics unknown) |
| 122 | `AHCh` | Asian Handicap line (C-suffix snapshot) | float | `-1.75` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[AHCh] (time_semantics unknown) |
| 123 | `B365CAHH` | Bet365 Asian Handicap home price (C-suffix snapshot) | float | `2.03` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[B365CAHH] (time_semantics unknown) |
| 124 | `B365CAHA` | Bet365 Asian Handicap away price (C-suffix snapshot) | float | `1.78` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[B365CAHA] (time_semantics unknown) |
| 125 | `PCAHH` | Pinnacle Asian Handicap home price (C-suffix snapshot) | float | `2.07` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[PCAHH] (time_semantics unknown) |
| 126 | `PCAHA` | Pinnacle Asian Handicap away price (C-suffix snapshot) | float | `1.85` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[PCAHA] (time_semantics unknown) |
| 127 | `MaxCAHH` | max across books Asian Handicap home price (C-suffix snapshot) | float | `2.03` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[MaxCAHH] (time_semantics unknown) |
| 128 | `MaxCAHA` | max across books Asian Handicap away price (C-suffix snapshot) | float | `1.88` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[MaxCAHA] (time_semantics unknown) |
| 129 | `AvgCAHH` | average across books Asian Handicap home price (C-suffix snapshot) | float | `1.94` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[AvgCAHH] (time_semantics unknown) |
| 130 | `AvgCAHA` | average across books Asian Handicap away price (C-suffix snapshot) | float | `1.76` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[AvgCAHA] (time_semantics unknown) |
| 131 | `BFECAHH` | Betfair Exchange Asian Handicap home price (C-suffix snapshot) | float | `2.14` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[BFECAHH] (time_semantics unknown) |
| 132 | `BFECAHA` | Betfair Exchange Asian Handicap away price (C-suffix snapshot) | float | `1.86` | 否 | 否 | 是 | NO - time semantics UNKNOWN (principle 5); excluded until source documentation confirms | HIGH (cannot verify opening vs closing from the file) | 是 | raw_odds[BFECAHA] (time_semantics unknown) |

## 5. 导入产物

- 原始文件：`data/historical/raw/E0.csv`（203,438 字节，未修改）
- 规范数据集：`data/historical/epl_2025_26.json`（380 条 `HistoricalMatch`，`is_synthetic=false`，`source='football-data.co.uk E0 2025-26 (real)'`）
- 每条记录：结果字段与赛前字段结构性分离；closing_odds=Avg（惯例标注）；108 个原始赔率字段逐字保留并打时间语义标签（54 个 UNKNOWN）；xG 保持缺失。
- 泄漏审计（真实数据上运行）：**7/7 PASS**（含 380 场时间旅行位一致测试）。

## 6. 最终判定

**REAL DATA ONBOARDING PASS**

后续（本阶段不做）：正式回测需先补充 C 后缀列的开/收盘官方文档、确认每列赔率的精确抓取时间，然后才能决定哪些列可进入市场基准。
