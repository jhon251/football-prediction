# EXP-DIAG-EPL-001：真实数据失败机制诊断

> 只读诊断：生产模型、35 条规则、config、数据层、冻结基线 EXP-REAL-EPL-BASE-001（`7c52c6bdfa37`）均未修改。
> 诊断模拟写入独立目录 `backtest_output/diagnosis_epl_001/`，与基线同一样本定义（`range(0,380,3)[:120]`）与同一种子（20240101）。

## 0. 数据可用性声明

- 冻结基线原始记录保存：各模型 1X2/OU/BTTS/比分概率、unknowns、top_scenario。
- **未保存**（原始运行）：Team/Tactical/Psychology/Momentum/Referee/Player 的逐场直接输出、动量轨迹、赛中状态 → 记为 **DATA_UNAVAILABLE**。
- 本诊断使用的『逐场 Agent 输出』是**确定性重建**（同一冻结数据与代码、赛前层纯函数、无模拟），仅用于诊断，不冒充原始实验数据。

## 1. Agent 输出取证（确定性重建，380 场）

| Agent/信号 | 均值 | 标准差 | min | max | p50 | NO_SIGNAL 占比 | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Elo 差（基线特征） | 0.22622 | 64.109 | -223.11803 | 244.03436 | 0.0 | 0.02632 | 基线特征 |
| Team：攻防强度和差 | 0.23439 | 0.10667 | -0.80653 | 0.97285 | 0.23384 | 0.0 | 含主场优势（Team 把 home_adv 加进 attack） |
| Team：和差（无主场版） | -0.00478 | 0.09614 | -0.98536 | 0.68285 | 0.0 | 0.21579 | 主场优势剥离版，用于第 2 节相关性诊断 |
| Tactical：对位优势 | 0.04813 | 0.02769 | -0.232 | 0.279 | 0.047 | 0.0 | 幅度极小（±0.28），含主场偏移 |
| Tactical：对位优势（无主场版） | -0.00042 | 0.02801 | -0.283 | 0.196 | 0.0 | 0.06842 | 剥离主场偏移后用于相关性诊断 |
| Tactical：机会创造差 | 0.0871 | 0.04947 | -0.42 | 0.506 | 0.084 | 0.0 |  |
| Psychology：信心差 | 0.05953 | 0.06335 | -0.17 | 0.29 | 0.06 | 0.03947 | 仅由近期战绩驱动 |
| Psychology：压力差 | -0.05937 | 0.06891 | -0.26 | 0.14 | -0.06 | 0.0 |  |
| Fitness：疲劳差 | 0.00017 | 0.01322 | -0.056 | 0.056 | 0.0 | 0.77895 | 78% 场次为 0（周赛程双方拥挤度相同） |
| Referee：信号 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1.0 | 恒 0 —— 只有姓名，倾向 NO_SIGNAL |
| Player：信号 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1.0 | 恒 0 —— 无球员数据，NO_SIGNAL 占位 |
| Momentum：赛前值 | 0.5 | 0.0 | 0.5 | 0.5 | 0.5 | 0.0 | 恒 0.5；赛中轨迹 DATA_UNAVAILABLE |

## 2. 信息重复性分析

（Team/Tactical 信号采用**主场优势剥离版**，避免主场偏移把相关性虚高；Elo 差本身无主场成分。）
| 信号对 | Pearson | Spearman |
| --- | --- | --- |
| elo_diff__team_strength_diff_nohome | 0.2088 | 0.4276 |
| elo_diff__tactical_advantage_nohome | 0.2954 | 0.5942 |
| elo_diff__tactical_cc_diff_nohome | 0.1999 | 0.4231 |
| elo_diff__psych_confidence_diff | 0.4397 | 0.4747 |
| elo_diff__psych_pressure_diff | -0.3283 | -0.2598 |
| elo_diff__fitness_fatigue_diff | 0.0933 | 0.1017 |
| team_strength_diff_nohome__tactical_advantage_nohome | 0.9884 | 0.9505 |
| team_strength_diff_nohome__tactical_cc_diff_nohome | 0.9921 | 0.97 |
| team_strength_diff_nohome__psych_confidence_diff | 0.4323 | 0.8194 |
| team_strength_diff_nohome__psych_pressure_diff | -0.3105 | -0.4238 |
| team_strength_diff_nohome__fitness_fatigue_diff | -0.0071 | 0.0376 |
| tactical_advantage_nohome__tactical_cc_diff_nohome | 0.9951 | 0.9646 |
| tactical_advantage_nohome__psych_confidence_diff | 0.4308 | 0.8192 |
| tactical_advantage_nohome__psych_pressure_diff | -0.3095 | -0.416 |
| tactical_advantage_nohome__fitness_fatigue_diff | 0.0053 | 0.0647 |
| tactical_cc_diff_nohome__psych_confidence_diff | 0.3942 | 0.8027 |
| tactical_cc_diff_nohome__psych_pressure_diff | -0.282 | -0.3878 |
| tactical_cc_diff_nohome__fitness_fatigue_diff | -0.0036 | 0.0548 |
| psych_confidence_diff__psych_pressure_diff | -0.7555 | -0.6127 |
| psych_confidence_diff__fitness_fatigue_diff | -0.0203 | 0.0405 |
| psych_pressure_diff__fitness_fatigue_diff | 0.0373 | 0.1314 |

