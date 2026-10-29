# Football Match Digital Twin & Simulation System V1（足球沙盘推演系统）

> **Predict less, simulate more.** 先问「比赛可能如何发展」，再问「每条路径有多大可能」，最后从所有路径统计出概率。

这是一个**比赛沙盘推演引擎**，而不是传统的「输入数据 → 输出主胜63%」黑盒预测器：

## 研究主线地图（两套系统，勿混淆）

本仓库包含**两套相互独立的系统**，回答两类不同的问题：

| | 系统 A：沙盘模拟引擎 | 系统 B：时间安全预测研究主线 |
|---|---|---|
| 位置 | `src/football_simulation/` | `backtest_output/`（Phase 2A → 5.3） |
| 数据 | 合成 mock（`is_synthetic=true`） | 真实历史冻结集 v1.1.0 + 前向采集 |
| 回答的问题 | "比赛可能如何发展"（过程模拟） | "胜/平/负与大小球概率多少"（预测，严格时间安全） |
| 预测地位 | **不是**预测器：35 条规则全 tentative，概率输出是模拟产物 | 唯一已验证预测器 = 市场基线 M4/O2（`src/football_prediction`，冻结集 test split 3504 场与 Phase4A 0 mismatch） |
| 当前位置 | V1.2 完成，无后续计划 | Phase 5.3-P1-C：Understat forward xG 累积中（time_safe 207 场，门槛 ≥300/联赛-季 × 5 + 完整赛季） |

**阅读指引**：想了解预测研究现状，从 `backtest_output/experiments/phase5_review/PHASE5_REVIEW_ARCHITECTURE_AND_ROADMAP.md`、根目录 `CURRENT_SYSTEM_AUDIT.md`、`PREDICTION_MATRIX.md` 开始；想一键预测未开赛的比赛（胜平负概率 + 比分概率矩阵），见 **[一键赛前预测 WebApp](docs/PREDICTION_WEBAPP.md)**（`python -m football_prediction.cli serve`）；本 README 其余部分描述的是系统 A。

**系统 B 当前硬门槛**：每联赛 ≥300 场 time_safe + 完整一赛季 → 预注册增量实验 → 通过全部预注册门槛后才允许任何信号进入预测；市场外信号（xG/lineup）目前均为候选/未验证状态。

```
Data → World Model → Team/Coach/Player/Tactical State
     → Scenario Generation → State Transition → Event Simulation
     → Monte Carlo Aggregation → Probability Output → Risk / Explanation
```

## 快速开始

```bash
# 依赖：Python 3.10+、pydantic>=2、numpy（已内置所需的一切，无其它强制依赖）
pip install pydantic numpy          # 仅当尚未安装

# 生成合成 mock 数据（fixtures，仅用于开发/测试）
python scripts/generate_fixtures.py

# CLI
python -m football_simulation.cli analyze match-demo-001 --runs 10000
python -m football_simulation.cli simulate match-demo-001 --runs 10000
python -m football_simulation.cli scenarios match-demo-001
python -m football_simulation.cli trace match-demo-001
python -m football_simulation.cli post-match match-demo-000
python -m football_simulation.cli validate          # V1.1 Football Reality Validation 面板
python -m football_simulation.cli backtest --seasons 2023-24 2024-25 --runs 1000   # V1.2 walk-forward 回测
python -m football_simulation.cli audit-leakage      # V1.2 泄漏审计（FAIL 时禁止正式回测）
python -m football_simulation.cli backfill-evidence  # V1.2 规则证据回填（合成数据不写入）
python -m football_simulation.cli experiments        # V1.2 实验注册表
python -m football_simulation.cli demo
python -m football_simulation.cli api --port 8000

# 测试
python -m unittest discover -s tests
```

安装为命令行工具（可选）：

```bash
pip install -e .
football analyze match-demo-001 --runs 10000
```

## 输出示例（标准 V1 输出）

* **胜平负**：主胜 / 平局 / 客胜（内部 0~1，展示层转百分比）
* **最可能比分** Top 10（0~6+ 截断的完整比分矩阵）
* **大小球**：O/U 0.5 ~ 5.5 六条线 + 期望总进球
* **BTTS**：Yes / No
* **半全场**：9 种组合 + 半场 1X2
* **最可能比赛剧本** Top 5（带概率、时间线、关键事件、比分路径）
* **爆冷风险**：低 / 中 / 高 / 极高 + 爆冷方向 + 概率 + 原因 Top 5
* **风险分解**：阵容 / 伤病 / 体能 / 战术 / 心理 / 裁判 / 天气 / 模型不确定性 / 剧本离散度 / 数据质量
* **预测失效条件**、**Confidence**（High/Medium/Low + 理由）、**Reasoning Trace**

## 核心设计

