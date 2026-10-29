# 知识层与规则引擎

## 原则

> 足球知识不是代码。知识是带来源、置信度与生命周期的数据。

```text
KnowledgeRule
↓
RuleEngine（判断条件 → 计算影响 → 返回 Modifier）
↓
State Modifier（应用于 WorldState）
```

修改规则不需要改代码 —— 编辑 JSON 知识包即可；学习系统也只能提出 Candidate Rule，不能直接修改核心规则。

## 知识包（`knowledge/*.json`）

| 文件 | 内容 |
| --- | --- |
| `default_knowledge.json` | 27 条状态转换规则：领先降速/落后反扑/末段管理/红牌劣势/心理反馈/天气影响/半场重置等 |
| `tactical_patterns.json` | 8 条战术对位模式：高压vs弱出球、低位vs控球、反击vs高位防线、边路vs窄防守、三中卫vs双前锋、内收边卫vs宽压迫、定位球错配、中场质量差 |
| `event_defaults.json` | 事件基线参数：进攻强度、射门质量分布、犯规/牌/点球/伤病/失误/VAR 概率、补时、势头衰减、控球惯性 + 15 条 Event Dependency Rules |

## KnowledgeRule 结构

```json
{
  "rule_id": "R_MENTALITY_LEAD_TEMPO",
  "name": "leading_team_tempo_moderation",
  "category": "rules",
  "status": "tentative",            // UNVERIFIED | TENTATIVE | VALIDATED | DEPRECATED
  "source": "internal_default_v1",
  "confidence": 0.55,
  "evidence_count": 0,
  "condition": {"all": [
    {"field": "mentality_home", "op": "eq", "value": "leading"},
    {"field": "home_coach.reaction_to_leading", "op": "eq", "value": "defensive"}
  ]},
  "effects": [
    {"target": "home_tactical_state.tempo_contribution", "op": "add",
     "value": -0.15, "confidence": 0.55, "reason": "leading + defensive coach"}
  ]
}
```

* 条件：叶子 `{field, op, value}`（`eq/ne/gt/gte/lt/lte/in/contains/known/unknown`）+ 组合子 `all/any/not`；支持 `WorldState` 计算字段（`minute`、`goal_diff_home`、`mentality_home`、`players_on_pitch_home`、`is_late_game`…）。
* 效果：`add / multiply / set / clamp01`，作用于任意点分路径；应用时 copy-on-write，绝不原地修改共享状态。
* 生命周期：V1 内置规则全部 `tentative`（无真实比赛证据）；LearningAgent 累积 evidence 后可升级为 `validated`，前提是人工验证。

## 事件依赖规则（Event Dependency Rules）

防止不合理黑天鹅：例如一分钟内三红牌、两乌龙、五点球。每条规则给出：

```json
{"event_type": "red_card", "max_per_match": 4, "max_per_team": 2,
 "max_per_minute": 1, "cooldown_minutes": 10}
```

结构性依赖（乌龙必须由防守失误路径触发、门将失误必须先有射门、二黄必须由已染黄球员再犯规触发）在 EventTriggerAgent 的采样路径中实现。

## 未知即未知

任何不存在的数据点（伤病、首发、天气、裁判、球员状态）在系统中是 `unknown`/`None`，绝不猜测；DataQuality 层统计未知项并压低 Confidence。规则可以用 `{"op": "known"}` / `{"op": "unknown"}` 显式区分。

## 未来扩展

* 新知识包直接放入 `knowledge/`，Director 的 `load_all_knowledge()` 自动聚合。
* 事件基线参数全部可调，未来可用历史数据学习（LearningAgent 的候选规则即为此设计）。