### Agent → 输入特征依赖矩阵（代码静态分析）

| Agent | 输入特征 | 与 Elo 输入的重叠 |
| --- | --- | --- |
| Team | elo(walk-forward), attack_rate, defense_rate, form_ppg, streak, home_advantage(league rates), shots/SOT/corners rates (extended) | 高（elo/进球率同源） |
| Tactical | TeamState fields only (attack/defense/midfield, styles=neutral, defensive_line=0.5, counter=0.5) | 高（消费 TeamState，即 Elo 派生） |
| Psychology | form points/streak from FT results, importance=0.5 const, coach pressure=0.5 const, home flag | 中（近况战绩） |
| Fitness | schedule: congestion_14d, days_since_last_match | 低 |
| Referee | referee NAME only (no tendency data) -> NO_SIGNAL | 零（NO_SIGNAL） |
| Player | no player data -> NO_SIGNAL placeholder squad | 零（NO_SIGNAL） |
| Momentum | in-match events only (not a pre-match feature consumer) | 零（赛中事件） |

## 3. 单 Agent 信息价值（120 场固定样本，400 模拟）

| 配置 | Accuracy | Brier | LogLoss | ECE |
| --- | --- | --- | --- | --- |
| team_psychology | 0.4083 | 0.6579 | 1.0863 | 0.0181 |
| full_minus_tactical | 0.4000 | 0.6601 | 1.0902 | 0.0176 |
| team_referee | 0.3917 | 0.6628 | 1.0933 | 0.0162 |
| team_only | 0.3917 | 0.6633 | 1.0939 | 0.0150 |
| team_tactical | 0.3917 | 0.6635 | 1.0950 | 0.0399 |
| player_only | 0.3917 | 0.6641 | 1.0954 | 0.0250 |
| referee_only | 0.3917 | 0.6643 | 1.0955 | 0.0200 |
| full_minus_psychology | 0.3917 | 0.6647 | 1.0969 | 0.0416 |
| tactical_only | 0.3917 | 0.6652 | 1.0965 | 0.0133 |
| psychology_only | 0.3833 | 0.6655 | 1.0983 | 0.0381 |
| full_minus_referee | 0.4000 | 0.6661 | 1.0990 | 0.0420 |
| momentum_only | 0.3917 | 0.6665 | 1.0992 | 0.0317 |
| full_minus_momentum | 0.4000 | 0.6665 | 1.1003 | 0.0439 |
| full | 0.4000 | 0.6677 | 1.1021 | 0.0414 |
| full_minus_player | 0.4000 | 0.6677 | 1.1021 | 0.0414 |
| full_minus_team | 0.3333 | 0.6687 | 1.1018 | 0.0244 |
| team_momentum | 0.3917 | 0.6700 | 1.1049 | 0.0354 |

### 交互/融合问题标记

- `team`：only Brier=0.6633，full−X Brier=0.6687，full Brier=0.6677 → 单独运行优于 full，但移除后 full 无明显改善 → 其优势在栈内被其他通道稀释
- `tactical`：only Brier=0.6652，full−X Brier=0.6601，full Brier=0.6677 → **INTERACTION / FUSION PROBLEM**：单用优于 full，移除后 full 也变好
- `psychology`：only Brier=0.6655，full−X Brier=0.6647，full Brier=0.6677 → **INTERACTION / FUSION PROBLEM**：单用优于 full，移除后 full 也变好
- `momentum`：only Brier=0.6665，full−X Brier=0.6665，full Brier=0.6677 → 单独与融入均接近中性（差异 <0.002，噪声级）
- `referee`：only Brier=0.6643，full−X Brier=0.6661，full Brier=0.6677 → 单独运行优于 full，但移除后 full 无明显改善 → 其优势在栈内被其他通道稀释
- `player`：only Brier=0.6641，full−X Brier=0.6677，full Brier=0.6677 → 单独运行优于 full，但移除后 full 无明显改善 → 其优势在栈内被其他通道稀释

