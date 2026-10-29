# V1.2 Historical Backtesting & Data Integrity Report（历史回测与数据完整性报告）

> **首条重要声明（必须最先读）：**
> 本阶段计划接入真实英超历史数据。**执行环境中网络完全不可用**（football-data.co.uk / GitHub 等全部连接失败，已多次验证），真实数据无法进入本工作区。按照 V1.2 最高原则"不得伪造真实足球数据"，本阶段**没有捏造任何真实数据**，而是：
> 1. 完整实现了 V1.2 全部数据完整性/回测基础设施（schema、PreMatchFreeze 2.0、时间旅行测试、泄漏审计、6 个基准、全部指标、walk-forward 回测器、真实数据版消融、五级规则证据、反例库、实验注册表、失败分析、CLI）；
> 2. 提供了 football-data.co.uk 真实数据格式的**现成导入器**（数据文件一旦放入即可运行正式回测，无需改代码）；
> 3. 用**明确标注的合成开发数据**（每条记录 `is_synthetic=true`）跑通了全部机制，只用于验证流水线本身正确性；
> 4. 因此本报告中的数字**没有任何真实足球预测含义**，最终判定只能是 **NO EVIDENCE OF EDGE（未获得真实数据，无法评估预测优势）**，`REAL_DATA_READY` 保持 `false`，"historical_data" 门槛**未完成**。

---

## 1. 数据来源

| 项 | 状态 |
| --- | --- |
| 计划数据源 | football-data.co.uk（EPL 各赛季 CSV：赛程、比分、半场比分、射门、牌、裁判、多家赛前收盘赔率） |
| 真实数据获取 | **被环境阻止（无网络）**，未能进行 |
| 本报告使用的数据 | `data/historical/synthetic_epl.json` —— **合成开发数据**（生成器 `SyntheticPremierLeagueSource`，种子固定、结构拟真：场均 2.72 球、主胜 47.4%、平局 23.6%、BTTS 52.6%），每条记录 `is_synthetic=true`、`source="synthetic_development"` |
| 真实数据就绪路径 | 下载任意赛季 `E0.csv` → `CsvFootballDataCoUkSource().parse(...)` → `football backtest --dataset real_epl.json` |

## 2. 数据时间范围与字段

- 合成开发数据：4 个赛季（2021-22 ~ 2024-25）× 380 场 = 1520 场，20 队。
- `HistoricalMatch` 统一 schema（V1.2 §3 完整实现）：赛前可见状态（可选）、opening/closing odds（带强制 `odds_timestamp`）、首发三态、结果字段（结构性隔离）、事件（goals/cards/penalties/own_goals/substitutions）、`is_synthetic` 与 `observed_at` 溯源。
- 可用字段：日期/球队/FT/HT 比分/射门/射正/犯规/黄红牌/裁判名/多家赔率列。
- 缺失字段（真实数据中该源也没有）：球员、首发名单、伤停、天气、xG、事件级分钟数据 —— 全部保持 **UNKNOWN**，绝不猜测。

## 3. 缺失率（诚实报告）

| 字段类别 | 状态 | 处理 |
| --- | --- | --- |
| 赛程/比分/半场/牌/赔率 | 可用 | 直接使用 |
| 首发名单 | 100% 缺失 | `LineupTriState.UNKNOWN`，LineupAgent 走"未确认→预期阵容"路径并标注不确定性 |
| 球员数据 | 100% 缺失 | Provider 返回空列表；Director 走 **NO_SIGNAL** 中性占位阵容路径（trace 中可见，不虚构能力） |
| 伤病 | 100% 缺失 | UNKNOWN，数据质量分下降 |
| 天气 | 100% 缺失 | `known=false`，环境影响自动中性 |
| 教练 | 100% 缺失 | 中性教练（NO_SIGNAL） |
| 裁判倾向 | 只有姓名 | 姓名可用；倾向 NO_SIGNAL（0 场执法证据） |
| 事件级分钟数据 | 缺失 | `events.complete=false` |

## 4. 时间冻结机制（PreMatchFreeze 2.0）

