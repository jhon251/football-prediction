# CANONICAL_SCHEMA.md（统一 canonical schema 规范）

目标：跨 2015-16~2025-26 的 schema drift，统一读取投影；**不修改 raw CSV**；缺失字段置 NULL（禁止插补/回填/猜测）；保留 provenance。

## 1. 投影结构（每行一场比赛）

| 组 | 字段 | 类型 | 来源（football-data） | 说明 |
|---|---|---|---|---|
| IDENTITY | league | str | Div | E0/SP1/I1/D1/F1 |
| | season | str | Date 推断 | yyyy-yy |
| | home_team / away_team | str | HomeTeam/AwayTeam | raw name（队名规范化见 policy，不在此层） |
| | kickoff_date | date | Date | dd/mm/yy → date |
| | kickoff_time_local | str\|NULL | Time | 仅 2019-20+；2015-18 恒 NULL |
| | kickoff_utc | datetime\|NULL | Date+Time→zoneinfo | 仅 TIER_DATETIME 构建时计算；NULL=未计算 |
| | temporal_tier | enum | 派生 | `TIER_DATE_ONLY`（2015-18）/ `TIER_DATETIME`（2019-20+） |
| RESULT | fthg / ftag | int | FTHG/FTAG | 非空（DQ 已验证） |
| | ftr | enum H/D/A | FTR | 与比分一致性已验 |
| | hthg / htag / htr | int/enum\|NULL | HTHG/HTAG/HTR | LABEL-ONLY |
| ODDS | odds_preclosing_{book}_{hda} | float\|NULL | 非 C 列 | pre-closing（官方 L48）；2015-18 无 pre/closing 区分（L3） |
| | odds_closing_{book}_{hda} | float\|NULL | C 后缀列 | closing（官方 L48）；仅 2019-20+；采集时点快照（L2） |
| | ah_line | float\|NULL | AHh（2019-20+）/BbAHh（2015-18） | 亚盘线 |
| | ah_{book}_{ha} | float\|NULL | *AHH/*AHA 族 | 亚盘价 |
| | ou25_{book}_{over,under} | float\|NULL | *>2.5/*<2.5 族 | O/U 2.5 |
| | odds_evidence | str | 常量 | `football-data notes.txt L48/L198` |
| | odds_timestamp_kind | str | 常量 | `collection_convention_coarse`（周五/周二） |
| POST-STAT | hs..ar（12 列） | int\|NULL | HS..AR | LEAKAGE-RISK：保留但**结构性禁止**入 Feature |
| META | referee | str\|NULL | Referee | 仅 E0 存在 |
| | hxg / axg | float\|NULL | HxG/AxG | 仅 2026-27；本版本**不纳入**（L4）→ 恒 NULL |
| PROVENANCE | source_file | str | 文件名 | canonical 文件名 |
| | source_path | str | 绝对路径 | canonical manifest 路径 |
| | source_row | int | 行号 | 1-based |
| | source_hash | str | 文件 SHA256 | 来自 sha256_manifest.json |
| | build_config | str | 构建配置指纹 | 见 FREEZE SPEC |

## 2. Era 投影规则（schema drift）

| Era | 特有字段投影 | 缺失处理 |
|---|---|---|
| 2015-18 | Bb*/IW/WH/VC/LB；无 Time；无 C 后缀；无 Avg/Max | 缺失列 → NULL；tier=DATE_ONLY |
| 2018-19 | 同上去 LB | 同上 |
| 2019-24 | Time/Avg/Max/BFD；无 Bb* | Bb* 族 → NULL |
| 2024-25 | +CL/BV/BMGM；无 IW/VC | IW/VC → NULL |
| 2025-26 | +C 后缀全族 | — |
| 2026-27 | +HxG/AxG（另册） | 不纳入本版本 |

规则：字段家族按官方 notes.txt 定义映射；**任何列无官方定义（如 2026-27 HxG/AxG）→ 不入 canonical 核心**。

## 3. 与既有生产 schema 的对齐（不修改生产代码）

- 既有 `HistoricalMatch`（src/.../schema.py）字段语义与本规范一致（odds/lineup tri-state/result 分离/provenance）。
- 本 canonical schema 是**数据集层投影**；生产层导入时：
  - non-C 列 → `raw_odds` + `odds_semantics_note="pre-closing (notes L48)"`；C 列 → `closing_odds(kind=closing, odds_timestamp=采集惯例时点 coarse)`。
  - `odds_timestamp` 强制要求（V1.2 规则 #8）以"采集惯例时点（周五/周二 12:00 当地，最近一个早于 kickoff 的采集日）"满足，并标注 `resolution=coarse, evidence=notes.txt L198` —— **不得冒充精确时间戳**。
  - tier 信息由数据集层 wrapper 携带（生产 schema 无 tier 字段，**不改生产代码**）。
- 禁止猜测：任何无法从源文件读出的值一律 NULL。

## 4. 校验门（build 时逐行执行）

1. 行 ∈ canonical manifest（按 source_hash 校验文件未变）
2. 身份/比分非空（basicQC 已过 19,763）
3. 赔率 >1.0 且非空（否则 NULL，不算错）
4. tier 与 season 一致（2015-18 ⇒ DATE_ONLY）
5. 尾部空行剔除（I115/F115 各 1）
6. 输出行数与 19,763 一致（不一致 → STOP 报告）
