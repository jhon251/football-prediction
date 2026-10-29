# Agent 详解

所有 Agent 实现同一契约（`agents/base.py`）：

```python
class BaseAgent(Generic[T]):
    name: str
    def run(self, context: AgentContext) -> AgentResult[T]: ...
```

`AgentContext` 携带 `match_id / request / world / data / knowledge / matchup / batch / input_version`；
`AgentResult` 携带 `agent_name / timestamp / match_id / input_version / output / confidence / evidence / reasoning / warnings / impact`。

Agent **无状态**、**互不直接调用**，统一由 Director 调度（避免循环依赖，便于并行化与测试）。

## 赛前 Agent

| Agent | 输入 | 输出 | 说明 |
| --- | --- | --- | --- |
| `TeamAgent` | TeamProfile + 近期战绩 | `TeamState` | 风格/打法/反应模式 + 近期状态有界修正；不是 ELO 抄写 |
| `CoachAgent` | CoachProfile + 双方实力 + 重要性 | `CoachState` | 本场 gameplan（阵型/压迫/防线/节奏/风险）；不同教练产生不同策略与反应 |
| `PlayerAgent` | PlayerProfile + 球队风格 | `PlayerState` | 技术/身体/心理/行为 + 战术契合度 + 疲劳敏感度 |
| `FitnessAgent` | 赛程密度/休息天数/年龄/旅行 | `FitnessState` | 每人疲劳（个体敏感度）× 团队疲劳曲线 × 末段下滑；禁止一刀切 -10% |
| `PsychologyAgent` | 比赛背景/近期走势/重要性 | `PsychologicalState` | 信心/压力/动机/冷静/风险偏好/决策质量；影响风险、节奏、末段行为 |
| `EnvironmentAgent` | 天气/场地/海拔 | `WeatherState` | impact = low/medium/high；系数可学习，不无脑放大 |
| `RefereeAgent` | RefereeProfile | `RefereeMatchState` | 只改变事件概率（牌/点球/VAR），绝不决定结果 |
| `TacticalMatchupAgent` | 双方 TeamState + 战术模式知识 | `TacticalMatchupState` | 高压 vs 出球、低位 vs 控球、反击 vs 高位防线、边路 vs 窄防守等；输出优势/危险区域/转换风险/机会创造修正 |
| `OpeningAgent` | 教练攻击性 + 心理 + 对位 | `OpeningState` | 0-15 分钟：谁抢开局、压迫强度、早期进球风险 |
| `LineupAgent` | 首发/伤病/轮换倾向 | `LineupState` | 核心缺阵、关键位置缺阵、轮换、年轻首发、替补门将识别；影响强度与 Confidence |
| `SpaceAgent` | 对位 + 实时比分/红牌 | `List[DangerousSpace]` | 危险区域随比赛动态变化 |

## 赛中 Agent（引擎内调用）

| Agent | 职责 |
| --- | --- |
| `PossessionAgent` | 控球目标（对位+比分+牌+疲劳+势头）+ 惯性演化 |
| `TempoAgent` | very_low ~ very_high，由比分/战术/疲劳/心理/时间/牌/重要性驱动 |
| `MomentumAgent` | 事件驱动的势头转移 + 每分钟衰减 + 均值回归（不是“谁射门多”） |
| `EventTriggerAgent` | 每分钟事件强度 + 事件采样；受全部状态影响；Event Dependency Rules 约束 |
| `SubstitutionAgent` | 何时换/换谁/为什么：领先防守换人、落后进攻换人、疲劳/黄牌/战术克制/伤病换人 |
| `StateTransitionAgent` | 状态机：进球→心态/教练反应/心理；红牌→阵型/强度；换人→攻防修正；半场→重置与调整；之后由 RuleEngine 追加知识规则修饰 |

## 场景 / 模拟 / 概率 / 风险 Agent

| Agent | 职责 |
| --- | --- |
| `MatchSimulationEngine` | 0→90+ 逐分钟模拟；`simulate_match(seed)` 可复现；`simulate_n_matches(n)` 蒙特卡洛（默认 10000，支持 1k~100k）；收敛检测 |
| `MatchScriptAgent` | 把模拟批次按事件模式归类为命名剧本原型（20+ 种），原型占比 = 剧本概率 |
| `ScenarioRankingAgent` | 按 概率×一致性×可信度 排序；低频归入 Long Tail |
| `CounterfactualAgent` | 若无此球/无红牌/无伤病… 重模拟并输出概率差值 |
| `ResultProbabilityAgent` | 1X2（纯统计） |
| `ScoreProbabilityAgent` | 比分矩阵（0~6+ 截断） |
| `GoalsOUProbabilityAgent` | O/U 0.5~5.5、期望总进球、BTTS |
| `HTFTProbabilityAgent` | 9 种半全场 + 半场 1X2 |
| `UpsetRiskAgent` | 爆冷 = 相对赛前概率定义；输出等级/方向/概率/驱动因素 |
| `RiskAgent` | 10 项分解风险 + overall |
| `ConfidenceAgent` | 剧本集中度/数据完整度/意见一致度/阵容确定性/概率边际 —— 不是 max(概率) |
| `ExplanationAgent` | 人类可读：为什么/怎么踢/双方因素/转折点/失效条件/爆冷原因 |
| `LearningAgent` | 赛后记录 + Candidate Rule 提案（不改核心规则） |
| `PostMatchEvaluationAgent` | 结果/比分/剧本/战术/事件/O-U/爆冷检测 8 项准确度 |
| `DirectorAgent` | 总调度：初始化→数据→Agent→WorldState→场景→模拟→概率→风险→解释→报告 + Reasoning Trace |
