# V1.1 Football Reality Validation Report（足球真实性验证报告）

生成方式：全部实验运行在**受控合成世界**（`RealityHarness`，两队强度/风格旋钮显式可控）与合成 mock 数据上，**不使用任何真实比赛数据**。所有断言只验证**因果方向**，不规定具体数值；所有失败都来自真实因果链缺陷，已逐条修复（不是为了让测试通过而改结果）。

> 重要结论：本报告通过全部现实性检查，只意味着**沙盘在逻辑层面没有明显违背现实足球**。
> **它仍然 NOT READY FOR REAL PREDICTION**（`REAL_DATA_READY = false`）。

---

## 1. 当前系统架构（V1.1 时点）

```
Data(合成) → WorldState → 31 Agents → Knowledge Rules(35条) → RuleEngine
          → Scenario Engine(31+原型) → Monte Carlo Engine(默认10k, 可复现)
          → Probability Agents(纯统计) → Risk/Confidence → Explanation
          → Learning/PostMatch → V1.1: RealityHarness + AnomalyDetector + Ablation + SanitySuite
```

V1.1 新增（验证基础设施，非新 Agent、非 UI、非真实数据）：
- `evaluation/reality.py` — 受控世界构建器 + 配对模拟 + 足球指标
- `evaluation/anomaly.py` — 反常结果自动检测器（10 项检查）
- `evaluation/sanity.py` — 系统级 Sanity Suite（11 个区块）
- `evaluation/ablation.py` — Agent 消融/贡献分析
- `evaluation/rule_audit.py` — 35 条规则人工审计元数据
- `tests/football_reality/` — 常识场景 A-H、因果方向、异常、消融、规则审计测试
- CLI：`football validate`；配置：`real_data_ready`（默认 false，9 个门槛）

## 2. 35 条 Knowledge Rule 审计结果

全部 35 条（27 条状态规则 + 8 条战术模式）审计输出：

- **Validated: 0** — 没有一条规则拥有真实比赛证据，任何规则都不得声称已验证。
- **Tentative: 35 / Unverified: 0 / Assumption: 35** — 全部规则 `source_type = "assumption"`（开发期人为假设），状态保持 tentative。
- **needs_real_data_validation: 35/35 = true**。

逐条审计摘要（完整 JSON 见 `football validate --output`，机器可读）：

| 类别 | 规则 | 因果方向 | 过拟合风险 |
| --- | --- | --- | --- |
| 心态 | leading_tempo / trailing_push / late desperation / late game management（8条主客镜像） | 比分 → 教练反应 → 节奏/风险/强度 | medium（方向有文献支持，幅度是拍脑袋的） |
| 红牌 | red_card_disadvantage ×2 | 少一人 → 机会创造/压迫下降 | **low**（方向证据最强） |
| 心理 | goal_up/down_momentum、pressure_decision、high_confidence、momentum_feedback、home_crowd（9条） | 进球/压力/势头 → 心理状态 | medium～high（momentum_feedback 与动量本体部分重复，标记 high） |
| 疲劳 | fatigue_late_decline ×2 | 疲劳+末段 → 机会质量下降 | medium（0.55 阈值任意） |
| 环境 | rain / heat / wind | 天气 → 小幅机会/节奏修正 | medium；**wind 系数接近无效，明确标记 high 风险假设** |
| 纪律 | yellow_card_caution ×2 | 黄牌积累 → 压迫谨慎 | medium |
| 结构 | half_time_reset | 中场 → 势头重置 | low（结构性机制） |
| 战术模式 | 高压vs弱出球 / 低位vs控球 / 反击vs高位 / 边路vs窄防 / 三中卫vs双前锋 / 内收边卫vs宽压迫 / 定位球错配 / 中场质量差 | 风格对位 → 机会/控球/转换修正 | medium；**inverted_fb_vs_wide_press 标记 high（高度推测）** |

审计结论：方向性大多有足球常识或文献支持；**所有幅度参数都是假设**，必须等真实数据标定。

## 3. 每个 Agent 的职责（不变，仅列）

