# Schema Policy（跨联赛 × 跨赛季字段治理）

来源：官方 football-data notes.txt + 全量表头审计。原始 CSV 不可变；本 policy 只定义"读取时如何使用字段"。

## 字段分类（final）

| 类别 | 字段 | 说明 |
|---|---|---|
| IDENTITY | Div, Date, HomeTeam, AwayTeam | 主身份 |
| TIME | Time（仅 2019-20+）, Date | 见 temporal_availability_policy |
| SAFE-FEATURE | Div, Date, Time, HomeTeam, AwayTeam, Referee（仅 E0） | 赛前已知 |
| CONDITIONAL-FEATURE | 非 C 赔率族（B365*/BW*/IW*/PS*/WH*/VC*/Max*/Avg*/AH*/O/U*/BFD*/BFE*/CL*/LB*/BMGM*/BV*/Bb*） | 官方=pre-closing；周五/周二采集（赛前）；单快照 |
| CONDITIONAL-FEATURE | C 后缀族（*C*，2019-20+） | 官方=closing（notes.txt L48）；周五/周二采集（赛前）；"closing"=采集时点收盘，非开球瞬间 |
| UNKNOWN-EXCLUDED | HxG, AxG（2026-27 起） | 官方 notes 未定义；样本<12；暂不纳入核心 Dataset |
| LABEL | FTHG, FTAG, FTR | 赛后结果 |
| LABEL-ONLY | HTHG, HTAG, HTR | 半场（赛中） |
| LEAKAGE-RISK-EXCLUDED | HS/AS/HST/AST/HF/AF/HC/AC/HY/AY/HR/AR | 全场赛后统计，严禁 Feature（仅历史聚合 observed_at<kickoff 可用） |

## 跨季字段族（era）

| 时代 | 字段数 | 特有 | 缺失 |
|---|---|---|---|
| 2015-18 | 64-65 | Bb*/IW/WH/VC/LB | Time/Avg*/Max*（Avg/Max 2019-20+ 才有）/C 后缀 |
| 2018-19 | 61-62 | Bb*/IW/WH/VC | LB |
| 2019-24 | 105-106 | Time/Avg*/Max*/BFD* | Bb* |
| 2024-25 | 119-120 | +CL/BV/BMGM | IW/VC |
| 2025-26 | 131-132 | +C 后缀族全量 | — |
| 2026-27 | 113 | +HxG/AxG | —（进行中，另行跟踪） |

规则：
- 跨季统一 schema 时**不改原始 CSV**；读取层按 era 投影到并集字段，缺字段置 None（DIAG-007：禁止插补/回填）。
- C 后缀列**不因名为 "closing" 自动进入 SAFE**——一律 CONDITIONAL，且仅在 temporal policy 允许的时点使用。
