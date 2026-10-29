# DATA-005：前瞻实时首发采集实弹验证（Prospective Live Lineup Capture Validation）

> 真实世界验证：仅使用**真实即将开赛的比赛**（西甲 2026-27 首批；英超 2026-27 开赛后加入）。禁止 mock/historical replay/赛后补抓/用最终 XI 反推；历史 FINAL XI 不转换为 time_safe。本阶段不运行预测实验、不计算 ΔBrier/LogLoss/ROI、不进入 V1.3、不是 DIAG-010。

## 0. 最终判定

**分类：D: INSUFFICIENT REAL-WORLD OBSERVATION**

## 1. 采集概览

| 指标 | 值 |
| --- | --- |
| real_matches | 11 |
| matches_with_lineup | 1 |
| matches_time_safe | 1 |
| window_missed_or_not_reached | 4 |
| matches_captured_any | 5 |
| invalid_empty_xi_records_excluded | 5 |
| time_safe_match_rate | 0.0909 |
| capture_success_rate | 0.0909 |
| first_lineup_capture_rate | 1.0 |
| pre_kickoff_capture_rate | 1.0 |
| unstable_rate | 0.0 |
| duplicate_rate | 0.6471 |
| api_failure_rate | 0.002 |
| retry_recovery_rate | 0.0 |
| version_change_rate | 0.0 |
| total_versions | 1 |
| time_safe_versions | 1 |
| total_polls | 512 |

## 2. 逐场记录

| event_id | kickoff (UTC) | 状态 | versions | time_safe | polls | failures |
| --- | --- | --- | --- | --- | --- | --- |
| 401875637 | 2026-08-22T14:30:00+00:00 | captured_time_safe | 2 | 2 | 5 | 0 |
| 401876489 | 2026-08-21T18:45:00+00:00 | window_missed_or_not_reached | 0 | 0 | 128 | 0 |
| 401876490 | 2026-08-22T15:15:00+00:00 | window_reached_no_lineup | 0 | 0 | 5 | 0 |
| 401879298 | 2026-08-22T14:00:00+00:00 | captured_invalid_empty_xi | 1 | 1 | 2 | 0 |
| 401879299 | 2026-08-22T14:00:00+00:00 | captured_invalid_empty_xi | 1 | 1 | 3 | 0 |
| 401879300 | 2026-08-22T14:00:00+00:00 | captured_invalid_empty_xi | 1 | 1 | 3 | 0 |
| 401879322 | 2026-08-22T11:30:00+00:00 | captured_invalid_empty_xi | 1 | 1 | 4 | 0 |
| 401882908 | 2026-08-20T19:00:00+00:00 | window_missed_or_not_reached | 0 | 0 | 179 | 1 |
| 401882914 | 2026-08-21T19:00:00+00:00 | window_missed_or_not_reached | 0 | 0 | 133 | 0 |
| 401882916 | 2026-08-22T15:00:00+00:00 | window_reached_no_lineup | 0 | 0 | 5 | 0 |
| 401882925 | 2026-08-19T19:00:00+00:00 | window_missed_or_not_reached | 0 | 0 | 45 | 0 |

## 2.1 工程限制（如实报告）

- 本运行环境**无法保证后台任务跨回合持续运行**：两次采集会话均在环境中断时被杀（401882925、401882908 → `window_missed`，比赛在中断期间完赛，**未做赛后补抓**，不转为 time_safe）。
- 已按指令停止长时间 wait/sleep 值守；当前正在运行的两个无人值守采集会话（401882914 Betis-Sociedad 19:00Z、401876489 Marseille-Strasbourg 18:45Z）将在窗口开启后自行轮询（16:45-17:00Z 起），其结果可在下次检查时读取；本报告基于当前已确认的证据定级，不因『可能成功』而升级分类。

## 3. 质量门槛

- post_match_marked_time_safe: PASS
- kickoff_consistent: PASS
- timezone_utc: PASS
- immutable_snapshots: PASS
- version_continuity: PASS
- final_xi_source_limitation_flagged: PASS

## 4. 已知限制与问题

- KNOWN LIMITATION: ESPN provides no native publication timestamp; time_safe rests on capture-proxy evidence only

## 5. 说明

- 全部时间戳 UTC-aware；time_safe 采用严格不等式 `information_available_time < kickoff`。
- ESPN 无原生 published_at → `time_trust='capture_proxy'`，capture_time 是系统可用性证据，绝非官方发布时间。
- 若某场比赛首发首次捕获发生在 kickoff 后 → 该场 `time_safe=False`，不得补救。
- mock 与历史数据不计入；本文件只统计真实捕获。
- 总体 manifest 与 fingerprint：`backtest_output\data_005_lineup_live\MANIFEST.json`。