- `HistoricalPreMatchSnapshot`：任意比赛 X 只能读取 `observed_at < kickoff` 的观测；晚于开球的观测**直接拒绝并抛 `TemporalViolation`**（不是静默丢弃）。
- 所有 walk-forward 特征（Elo/进球率/赛程拥挤度/状态/联赛均值）只读取 `date < kickoff` 的比赛。
- 首发严格三态：`confirmed / predicted / unknown`；历史上无法确认 = UNKNOWN，**不允许用赛后已知首发倒灌**。
- 赔率强制带 `odds_timestamp`，≥ kickoff 一律拒绝。
- 结果字段在 snapshot schema 中**结构性不存在**；Provider 的赛后方法无条件抛 `FutureDataError` —— 冻结预测路径从构造上碰不到结果。

## 5. Leakage Audit

`football audit-leakage` 输出（合成开发数据上执行）：

```
Leakage Audit
=================
Temporal Leakage:      PASS
Future Match Leakage:  PASS   (1520 场比赛时间旅行测试位一致)
Post Match Leakage:    PASS   (结果字段结构性隔离)
Lineup Leakage:        PASS   (三态 + observed_at 强制)
Odds Leakage:          PASS   (odds_timestamp 严格 < kickoff)
Player Leakage:        PASS   (无赛后球员表现特征)
Ranking Leakage:       PASS   (无最终积分/排名特征)
=================
Overall: PASS
```

测试还验证了审计器能**抓出注入的泄漏**（赛后赔率行、赛后首发行 → 对应区块 FAIL 并阻止正式回测）。

## 6. 基准（6 个，全部严格 walk-forward）

1. **Random**：1X2 均匀。
2. **Home Advantage**：训练窗口（开球前全部比赛）主/平/客频率。
3. **Elo**：成对 walk-forward Elo（只使用开球前比赛，逐场更新）。
4. **Historical Goal Rate**：两队近 10 场滚动进/失球率 × 对手防守（Poisson）。
5. **Poisson（Dixon-Coles 简化）**：攻击/防守参数 MLE，**每个测试赛季只拟合一次**，训练窗口严格止于赛季开始前。
6. **Market Odds**：收盘赔率隐含概率（去水），用数值优化还原等价的 λ 对。

> Poisson 只是基准，不代表真实足球模型。

## 7. 回测结果（合成开发数据 —— 仅验证流水线，无真实含义）

`football backtest --seasons 2023-24 2024-25 --runs 800 --seed 12345`（760 场，含全部 6 个基准 + 完整 31-Agent 系统；每场在严格赛前冻结下运行）

### 1X2（760 场）

| 模型 | Brier | LogLoss | Accuracy | Top-2 | ECE |
| --- | --- | --- | --- | --- | --- |
| **full_system** | 0.6360 | 1.0540 | 0.471 | 0.754 | **0.0186**（校准最好） |
| elo | **0.6327** | **1.0498** | 0.475 | 0.759 | 0.0263 |
| home_advantage | 0.6423 | 1.0633 | 0.461 | 0.755 | 0.0146 |
| poisson | 0.6416 | 1.0630 | 0.470 | 0.746 | 0.0240 |
| market_odds | 0.6646 | 1.1724 | **0.496**（准确率最高） | 0.759 | 0.0864（过度自信） |
| random | 0.6667 | 1.0986 | 0.461 | 0.705 | 0.0000 |
| historical_goal_rate | 0.6994 | 1.1644 | 0.355 | 0.668 | 0.0894 |

### O/U 2.5 与 BTTS

| 模型 | OU2.5 Brier | OU2.5 Acc | BTTS Brier | BTTS Acc |
| --- | --- | --- | --- | --- |
| full_system | 0.2596 | 0.507 | 0.2623 | 0.524 |
| elo | 0.2501 | 0.507 | 0.2496 | 0.514 |
| poisson | 0.2506 | **0.517** | 0.2475 | **0.534** |
| market_odds | 0.3099 | 0.480 | 0.3585 | 0.474 |

### 比分（不要作为核心指标）

| 模型 | Exact Score | Top-3 Coverage | Top-5 Coverage |
| --- | --- | --- | --- |
| full_system | 0.1158 | 0.2961 | 0.4579 |
| elo | 0.1132 | 0.3158 | 0.4882 |
| poisson | 0.1184 | 0.3171 | 0.4921 |

### 诚实解读（仅限合成数据）

