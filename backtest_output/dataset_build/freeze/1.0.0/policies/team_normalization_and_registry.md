# Team Normalization Policy + Match Registry Specification

## Team Normalization Policy

1. **联赛内**（football-data 系列，11 季核心集）：零拼写变体（E0 34 / SP1 31 / I1 35 / D1 30 / F1 33 队），可直接用 raw name。
2. **跨源**需字典映射（key = 规范化名）：
   - football-data `Man United` / `Nott'm Forest` / `Ath Madrid` → canonical `Manchester United` / `Nottingham Forest` / `Atletico Madrid`
   - understat `Manchester United`、ESPN `Manchester United` → 同一 canonical
3. **2026-27 新格式缩写变体**已记录：`Ath Madrid` → `Atl. Madrid`（新文件）；`Dep. A Coruna` 等，须纳入字典。
4. **禁止合并**（同城不同俱乐部）：`Paris FC` ≠ `Paris SG`；`Ath Bilbao` ≠ `Ath Madrid` ≠ `Atl. Madrid`（后者同义）。
5. 规范化规则（不修改原始数据，仅读取层映射）：小写 → 去重音 → 去 `FC/CF/SC/AFC` 等**仅当不影响身份**（`Paris FC` vs `Paris SG` 必须保留俱乐部标识词）。
6. 升降级轮换：每季球队集合变化属正常；canonical 名不因升降级改变。

## Match Registry Specification

目标键：`(league, canonical_home, canonical_away, kickoff_date[, kickoff_time_utc])`

| 字段 | 来源 | 说明 |
|---|---|---|
| league | Div | E0/SP1/I1/D1/F1 |
| canonical_home / canonical_away | 队名字典(HomeTeam/AwayTeam) | 规范化 |
| season | Date 推断 | yyyy-yy |
| kickoff_date | Date | dd/mm/yy → date |
| kickoff_time | Time（仅 2019-20+） | HH:MM 当地 |
| kickoff_utc | Date+Time → zoneinfo | 仅 DATETIME-LEVEL |
| football_data_row_id | (league, season, HomeTeam, AwayTeam, Date) | 源行身份 |
| espn_event_id | 外部关联（可选） | 仅 DATA-006 匹配到时 |
| data006_lineup_id | event_id | 仅 time_safe=True 且 DATETIME-LEVEL 匹配 |

分层：
- 2015-18：`(league, home, away, date)` DATE-LEVEL，**不允许**用日期相同强行 join 到 DATETIME 记录。
- 2019-20+：`(league, home, away, kickoff_utc)` DATETIME-LEVEL。
- 跨源 join（lineup/xG）仅在 DATETIME-LEVEL + 队名规范化后；DATE-LEVEL 只作 baseline。