## 4. 概率融合机制诊断（敏感性）

| Agent | 平均 |ΔP(home)| | 最大 |Δ| | >1pp 场次占比 | 判定 |
| --- | --- | --- | --- | --- |
| Team | 0.06896 | 0.2075 | 1.0 | high_influence_standalone_competitive |
| Tactical | 0.02823 | 0.1275 | 0.8 | high_influence_standalone_competitive |
| Psychology | 0.01208 | 0.04 | 0.55 | high_influence_standalone_competitive |
| Momentum | 0.00694 | 0.0225 | 0.275 | low_influence |
| Referee | 0.00552 | 0.0125 | 0.16667 | low_influence |
| Player | 0.0 | 0.0 | 0.0 | low_influence |

判定规则：平均 |ΔP|≥0.01 为高影响；高影响且单 Agent 配置 Brier < full−0.002 为 standalone_competitive（仅表示单独可竞争，**不代表其信息独立** —— 独立性由第 2/6 节相关性判定），否则为 low_information_high_influence。

## 5. 阶段性诊断（120 场样本按时间三分）

### early_season

| 配置 | n | Accuracy | Brier | LogLoss | ECE |
| --- | --- | --- | --- | --- | --- |
| full | 40 | 0.6250 | 0.6150 | 1.0256 | 0.1229 |
| team_only | 40 | 0.6000 | 0.6149 | 1.0233 | 0.1142 |
| tactical_only | 40 | 0.6000 | 0.6437 | 1.0630 | 0.0700 |
| psychology_only | 40 | 0.6000 | 0.6213 | 1.0302 | 0.0615 |
| momentum_only | 40 | 0.6000 | 0.6281 | 1.0396 | 0.0517 |
| referee_only | 40 | 0.6000 | 0.6318 | 1.0459 | 0.0633 |
| full_minus_team | 40 | 0.3000 | 0.6482 | 1.0677 | 0.0631 |
| full_minus_tactical | 40 | 0.5500 | 0.6184 | 1.0273 | 0.0721 |
| full_minus_psychology | 40 | 0.6000 | 0.6164 | 1.0263 | 0.0882 |
| full_minus_momentum | 40 | 0.6250 | 0.6113 | 1.0203 | 0.1057 |
| full_minus_referee | 40 | 0.6250 | 0.6118 | 1.0215 | 0.1161 |

### mid_season

| 配置 | n | Accuracy | Brier | LogLoss | ECE |
| --- | --- | --- | --- | --- | --- |
| full | 40 | 0.3000 | 0.6771 | 1.1117 | 0.0844 |
| team_only | 40 | 0.3000 | 0.6955 | 1.1425 | 0.1194 |
| tactical_only | 40 | 0.3000 | 0.6894 | 1.1344 | 0.1133 |
| psychology_only | 40 | 0.3000 | 0.7021 | 1.1571 | 0.1370 |
| momentum_only | 40 | 0.3000 | 0.7038 | 1.1592 | 0.1317 |
| referee_only | 40 | 0.3000 | 0.6938 | 1.1419 | 0.1200 |
| full_minus_team | 40 | 0.3000 | 0.6986 | 1.1499 | 0.1249 |
| full_minus_tactical | 40 | 0.3250 | 0.6926 | 1.1409 | 0.1113 |
| full_minus_psychology | 40 | 0.3000 | 0.6707 | 1.1030 | 0.0972 |
| full_minus_momentum | 40 | 0.3000 | 0.6753 | 1.1084 | 0.0992 |
| full_minus_referee | 40 | 0.3000 | 0.6788 | 1.1132 | 0.0944 |

### late_season