| 层 | 组件 |
| --- | --- |
| 世界模型 | `WorldState`（强类型 Pydantic，每次状态转换产生带版本号的新快照） |
| 知识层 | `KnowledgeBase` + `RuleEngine`（足球知识是**数据**，不是代码；UNVERIFIED/TENTATIVE/VALIDATED/DEPRECATED 生命周期） |
| 数据层 | `DataProvider` 标准接口 + `PreMatchFreeze`（赛前冻结，杜绝未来信息泄漏）+ 合成 Mock Provider |
| 状态机 | `StateTransitionAgent`（进球/红牌/点球/伤病/换人/半场 → 重算 WorldState） |
| 事件引擎 | `EventTriggerAgent`（事件概率由状态共同决定，受 Event Dependency Rules 约束） |
| 模拟引擎 | `MatchSimulationEngine.simulate_match(seed)` / `simulate_n_matches(n)`（可复现、收敛检测、支持 1k~100k） |
| 场景引擎 | `MatchScriptAgent`（从模拟结果聚类为剧本）+ `ScenarioRankingAgent`（保留长尾） |
| 概率层 | 胜平负 / 比分矩阵 / O-U / BTTS / 半全场 —— **全部从模拟结果统计**，无独立预测 |
| 风险层 | Upset（相对赛前概率定义）/ 分解风险 / Confidence（剧本集中度等） |
| 学习层 | `LearningAgent`（只写记录与 **Candidate Rule**，绝不自动改核心规则）+ `PostMatchEvaluationAgent` |
| 编排 | `DirectorAgent`（调度、协调、冲突处理、质量控制）+ `OpinionFusionLayer` |

## Agent 清单（V1 全部实现）

Team / Coach / Player / Lineup / Fitness / Psychology / Environment / Referee /
TacticalMatchup / Opening / Possession / Space / Tempo / Momentum /
EventTrigger / Substitution / StateTransition / MatchScript / ScenarioRanking /
Counterfactual / ResultProbability / ScoreProbability / GoalsOU / HTFT /
UpsetRisk / Risk / Confidence / Explanation / Learning / PostMatchEvaluation /
Director。

所有 Agent 无状态（输入 WorldState → 输出 `AgentResult`），由 Director 统一调度，互不直接调用。

## 数据说明

* V1 **不实现**数据采集（爬虫/API/供应商），只定义标准 `DataProvider` 接口。
* 仓库内置的是**合成 mock 数据**（`scripts/generate_fixtures.py` 生成），只用于开发与测试，不含任何真实足球统计。
* 联赛集合是**数据**（`competitions.json`），内置五大联赛并预留葡超/荷甲/欧冠/欧联/欧协联/国家队，扩展无需改代码。
* 未知数据一律 `unknown`，绝不伪造；数据质量直接影响 Confidence。

## 架构文档

* [架构总览](docs/architecture.md)
* [Agent 详解](docs/agents.md)
* [知识层与规则引擎](docs/knowledge.md)
* [使用指南（CLI / API / 配置）](docs/usage.md)
* **[V1.1 足球真实性验证报告](docs/V1_1_REALITY_VALIDATION_REPORT.md)**（规则审计、因果方向、异常检测、Agent 贡献、修复的 9 处因果链缺陷、`REAL_DATA_READY=false`）
* **[V1.2 历史回测与数据完整性报告](docs/V1_2_HISTORICAL_BACKTEST_REPORT.md)**（HistoricalMatch schema、PreMatchFreeze 2.0、时间旅行与泄漏审计、6 基准、walk-forward 回测、五级规则证据、反例库、实验注册表）

## V1.2 现状声明

* 本环境**无网络**，真实英超数据未能获取；`football backtest` 使用**明确标注的合成开发数据**（每条 `is_synthetic=true`），数字不代表任何真实预测能力。
* 真实数据就绪路径：下载 football-data.co.uk 的 `E0.csv` → `CsvFootballDataCoUkSource` 导入 → 同一命令直接跑正式回测。
* 判定：**NO EVIDENCE OF EDGE**（未在真实数据上评估）；`REAL_DATA_READY=false`。
* 数据完整性：`audit-leakage` 7 项 PASS；时间旅行测试位一致；合成数据**永远不能写入规则证据/状态**（35 条规则保持 tentative、0 证据）。
* `REAL_DATA_READY = false`：真实数据 Provider / 历史回测 / 泄漏审计 / 校准 / Brier / LogLoss / ROI / 基准对比 9 个门槛全部未完成。
* 全部 35 条知识规则为 `assumption`（开发期假设），**0 条 validated** —— 任何概率输出都不是真实预测。
* 不接入博彩/下注功能；ROI 仅作为观察指标，禁止按结果调参。

## 目录结构

```
src/football_simulation/
├── agents/        # 全部 Agent（base/director/team/.../fusion）
├── core/          # rule_engine / state_machine / event_engine / scenario_engine / simulation_engine / rng
├── models/        # 强类型领域模型（WorldState、实体、事件、场景、报告）
├── knowledge/     # 知识包（规则/战术模式/事件基线参数，JSON）
├── data/          # DataProvider 接口、冻结门、竞赛注册表、Mock Provider + fixtures + historical/（V1.2 schema/快照/特征/数据源）
├── backtest/      # V1.2 回测（基准/指标/runner/实验注册表/泄漏审计/失败分析）
├── evaluation/    # 学习/赛后评估 + V1.1 真实性验证 + V1.2 规则证据回填/反例库
├── app/           # HTTP API（纯标准库实现）
├── cli.py         # 命令行
└── config.py      # 配置系统（config/default.json）
```
