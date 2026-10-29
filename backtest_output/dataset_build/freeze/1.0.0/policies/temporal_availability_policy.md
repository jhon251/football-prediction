# Temporal Availability Policy（时间可用性）

## 官方证据（football-data.co.uk notes.txt，抓取于 2026-08-23）

| 引用 | 原文关键语义 | 结论 |
|---|---|---|
| L9 | "Time = Time of match kick off" | Time 列 = 开球时间 |
| L48 | "These are for pre-closing odds. For the closing odds, as below but with an additional C character ... (e.g. B365CH = closing Bet365 home win odds)." | 非 C = pre-closing；C = closing |
| L160 | "AHh = Market size of handicap (home team) (since 2019/2020)" | 新格式（含 C/Time）始于 2019/20 |
| L198 | "Betting odds for weekend games are collected Friday afternoons, and on Tuesday afternoons for midweek games." | 赔率在周五/周二采集 → **开球前** |

URL：https://www.football-data.co.uk/notes.txt（本地存档 `backtest_output/hist_csv_audit/football_data_notes.txt`）

## 分层结论

### P0-2（赔率时间语义）→ RESOLVED
- 非 C 赔率 = **pre-closing**（赛前采集，官方 L48）
- C 后缀 = **closing**（赛前采集，官方 L48）
- 两者均周五/周二采集（官方 L198）→ **无赛后泄漏**
- 残留限制（仍 CONDITIONAL，非 SAFE）：
  1. "closing" 是**采集时点**（周五/周二）的收盘快照，非开球瞬间最后价；
  2. 2015-18 单套赔率（无 C 列）官方 notes 未区分 pre-closing/closing → 该 era 赔率统一标 CONDITIONAL（赛前采集，单一快照）。

### P0-3（2015-18 无 Time）→ RESOLVED（源数据历史限制，非缺陷）
- 官方 notes 将 Time 定义为当前列；2015-18 文件本身不含 Time（格式在 2019/20 演进，L160 佐证）。
- 决策：**不伪造时间**，采用分层：
  - **DATE-LEVEL**：2015-16 ~ 2018-19（4 季 × 5 联赛）——仅 (日期, 队名) 注册表；无 kickoff_time；无 DST 问题（无时间）。
  - **DATETIME-LEVEL**：2019-20 ~ 2025-26（7 季 × 5 联赛）——Date+Time(当地) → zoneinfo(Europe/London|Madrid|Rome|Berlin|Paris)+DST → kickoff_utc；DST 换日风险由正式 DQ 时区转换测试覆盖。
  - **2026-27**：进行中，SP126（SP1，7 场），DATETIME-LEVEL 但另行跟踪。

### 允许/禁止
- 允许：DATE-LEVEL 用于 2015-18 baseline；DATETIME-LEVEL 用于 2019-20+ 与 DATA-006 lineup join。
- 禁止：因日期相同就强行 join；为 2015-18 人为补时间；把 C 列当作"开球瞬间"价格。