| 配置 | n | Accuracy | Brier | LogLoss | ECE |
| --- | --- | --- | --- | --- | --- |
| full | 40 | 0.2750 | 0.7111 | 1.1691 | 0.1251 |
| team_only | 40 | 0.2750 | 0.6795 | 1.1159 | 0.0706 |
| tactical_only | 40 | 0.2750 | 0.6625 | 1.0920 | 0.0033 |
| psychology_only | 40 | 0.2500 | 0.6732 | 1.1075 | 0.0531 |
| momentum_only | 40 | 0.2750 | 0.6675 | 1.0989 | 0.0150 |
| referee_only | 40 | 0.2750 | 0.6673 | 1.0986 | 0.0033 |
| full_minus_team | 40 | 0.4000 | 0.6591 | 1.0876 | 0.0072 |
| full_minus_tactical | 40 | 0.3250 | 0.6693 | 1.1023 | 0.0442 |
| full_minus_psychology | 40 | 0.2750 | 0.7068 | 1.1614 | 0.1270 |
| full_minus_momentum | 40 | 0.2750 | 0.7129 | 1.1721 | 0.1292 |
| full_minus_referee | 40 | 0.2750 | 0.7078 | 1.1622 | 0.1246 |

## 6. Elo 信息覆盖分析（Team-only vs 冻结 Elo，120 场样本）

- Team-only 与 Elo 的主胜概率相关：**0.3625**
- Elo 正确率 0.4667 / Team-only 正确率 0.3917
- 两者同对 0.3833；**Elo 错而 Team 对 0.0083**；Team 错而 Elo 对 0.0833；同错 0.525
- Team−Elo 残差与实际结果的相关：**-0.2624（z≈-2.9σ，n=120）**
  —— 残差相关为**负**且超过 2σ：Team 相对 Elo 的偏离与结果负相关，即 Team 的『额外信息』整体是**反信息**（Elo 已覆盖其有效部分，偏离主要是有害噪声），而非≈0 的中性重复。

## 7. 失败样本分析（冻结 380 场记录，四类）

### full_high_conf_wrong（n=3）

- 2025-26-014 Burnley 2-0 Sunderland：full=0.22/0.23/0.54，elo=0.44/0.26/0.31。赛前已知：Elo差=-17，Team强度差=-0.81，信心差=+0.02。未知项：away_lineup, home_lineup, injuries
- 2025-26-023 Tottenham 0-1 Bournemouth：full=0.63/0.21/0.16，elo=0.49/0.26/0.26。赛前已知：Elo差=+20，Team强度差=+0.97，信心差=+0.10。未知项：away_lineup, home_lineup, injuries
- 2025-26-027 Nott'm Forest 0-3 West Ham：full=0.61/0.21/0.18，elo=0.50/0.25/0.25。赛前已知：Elo差=+30，Team强度差=+0.80，信心差=+0.11。未知项：away_lineup, home_lineup, injuries

### elo_right_full_wrong（n=27）

- 2025-26-013 Brentford 1-0 Aston Villa：full=0.35/0.28/0.37，elo=0.45/0.26/0.29。赛前已知：Elo差=-7，Team强度差=-0.13，信心差=+0.05。未知项：away_lineup, home_lineup, injuries
- 2025-26-014 Burnley 2-0 Sunderland：full=0.22/0.23/0.54，elo=0.44/0.26/0.31。赛前已知：Elo差=-17，Team强度差=-0.81，信心差=+0.02。未知项：away_lineup, home_lineup, injuries
- 2025-26-091 Burnley 0-2 Arsenal：full=0.37/0.35/0.28，elo=0.36/0.26/0.38。赛前已知：Elo差=-69，Team强度差=+0.22，信心差=-0.01。未知项：away_lineup, home_lineup, injuries
- 2025-26-115 Wolves 0-2 Crystal Palace：full=0.38/0.34/0.28，elo=0.32/0.25/0.43。赛前已知：Elo差=-95，Team强度差=+0.23，信心差=-0.05。未知项：away_lineup, home_lineup, injuries

### full_right_elo_wrong（n=7）

- 2025-26-024 Wolves 2-3 Everton：full=0.36/0.28/0.37，elo=0.43/0.26/0.31。赛前已知：Elo差=-20，Team强度差=-0.09，信心差=+0.02。未知项：away_lineup, home_lineup, injuries
- 2025-26-137 Leeds 3-1 Chelsea：full=0.40/0.33/0.27，elo=0.34/0.25/0.41。赛前已知：Elo差=-80，Team强度差=+0.28，信心差=+0.05。未知项：away_lineup, home_lineup, injuries
- 2025-26-192 Wolves 3-0 West Ham：full=0.40/0.34/0.26，elo=0.37/0.25/0.38。赛前已知：Elo差=-62，Team强度差=+0.24，信心差=+0.02。未知项：away_lineup, home_lineup, injuries
- 2025-26-220 West Ham 3-1 Sunderland：full=0.38/0.35/0.27，elo=0.33/0.25/0.42。赛前已知：Elo差=-91，Team强度差=+0.18，信心差=+0.00。未知项：away_lineup, home_lineup, injuries

