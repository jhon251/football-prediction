# FEATURE_AVAILABILITY_REGISTRY.md（字段级可用性注册表）

来源：官方 notes.txt + DQ 审计。`allowed_for_training` 只表示"字段层面允许"，实际进入特征仍需 temporal policy 与 snapshot 构建器（observed_at < kickoff）双重把关。

| field | source | season_range | availability_tier | temporal_resolution | leakage_class | allowed_for_training | notes |
|---|---|---|---|---|---|---|---|
| league(Div) | football-data | 2015-26 | BOTH | exact | SAFE | YES | — |
| season | 派生(Date) | 2015-26 | BOTH | exact | SAFE | YES | yyyy-yy |
| date | Date | 2015-26 | BOTH | day | SAFE | YES | dd/mm/yy |
| time | Time | 2019-26 | DATETIME | minute(当地) | SAFE | YES（仅 TIER_DATETIME） | 2015-18 缺失，**不伪造** |
| kickoff_utc | Date+Time→zoneinfo | 2019-26 | DATETIME | minute(UTC) | SAFE | YES（仅 TIER_DATETIME） | DST 转换须先过测试 |
| home_team / away_team | HomeTeam/AwayTeam | 2015-26 | BOTH | exact | SAFE | YES | 规范化走字典（L5） |
| referee | Referee | 2015-26(仅E0) | BOTH | exact | SAFE | YES（E0 only） | 其余联赛 NULL |
| fthg/ftag/ftr | FTHG/FTAG/FTR | 2015-26 | BOTH | exact | LABEL | 仅 Label | 一致性已验 |
| hthg/htag/htr | HTHG/HTAG/HTR | 2015-26 | BOTH | exact | LABEL-ONLY | 仅 Label/事后 | 半场=赛中 |
| hs/as/hst/ast | HS/AS/HST/AST | 2015-26 | BOTH | exact | LEAKAGE-RISK | **NO** | 全场赛后统计 |
| hf/af/hc/ac/hy/ay/hr/ar | 同上 | 2015-26 | BOTH | exact | LEAKAGE-RISK | **NO** | 同上（历史聚合需 observed_at<kickoff） |
| odds non-C（B365*/BW*/IW*/PS*/WH*/VC*/Bb*/BFD*/CL*/LB*/BMGM*/BV*/BFE*） | 各家 | 各 era（见 schema policy） | BOTH | 采集时点（周五/周二, coarse） | CONDITIONAL | YES（带证据） | 官方=pre-closing（L48）；2015-18 无 pre/closing 区分（L3） |
| odds Max*/Avg*（非 C） | 市场聚合 | 2019-26 | DATETIME | coarse | CONDITIONAL | YES（带证据） | 2019-20+ 才存在 |
| odds C 后缀（*C* 全族） | 各家收盘 | 2019-26 | DATETIME | coarse | CONDITIONAL | YES（带证据，标 L2） | 官方=closing（L48）；**采集时点收盘快照，非 kickoff 瞬间** |
| ah_line（AHh/BbAHh） | 市场 | 2015-26 | BOTH | exact | CONDITIONAL | YES | 2015-18 用 BbAHh |
| ah prices（*AHH/*AHA） | 各家 | 各 era | BOTH | coarse | CONDITIONAL | YES | 价侧约定需按 DQ 记录的亚盘语义复核 |
| ou25（*>2.5/*<2.5） | 各家 | 2015-26 | BOTH | coarse | CONDITIONAL | YES | 覆盖 ≥99% |
| hxg / axg | HxG/AxG | 2026-27 | DATETIME | unknown | UNKNOWN | **NO（本版本）** | L4：官方 notes 未定义、样本<12 |
| lineup | DATA-006（实时） | 2026-27+ | DATETIME | minute | SAFE(仅 time_safe=True) | 仅 Lineup-Enhanced | 本版本基线不含 |
| lineup（历史） | lineups_all.csv | 2024-25/2025-26 | — | — | LEAKAGE-RISK | **NO** | retroactive，time_safe=False |

## 规则
1. `allowed_for_training=NO` 的字段在构建层**结构性拒绝**（不是"建议不使用"）。
2. CONDITIONAL 字段进入特征时必须携带 `odds_evidence` + `odds_timestamp_kind=collection_convention_coarse`。
3. UNKNOWN 字段默认排除，除非未来有官方证据升级（需新 DQ 版本）。
4. 本注册表为 Dataset 版本的一部分（freeze 时指纹化）。