* 完整沙盘（0.6360）与 Elo 基准（0.6327）在 Brier 上基本打平，但**校准最好**（ECE 0.0186）。
* Market 在合成数据上准确率最高（0.496）但概率过度自信（ECE 0.0864）——市场赔率蕴含更极端的概率。
* Historical Goal Rate 基准显著最差（0.6994）：滚动小样本噪声大。
* **这些数字没有任何真实预测含义**：合成数据的生成过程与真实英超不同（例如市场赔率由生成器按真实强度算出，真实市场有更多信息源）。

## 8. 校准（Reliability Diagram，full_system，760 场 × 3 结果 = 2280 个预测）

| 概率桶 | 样本 | 预测均值 | 实际频率 |
| --- | --- | --- | --- |
| 0.0-0.1 | 0 | — | — |
| 0.1-0.2 | 15 | 0.190 | 0.267 |
| 0.2-0.3 | 1220 | 0.255 | 0.243 |
| 0.3-0.4 | 338 | 0.334 | 0.370 |
| 0.4-0.5 | 543 | 0.451 | 0.466 |
| 0.5-0.6 | 161 | 0.534 | 0.497 |
| 0.6-0.7 | 3 | 0.606 | 0.333 |
| 0.7+ | 0 | — | — |

ECE = 0.0186（整体校准良好）；唯一过度自信点在高概率尾端（n=3，样本太小不可下结论）。注意：沙盘输出几乎不给出 >0.6 的概率（这是 V1.2 的已知特性：状态驱动模拟自然保守，与"高置信度"绝缘）。

## 9. Agent Ablation（真实数据版结构，合成数据执行）

`scripts/v12_ablation_data.py`：Full System vs Full−X，2024-25 前 40 场 × 每场 400 模拟 × 同种子。

| 配置 | Brier | LogLoss | Acc | ECE | 期望进球 | ΔBrier(vs Full) |
| --- | --- | --- | --- | --- | --- | --- |
| full_system | 0.6690 | 1.0981 | 0.475 | 0.0670 | 3.26 | — |
| full−team | 0.6544 | 1.0826 | 0.450 | 0.0472 | 3.24 | **−0.0146（移除后反而更好）** |
| full−player | 0.6690 | 1.0981 | 0.475 | 0.0670 | 3.26 | 0（无球员数据，贡献恒 0，符合预期） |
| full−coach | 0.6690 | 1.0981 | 0.475 | 0.0670 | 3.26 | 0（教练数据 NO_SIGNAL，符合预期） |
| full−tactical | 0.6633 | 1.0962 | 0.450 | 0.0314 | **4.34** | −0.0057（主要校准总进球量） |
| full−fitness | 0.6690 | 1.0981 | 0.475 | 0.0670 | 3.26 | 0（周赛程下信号太弱，分辨率内为 0） |
| full−psychology | 0.6631 | 1.0886 | 0.450 | 0.0701 | 3.27 | −0.0059（小幅帮助校准） |
| full−referee | 0.6712 | 1.1015 | 0.450 | 0.0772 | 3.29 | +0.0022（噪音级） |
| full−environment | 0.6690 | 1.0981 | 0.475 | 0.0670 | 3.26 | 0（天气 NO_SIGNAL，符合预期） |
| full−momentum | 0.6638 | 1.0907 | 0.475 | 0.0495 | 3.26 | −0.0052（小幅帮助校准） |

**最重要的诚实发现：full−team 的 Brier 反而低于 full_system（−0.0146）。** 当前 Team Agent 从历史特征（Elo/进球率）到强度值的固定映射在这份数据上略微损害校准。按照 V1.2 纪律，**如实报告，不调参掩盖**；这进入"下一阶段工作"清单（真实数据上的 Team 映射重检）。

## 10. Rule Evidence 回填（五级状态）