### both_wrong（n=194）

- 2025-26-001 Aston Villa 0-0 Newcastle：full=0.46/0.23/0.31，elo=0.55/0.16/0.28。赛前已知：Elo差=+0，Team强度差=+0.29，信心差=+0.06。未知项：away_lineup, home_lineup, injuries
- 2025-26-002 Brighton 1-1 Fulham：full=0.46/0.23/0.31，elo=0.48/0.24/0.29。赛前已知：Elo差=+0，Team强度差=+0.29，信心差=+0.06。未知项：away_lineup, home_lineup, injuries
- 2025-26-005 Wolves 0-4 Man City：full=0.46/0.23/0.31，elo=0.47/0.25/0.28。赛前已知：Elo差=+0，Team强度差=+0.29，信心差=+0.06。未知项：away_lineup, home_lineup, injuries
- 2025-26-006 Chelsea 0-0 Crystal Palace：full=0.46/0.23/0.31，elo=0.48/0.24/0.29。赛前已知：Elo差=+0，Team强度差=+0.29，信心差=+0.06。未知项：away_lineup, home_lineup, injuries

说明：仅使用预测时刻已知信息；无法解释的场次不做归因（RANDOMNESS/UNEXPLAINED）。

## 8. 十个问题（按证据强度）

**Q1 Team 为什么有正贡献？** 本样本证据不足：移除 Team 后 Brier 变化 ≈+0.0009（0.6687 vs 0.6677），方向与 380 场冻结消融（+0.0048）一致但幅度低于判定阈值。结合 Q9：Team 的价值在于它是唯一注入通道（通道必要性），而非独立信息量。
**Q2 Tactical 为什么负贡献？** 本样本成立：移除后 Brier 改善 ≈+0.0077（0.6677→0.6601），与 380 场消融（−0.0044）同向。机制证据：Tactical 只消费 TeamState（即 Elo/Team 派生量），与 Team 无主场版相关性 0.9884（Spearman 0.9505），其乘性修饰（chance_creation_modifier）把同一强度信号在模拟中二次放大 → 重复信息 + 复合放大。
**Q3 Psychology 为什么负贡献？** 本样本成立：移除后 Brier 改善 ≈+0.0031（0.6677→0.6647）。Psychology 的信心/压力差仅由近期战绩驱动，与 Team 无主场版相关性 0.4323。其风险/动机通道把同一近况信息第三次乘性修饰进攻强度。注意：`team_psychology`（Team+Psychology，去掉其余通道）是全部配置中最优的（0.6579），说明 Psychology 的害处只在完整栈内叠加时显现。
**Q4 Momentum** 移除后 ΔBrier≈+0.0012，低于判定阈值 → 视为中性（380 场消融 −0.0018，方向一致但微弱）。
**Q5 Referee** 移除后 ΔBrier≈+0.0016。Referee 在本数据中只有姓名（倾向 NO_SIGNAL），任何非零影响都是围绕中性裁判因子的模拟方差 → 无信息贡献，影响可忽略。
**Q6 是否存在 Agent 信息重复？** 是。Team / Tactical / Psychology 全部消费同一 walk-forward 历史（Elo、进球率、近况），Tactical 甚至直接消费 TeamState。相关性证据（无主场版）：Team↔Tactical 0.9884（Spearman 0.9505）、Team↔Psychology 0.4323、Team↔Elo 0.2088（见第 2 节）。
**Q7 是否存在概率融合放大？** 是（机制级证据）。同一 Elo 派生信号在流水线中被乘性使用多次：Team 强度 → Tactical 的 chance_creation_modifier（乘）→ 事件引擎的进攻强度（再乘 attacking_intensity，Psychology 再次修饰）。乘性复合使信号误差指数化放大；第 4 节的影响度表给出逐 Agent 的量化影响。
**Q8 冷启动是否是主要问题？** 实测（120 场样本三分）：Elo 早/中/晚 = 0.5974/0.6930/0.6546；full = 0.6150/0.6771/0.7111。full 相对 Elo 的劣势：早段 +0.0176、中段 -0.0159、晚段 +0.0565。
→ 晚段劣势最大（中段 full 甚至不差于 Elo，-0.0159）：冷启动是**次要因素**，退化集中在晚段（同一信号的重复放大随赛季推进积累）。
**Q9 Elo 是否已覆盖 Team 的主要信息？** 证据：Team-only 与 Elo 的主胜概率相关 0.3625；Elo 正确率 0.4667 vs Team-only 0.3917；Elo 错而 Team 对仅 0.0083，Team 错而 Elo 对 0.0833（Elo 的纠错频次是反向的 10 倍）；Team−Elo 残差与结果相关 -0.2624（z≈-2.9σ）。
残差显著为负 → **Elo 已覆盖 Team 的有效信息**；Team 相对 Elo 的偏离整体是**反信息**（其『额外信息』与结果负相关）。Team 的正贡献因此不是信息贡献，而是通道必要性：它是模拟流水线唯一的强度注入点，移除会破坏整个融合尺度。
**Q10 full_system 输给 Elo 的主要原因？** 融合结构问题，而非信息无效。120 场样本实测：full=0.6677，Elo=0.6483（full 劣势 +0.0194）；全部 17 配置中最优的是 `team_psychology`=0.6579（比 full 低 0.0098），次优 `full_minus_tactical`=0.6601。即：Team(+Psychology) 核心单独运行时最好，而 Tactical/Momentum/Referee 通道的叠加把概率推向失真。结合 Q2/Q6/Q7/Q9：这些通道全部消费同一 Elo 派生信息并以乘性方式重复注入，放大的是重复信息与反信息噪声 → 校准退化（full ECE 高于 Elo，冻结基线 0.0350 vs 0.0152）。**结论：信息基本有效，但融合方式错误（重复 + 乘性放大）；且最优配置仍弱于 Elo，说明模拟流水线本身存在相对 Elo 的残余误差。**

