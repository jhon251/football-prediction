# 架构总览

## 分层

```
                    ┌──────────────────────┐
                    │   Director Agent     │
                    │   Orchestrator       │
                    └──────────┬───────────┘
                               │
                ┌──────────────┴──────────────┐
                │                             │
        ┌───────▼────────┐          ┌─────────▼────────┐
        │ Knowledge Layer │          │   Data Layer     │
        │ 足球知识/规则   │          │ Data Provider    │
        └───────┬────────┘          └─────────┬────────┘
                │                             │
                └──────────────┬──────────────┘
                               │
                     ┌─────────▼──────────┐
                     │    World Model     │
                     │    WorldState      │
                     └─────────┬──────────┘
          ┌────────────────────┼─────────────────────┐
   Team/Coach/Player      Tactical Layer       Environment
                     ┌─────────▼──────────┐
                     │ Scenario Generator│
                     └─────────┬──────────┘
                     ┌─────────▼──────────┐
                     │ Match Simulation   │
                     │ State Transition   │
                     └─────────┬──────────┘
                 ┌─────────────┼──────────────┐
              Result         Score         Goals/O-U
                     ┌─────────▼──────────┐
                     │ Risk / Confidence  │
                     │ Explanation        │
                     └─────────┬──────────┘
                     ┌─────────▼──────────┐
                     │ Learning / Review  │
                     └────────────────────┘
```

## 核心数据流

1. **Director.analyze(match_id)** 启动整个流水线。
2. **Data Layer**：`MockDataProvider`（或未来任何实现）提供球队/球员/教练/伤病/首发/历史/裁判/天气/赔率；`PreMatchFreeze` 在开球时刻冻结，冻结后任何赛后数据访问都会抛 `FutureDataError`。
3. **世界构建**（`Director.prepare_world`）：Team → Coach → Fitness → Player → Lineup → Psychology → Environment → Referee → TacticalMatchup → Opening → Space 依次运行，全部输出写回同一个 `WorldState`。
4. **意见融合**：各 Agent 对「主队实力优势」给出 `AgentOpinion`，`OpinionFusionLayer` 按 confidence × 证据强度 × impact 加权融合，并给出 agreement（用于 Confidence）。
5. **模拟**：`MatchSimulationEngine` 以该 `WorldState` 为模板，逐分钟执行：
   - Momentum 衰减 / 疲劳累积 / 控球演化 / Tempo 计算 / 危险空间刷新；
   - `EventTriggerAgent` 采样事件（射门/角球/犯规/牌/点球/伤病/乌龙/门将失误…）；
   - 每个事件更新统计量，重大事件交给 `StateTransitionAgent` 重算状态（领先/落后心态、教练反应、红牌阵型、换人效果、知识规则修饰）；
   - 45' 半场重置与教练调整；90'+ 补时；全场结束。
6. **概率统计**：从 `SimulationBatch` 统计 1X2 / 比分矩阵 / O-U / BTTS / 半全场 —— 概率层没有自己的预测，只有统计。
7. **场景**：每场模拟按事件模式归类为命名剧本原型（早进球控制、逆转、红牌改变比赛、点球、进球大战、乌龙、长尾……），原型占比即剧本概率；低频原型归入 Long Tail。
8. **风险与置信度**：UpsetRisk（相对赛前概率）、RiskAgent（10 个分解项）、ConfidenceAgent（剧本集中度 × 数据完整度 × 意见一致度 × 阵容确定性 × 概率边际）。
9. **解释与报告**：ExplanationAgent 生成人类可读分析；`MatchPredictionReport` 是最终输出契约。
10. **学习**：`PostMatchEvaluationAgent` 赛后对比预测与实际；`LearningAgent` 写 `LearningStore` 记录与 Candidate Rule，**永不自动修改核心知识**。

## 关键不变量

- **概率守恒**：1X2、比分矩阵、O/U 互补、BTTS、半全场各自求和 ≈ 1（有测试保证）。
- **可复现**：`WorldState + seed` → 完全相同的一场比赛；跨进程稳定（稳定字符串哈希派生随机流，不依赖 PYTHONHASHSEED）。
- **无未来信息**：冻结门 + 历史/伤病/首发按 `before` 截止时间过滤。
- **状态即证据**：每次状态转换 bump `state_version`，Reasoning Trace 可指向精确状态版本。
- **知识不是代码**：规则在 `knowledge/*.json`，RuleEngine 解释执行；未知数据 = unknown。
- **无状态 Agent**：输入 WorldState → 输出 AgentResult，由 Director 统一调度，无循环调用。