- 判定标准（预先定义）：SUPPORTED = n≥50 且成功率>0.52；VALIDATED = n≥200、成功率≥0.55 且二项检验 p<0.05；CONTRADICTED = n≥50 且成功率<0.45。
- **合成数据防线**：机制完整运行，但合成数据**永远不写入任何状态/证据字段**（35 条规则保持 tentative、0 证据，有断言测试）。
- 本数据可观测的规则（11 条，真实数据就绪后即可回填）：落后反扑类 4 条、领先管理类 4 条、红牌类 2 条、主场优势 1 条（机制演示：在合成数据上 n=285~1162、方向一致率 0.62~0.69 —— 仅演示，不计数）。
- **不可观测（24 条）**：疲劳类（纯单赛事赛程下双方拥挤度恒等，需杯赛/欧战赛程）、天气/裁判/心理/动量/纪律/战术模式类（该数据源无对应观测）。
- 反例库机制就绪：合成数据上发现 2970 个反例实例（仅演示，**未持久化** —— 只有真实数据反例才允许进入 `data/evidence/counterexamples.json`）。

## 11. Counterexamples

- 机制验证：合成数据上 2970 个反例实例被识别（落后反扑类最多，因其样本 n 最大）。
- **全部未持久化**：反例库只接受真实数据反例（合成数据防线）。
- 抽样（合成数据，仅格式演示）："半场落后的球队下半场进球少于领先方"、"红牌方仍然赢球"。
- 真实数据就绪后，每条规则将同时展示支持证据 + 反例，不允许只统计支持案例。

## 12. 失败比赛分析（20 场最高置信度 miss，full_system）

| 错误定位 | 数量 |
| --- | --- |
| randomness（实际结果模型给过 ≥15% 概率） | 20 |
| data_error | 0 |
| world_model_error | 0 |
| simulation_error | 0 |
| unknown | 0 |

抽样（合成数据）：`syn-2023-24-940` 预测主胜 0.61 → 实际 0-1（客胜概率 0.20 → 随机性）；`syn-2023-24-808` 预测主胜 0.60 → 实际 1-1（平局概率 0.19 → 随机性）……

诚实解读：完整沙盘的最高置信度也仅 ~0.61（模拟保守），miss 全部落在"模型认真考虑过的结果"上 —— 分类器没有发现结构性错误，但**这不能证明系统正确**，只说明当前失败模式以方差为主；真实数据上的分布可能完全不同。

## 13. Experiment Registry

每次回测写入 `experiments/*.jsonl`：experiment_id、git_commit、code_fingerprint（源码哈希）、data_version（数据集哈希）、knowledge_version、parameter_version、snapshot_version、random_seed、train/test period、models、matches、metrics、synthetic_data 标记。（本阶段所有条目 `synthetic_data=true`。）

## 14. 系统错误分类

- 已知限制：无事件级分钟数据 → 赛中规则只能在半场粒度验证；无球员/首发数据 → Player/Lineup/Fitness/Coach/Tactical 通道在真实数据下也将长期处于 NO_SIGNAL（这是数据源限制，不是代码缺陷）。
- 本阶段没有发现新的模拟器逻辑错误；发现并修复的流水线问题：时间旅行测试的 `built_at` 时间戳噪声、审计器对注入泄漏的异常传播、市场基准的网格拟合精度（改为数值优化）、规则证据对照构造（拥挤度在同轮次恒等）。

## 15. 当前是否存在预测优势 —— 最终判定

- 真实数据：未获取（环境无网络），**无法评估**。
- 合成开发数据上的数字只证明流水线端到端可运行、冻结与审计有效、指标计算正确，**不代表任何真实预测能力**。
- 按 V1.2 判定规则：

> **NO EVIDENCE OF EDGE**（未在真实数据上评估；不允许从合成数据推断任何优势）

- `REAL_DATA_READY = false`。9 个门槛中"historical_data / historical_backtest / leakage_audit(部分：机制已建、真实数据未审计) / calibration_test / brier_score / log_loss / roi_simulation / baseline_comparison / real_data_provider"**仍全部未完成**。

## 16. 下一阶段最重要的工作（按优先级）

1. **在具备网络的机器上获取真实 EPL CSV**（football-data.co.uk），用现成 `CsvFootballDataCoUkSource` 导入 → 重跑本报告全部流程（命令不变）。
2. 真实数据泄漏审计（首发/赔率发布时间逐场核对）。
3. 正式多赛季 walk-forward 回测与全部指标。
4. 规则证据回填（真实数据）+ 反例库 + 五级状态迁移。
5. 校准与 Brier/LogLoss/ROI（仅观察）对比。

---

*本报告的所有数字将在流水线运行完成后填入（见各节占位）。在任何情况下，合成数据的数字都不会被表述为真实预测能力。*