**PRIMARY（证据强）：**
- Tactical 与 Team 共享同一 Elo 派生输入（无主场版 r=0.9884），乘性修饰重复放大同一信号 → 移除后 Brier 改善 ≈+0.0077（两次独立样本同向：380 场 −0.0044）
- 信息重复：Team/Tactical/Psychology 是同一 Elo 派生信息的三种表达（Team↔Tactical 无主场 r=0.9884，Spearman 0.9505）
- 乘性放大：概率聚合采用乘性复合（chance_creation_modifier × attacking_intensity）而非加权平均 → 重复信号的误差被指数化放大
- Team 残差为反信息（r=-0.2624，z≈-2.9σ）：Elo 已覆盖其有效信息，Team 相对 Elo 的偏离整体有害 —— 支撑『信息重复而非信息无效』的定性结论
**SECONDARY（证据中等）：**
- Psychology 在 full 栈内移除改善 ≈+0.0031（近况信息第三次放大）；但其与 Team 单独组合（team_psychology）是实测最优配置
- Referee 无信息（NO_SIGNAL），其影响为噪声级
- 冷启动为次要因素：晚段劣势 +0.0565 最大，中段 -0.0159、早段 +0.0176
- 融合结构瓶颈：最优配置 team_psychology=0.6579、次优 full_minus_tactical=0.6601 均优于 full=0.6677，但都弱于 Elo=0.6483（幅度受 120 场样本限制，DIAG-002/003 进一步验证）
**UNCONFIRMED（证据不足，不猜测）：**
- Team 正贡献幅度：380 场消融 +0.0048，120 场诊断样本仅 ≈+0.0009，不显著
- Momentum 的微小负贡献需要更大样本确认

**NEXT EXPERIMENT（仅设计，不执行、不修改生产模型）：**
1. DIAG-002：在诊断副本中把 Tactical 的 chance_creation_modifier 改为可开关的加性项，量化『重复放大』对 full_minus_tactical 改善 ≈0.0077 的机制贡献。
2. DIAG-003：检验实测最优配置 `team_psychology`（0.6579）能否在更大样本上稳定优于 full；同时测『Team-only + 线性融合』与 Elo 的差距，分离融合结构瓶颈与信息量瓶颈。
3. DIAG-004：跨赛季（需先获取第二赛季真实数据）复测上述结论的稳定性。

## 9. 可复现

- 冻结基线引用：`7c52c6bdfa37`（基线目录未动，哈希清单在 `backtest_output/diagnosis_epl_001/baseline_manifest.json`）
- 诊断产物：`preds.json`（17 配置 × 120 场，400 模拟，seed 20240101）
- 注册表：`backtest_output/diagnosis_epl_001/experiments.jsonl`（EXP-DIAG-EPL-001，`synthetic_data=false`，`market_data=false`）