Team(风格+状态)/Coach(gameplan+反应)/Player(个体状态)/Lineup(首发与缺阵)/Fitness(个体疲劳)/Psychology(心理)/Environment(天气分级)/Referee(只改事件概率)/TacticalMatchup(对位)/Opening(开局)/Possession/Tempo/Momentum(动态层)/EventTrigger(事件采样)/Substitution(换人)/StateTransition(状态机)/MatchScript+Ranking(剧本)/Counterfactual(反事实)/四个概率Agent(纯统计)/UpsetRisk/Risk/Confidence/Explanation/Learning/PostMatchEvaluation/Director。

## 4. 每个 Agent 是否产生实际影响（Ablation，各 500 场，seed 42）

| 配置 | 主胜 | 平 | 客胜 | 期望进球 | Δ主胜 |
| --- | --- | --- | --- | --- | --- |
| baseline（全关） | 0.400 | 0.252 | 0.348 | 4.58 | — |
| + Team | 0.422 | 0.252 | 0.326 | 4.17 | **+0.022** |
| + Coach | 0.428 | 0.254 | 0.318 | 4.19 | +0.006 |
| + Player | 0.448 | 0.234 | 0.318 | 4.13 | **+0.020** |
| + Fitness | 0.448 | 0.234 | 0.318 | 4.13 | 0.000* |
| + Psychology | 0.480 | 0.230 | 0.290 | 4.13 | **+0.032** |
| + Tactical | 0.490 | 0.248 | 0.262 | 3.22 | +0.010** |
| + Environment | 0.490 | 0.248 | 0.262 | 3.22 | 0.000* |
| + Referee | 0.456 | 0.248 | 0.296 | 3.33 | **−0.034** |
| + Momentum | 0.484 | 0.232 | 0.284 | 3.39 | **+0.028** |
| + Scenario | 0.484 | 0.232 | 0.284 | 3.39 | 0.000*** |
| + Counterfactual | 0.484 | 0.232 | 0.284 | 3.39 | 0.000*** |
| full system | 0.484 | 0.232 | 0.284 | 3.39 | 0.000 |

诚实解读：
- **Team / Psychology / Momentum / Player** 是 1X2 的主要驱动（+2~3.2pp）。
- **Tactical** 对 1X2 影响不大（+1pp），但**把期望进球从 4.6 校准到 3.2** —— 它主要负责"比赛总量"的合理性。
- **Referee** 使主胜下降 3.4pp —— 该场被指派裁判的倾向（高黄牌/点球倾向）确实在改变模拟，说明裁判通道有效且**不是摆设**。
- **Fitness / Environment 在本场 fixture 上贡献为 0*** —— 不是坏了：本场两队赛程负担相近、天气温和，无信号可贡献；在极端疲劳/天气的受控测试中它们的方向性已验证（见第 5 节）。
- **Scenario / Counterfactual 贡献恒为 0*** —— 这是**设计使然**：它们是赛后/事后分析层，只改变报告，不改变模拟概率。这如实写入报告，而不是假装它们有贡献。

## 5. 因果方向测试结果（全部 PASS，方向断言，不锁数值）

| 因素改变（其余条件完全一致） | 方向断言 | 实测 |
| --- | --- | --- |
| 主队攻击 0.5→0.68 | 主胜 ↑ | 0.393 → 0.497 ✓ |
| 主队防守 0.5→0.70 | 主胜 ↑ | 上升 ✓ |
| 客队攻防 0.5→0.68/0.66 | 主胜 ↓ | 下降 ✓ |
| 主队 30' 红牌 | 主胜 ↓、客胜 ↑ | 0.39→0.14 / 0.36→0.61 ✓ |
| 主队疲劳 0.65 | 末段脆弱性 ↑ | 机制层：客队进攻强度 ↑ 且主队 ↓ ✓；端到端有界 ✓ |
| 裁判黄牌倾向 0.35→0.72 | 黄牌数 ↑ | 3.6→5.1 ✓ |
| 大雨 | 总进球不增 | 3.25 → 3.07 ✓ |
| 主队高位防线 + 客队强反击 | 客胜 ↑ | 0.36 → 0.48 ✓ |
| 主队门将 0.5→0.78 | 客队进球 ↓ | 下降 ✓ |
| 主队高压 vs 客队长传出球 | 主队射门占比 ↑ | 上升 ✓ |

## 6. 足球常识场景测试结果（A-H 全部 PASS）

- **A 强 vs 弱**：强队胜率显著更高、射门占比 >0.56；弱队仍能赢（爆冷存在），但从不占优（<45%）。
- **B 早进球(10')**：通过真实状态机触发进球 → 领先/落后心态、势头、压力全部变化；此后客队射门占比上升（15' 起落后反扑规则生效）。
- **C 红牌(30')**：人数 10、阵型 4-3-3→4-4-1、机会创造 ×0.68；主胜概率与射门占比显著下降；剧本分布改变。
- **D 高位防线 vs 强反击**：主队暴露(transition risk 0.78>0.65)、身后空当被识别；客队机会创造更高；**主队控球高 ≠ 安全**（客胜 0.36→0.48）。
- **E 70' 2-0 领先**：领先方不比 0-0 时更激进；落后方风险上升；追平/追近仍可能；进球未被机械关闭。
- **F 客队 70' 落后**：客队进攻强度与风险上升、末段射门占比上升；主队反击机会上升（落后压上留下身后空间）。
- **G 疲劳**：机制层验证（疲劳方的防守被攻得更凶、自己进攻下降）；惩罚有界，无夸张线性崩塌。
- **H 换人**：领先→防守换人（进攻/风险↓）；落后→进攻换人（进攻/风险↑）。

## 7. 异常情况（Anomaly Detector）

检测器在健康系统上 **10/10 PASS**；对**人为制造的反向因果**（弱队压制强队）能正确标记 ANOMALY。

## 8. 修复的问题（审计发现的真实因果链缺陷，共 9 处）

| # | 缺陷 | 修复前证据 | 修复 |
| --- | --- | --- | --- |
| 1 | **状态型规则每次事件重复叠加**（乘性规则复合衰减） | 红牌后每来一个事件，机会创造 1.0→0.68→0.46→0.31→0.21 | RuleEngine 增加 `rule_conditions` 条件边沿签名：规则只在条件 False→True 时触发一次；条件翻转后可再次触发 |
| 2 | **乌龙球动量方向颠倒** | 受益方动量 0.50→0.31 | 修正表值与方向逻辑：受益方 +0.26 |
| 3 | **xG 语义与进球机制脱节**（xG 累计/实际进球=1.85） | 平均 xG 4.48 vs 进球 2.42 | 进球抽样直接等于 xG（门将系数调整）；重新标定射门质量参数；乌龙 xG=0；标定后比率 ≈1.00 |
| 4 | **全场事件上限从未执行**（只执行单分钟上限） | 红牌理论上可跨分钟无限累积 | 引擎增加比赛级/球队级计数，`_within_caps` 在事件处理前拦截 |
| 5 | **连胜心理学逻辑失效**（streak 永远 ≤1） | 5 连胜信心与 5 连败几乎无差 | 修复连续胜场统计：5 连胜信心 0.66 vs 5 连败 0.43 |
| 6 | **防守强度单向失效**（防守只在对攻强于己时生效） | 防守 0.5→0.70 主胜概率纹丝不动 | 对位机会创造改为对称 attack−defense 项 + 射门质量防守抑制因子 |
| 7 | **反击威胁不传导到胜负**（高位防线 vs 强反击，客胜毫无变化） | 客胜 0.347→0.347 | transition risk → 对手机会创造通道 + 反击概率/质量随暴露度上升 |
| 8 | **疲劳没有"防守脆弱"通道**（疲劳只减进攻） | 疲劳方末段反而占优（落后反扑混淆） | 攻击疲劳防线强度通道；验证改为机制层断言 + 端到端有界 |
| 9 | **落后压上不留身后空间**（反击机会不随落后方压上上升） | 落后方压上后主队反击射门无变化 | trailing push 规则增加 transition_risk +0.08 |

每处修复都走的是"强度→机会创造→xG→进球→比分→结果"的既有因果链，**没有一行 `if strong_team: win += 0.2`**。

## 9. 尚未验证的问题（诚实清单）

1. **所有 35 条规则的幅度参数**（0.68、0.12、0.15…）都是假设值，方向合理、大小未标定。
2. **动量数值**（进球 +0.30、衰减 0.965/分钟）无证据支撑。
3. **补时模型**（进球+0.3'/换人+0.3'/伤病+0.6'）是简化近似。
4. **VAR 行为**（复审/改判概率）纯假设。
5. **受伤频率与严重度分布**未对真实伤病率校准。
6. **主场优势系数**（0.04）未按联赛/历史标定。
7. **换人窗口与触发阈值**（55/62/70/78/84'、疲劳 0.42）是人设的。
8. 教练/心理上下文（德比、保级战、夺冠战）在合成数据下未激活，通道未经验证。

## 10. 哪些部分只是人为假设

- 全部 35 条规则的**数值**与事件基线参数（`event_defaults.json`）。
- 教练行为字典（reaction_to_* 的 moderate/aggressive/defensive 映射与幅度）。
- 心理状态初始化（无真实赛前情绪数据）。
- 战术模式的 8 组对位系数。
- 场景原型库的分类边界（早进球 ≤15'、末段 ≥75' 等）。
这些假设**没有删除**（V1.1 原则），全部以 `source_type=assumption` 标记并可被未来证据覆盖。

## 11. 哪些部分必须等待真实数据

- 35 条规则的 Evidence 字段（verified_matches / success_rate / counter_examples）——结构已就绪，数据为零。
- 全部幅度参数的统计标定。
- `REAL_DATA_READY` 的 9 个门槛：真实 Data Provider、历史数据、历史回测、泄漏审计、校准检验、Brier Score、Log Loss、ROI 模拟、基准对比 —— **当前全部未完成，status=false**。

## 12. 当前系统距离真实比赛预测还有什么

1. 需要**真实 Data Provider**（当前只有合成 mock）。
2. 需要**历史回测**：用冻结时间点的数据预测已发生比赛，计算 Brier/LogLoss/校准曲线。
3. 需要**泄漏审计**（数据截止时间、首发发布时间、伤病发布时间逐场核对）。
4. 需要**基准对比**（与 naive 基线、ELO 基线、庄家赔率隐含概率对比，证明增量价值）。
5. 需要**规则证据积累**（LearningAgent 的候选规则 → 人工验证 → validated）。
6. 只有上述全部完成后，才允许 `REAL_DATA_READY=true`。

## 13. 下一阶段最重要的工作

1. **接入一个真实历史数据源**（Opta/Sportradar/StatsBomb/FBref 任一，只读历史数据，不做爬虫）。
2. **构建历史回测流水线**：逐场 `PRE_MATCH_FREEZE` 预测 → 赛后评估 → Brier/LogLoss/校准/ROI。
3. **对 35 条规则做证据回填**：每条规则用历史数据验证方向与幅度，失败的规则降级/修改并记录反例。
4. **校准事件基线**（进球率、牌率、点球率、伤停）按联赛分层。
5. **泄漏审计**作为回测的强制前置关卡。

---

## 附：`football validate` 面板输出

```
Football Reality Validation
============================
Core Logic:            PASS   (xG≈goals 比率≈1.0、进球/射门/平局率在现实区间)
Causal Direction:      PASS   (10 组单一因素方向断言全部正确)
State Transition:      PASS   (进球/红牌/换人/半场)
Red Card Logic:        PASS   (胜率↓、射门占比↓、剧本分布改变)
Fatigue Logic:         PASS   (机制方向正确、惩罚有界)
Leading State:         PASS   (领先不更激进、追平仍可能、进球未关闭)
Trailing State:        PASS   (落后进攻↑、对手反击机会↑)
Tactical Interaction:  PASS   (高位防线被反击惩罚、控球≠安全)
Scenario Diversity:    PASS   (31 原型、无单一剧本垄断、长尾保留)
Probability Conservation: PASS (1X2/比分/O-U/BTTS/半全场守恒)
Anomaly Detection:     PASS   (10/10)
Rules: Validated 0 / Tentative 35 / Unverified 0 / Assumption 35
REAL_DATA_READY: false (9 个门槛全部未完成)
Overall: READY FOR HISTORICAL BACKTEST（≠ READY FOR REAL PREDICTION）
```
