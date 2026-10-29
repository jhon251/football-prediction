# PREDICTION_MATRIX — 预测矩阵（设计基线 v1.0，2026-09-13）

依据 `CURRENT_SYSTEM_AUDIT.md` 的验收结论设计。每个单元格必须同时回答六个问题：
**是否已实现 / 是否已验证 / 是否允许生产预测 / 是否允许进入 backtest / 是否允许输出最终概率 / 是否需要额外授权。**

缩写：✅=是 ❌=否 ⚠️=有条件 🚫=禁止（本阶段硬性禁止）
证据等级：E=Evidence，H=Hypothesis，U=Unknown。

状态词表（维度 D）：`VALID` `CONDITIONAL` `INSUFFICIENT_DATA` `UNKNOWN` `REJECTED` `STOP`。
外部信号状态词表：`NOT_AVAILABLE` `AVAILABLE_NOT_VALIDATED` `TIME_SAFE_VALIDATED` `REJECTED`。

---

## 维度 A × B：预测任务 × 预测模式

### A1. FTR（主胜/平/客胜）

| 模式 | 已实现 | 已验证 | 允许生产预测 | 允许进 backtest | 允许输出最终概率 | 需额外授权 | 证据等级 | 输出状态 |
|---|---|---|---|---|---|---|---|---|
| Market Baseline（M4：multi-book + Shin，preclosing） | ✅（4A 代码 + 本次验收复现） | ✅（3B/4A/4D/5.1 系列门控） | ✅ | ✅（已完成的 4A backtest + 未来 forward 评测） | ✅（概率 + 不确定性 + 溯源） | ❌ | E | VALID（输入完整且 time-safe 时） |
| Market + External Signal Candidate | ⚠️ 部分实现（仅信号状态管理；信号不改概率） | ❌（无信号通过增量门槛） | ✅ 仅作为"状态报告" | 🚫（不得将候选信号写入任何回测数据集） | ✅ 但概率=纯 M4（信号仅附状态标签） | 信号接入需预注册 | U（当前无 time_safe 数据） | CONDITIONAL |
| Validated Signal Model | ❌ | ❌ | 🚫 | 🚫 | 🚫 | ✅ 需预注册增量实验 + 完整赛季 + ΔLL≥0.003 全部门槛 | U | 不可产出（STOP if attempted） |
| Agent / Ensemble | ❌ | ❌ | 🚫 | 🚫 | 🚫 | ✅（未来设计 + 预注册） | U | 不可产出 |

### A2. OU25（大于/小于 2.5 球）

| 模式 | 已实现 | 已验证 | 允许生产预测 | 允许进 backtest | 允许输出最终概率 | 需额外授权 | 证据等级 | 输出状态 |
|---|---|---|---|---|---|---|---|---|
| Market Baseline（O2：B365 + Shin，preclosing） | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | E | VALID |
| Market + External Signal Candidate | ⚠️ 同 A1 | ❌ | ✅ 仅状态报告 | 🚫 | ✅ 概率=纯 O2 | 同 A1 | U | CONDITIONAL |
| Validated Signal Model | ❌ | ❌ | 🚫 | 🚫 | 🚫 | ✅ | U | 不可产出 |
| Agent / Ensemble | ❌ | ❌ | 🚫 | 🚫 | 🚫 | ✅ | U | 不可产出 |

### A3. 其他市场（扩展位）

| 模式 | 已实现 | 已验证 | 允许生产预测 | 允许进 backtest | 允许输出最终概率 | 需额外授权 |
|---|---|---|---|---|---|---|
| 任意未列市场（BTTS、让球、比分等） | ❌ | ❌ | 🚫 | 🚫 | 🚫 | ✅：必须先有对应市场基线的预注册实验；**不得假装已验证**。冻结 2A/2B 中 AH/球未列价等字段存在但未经验证，一律 UNKNOWN |

---

## 维度 C：数据状态 × 可行动作

| 数据状态 | 定义 | FTR/OU25 动作 | 输出状态 | 证据标签 |
|---|---|---|---|---|
| Market available (preclosing, time-safe) | ≥1 个有效庄家赔率组；FTR M4 需 ≥2 庄家，O2 需 B365 对（或回退链命中） | 计算 M4/O2 | VALID / CONDITIONAL（回退或时间戳缺失时） | E |
| Market missing | 无任何 preclosing 赔率（或全部格式非法） | 不计算，概率=null | INSUFFICIENT_DATA | U |
| Market unsafe（retrieved_at ≥ kickoff 或 closing 输入） | 时间安全门失败 | 拒绝计算 | REJECTED | E |
| Understat forward time-safe | `dq_namespace=forward` 且 `dq_status=time_safe` 且 `retrieved_at < kickoff_utc` 且 DQ 通过 | 仅作候选信号记录，不改概率 | AVAILABLE_NOT_VALIDATED | H（增量价值未验证） |
| Understat historical retro | 2015–26 回溯数据 / `historical_retro` 标签 / 冻结季数据 | 永久排除出正式预测 | REJECTED（若被注入） | E（隔离已验证） |
| External signal unknown | `generated_at`/`published_at` 缺失 | 保持 UNKNOWN，不推断 | UNKNOWN | U |
| Insufficient data | 关键字段缺失（联赛/时间/赔率全缺） | 不计算 | INSUFFICIENT_DATA | U |
| Leakage detected | 检出 label 字段/closing 键注入/冻结指纹漂移 | 全部停止 | STOP | E |

---

## 维度 D：输出状态语义（全模块统一）

| 状态 | 含义 | 概率字段 |
|---|---|---|
| VALID | 基线方法命中（M4/O2），时间安全，输入完整 | 真实概率 |
| CONDITIONAL | 命中回退链（如 M4→M2）、或时间戳缺失（time-safe=UNKNOWN）、或数据部分缺失 | 真实概率 + 降级说明 |
| INSUFFICIENT_DATA | 无法构造任何已验证方法的输入 | **null（绝不伪造）** |
| UNKNOWN | 输入存在但语义不明（如信号时间戳缺失） | null 或仅基线概率 |
| REJECTED | 时间安全门/输入安全门失败（closing 输入、retrieved_at≥kickoff、retro 注入） | null |
| STOP | 冻结指纹漂移 / 检出泄漏 / 结构性故障 | null + 故障详情 |

---

## 维度 E：研究证据等级映射

| 项 | 等级 | 依据 |
|---|---|---|
| M4/O2 市场基线概率 | **Evidence** | 3B/4A（本次独立复现）+ 4D/5.1 系列门控 |
| M4 优于 M1（多庄+Shin 增量） | Evidence | 4A（LL 0.9719→0.9707，ECE 0.2921→0.2859） |
| 校准映射（isotonic 等） | Evidence（关闭） | 4D + 5.1-A 全 CLOSE → 生产预测不叠加任何校准层 |
| CLOSING 赔率作为输入 | Evidence（亚门槛，CONDITIONAL） | 5.1-D → 不进入 SAFE 输入 |
| Understat forward xG 增量价值 | **Hypothesis** | 5.3 预注册门槛未评估（time_safe=0） |
| Lineup 前向信号 | Unknown | DATA-006 time_safe 样本≈0 |
| 任何"Agent 已超过 Market" | **禁止宣称** | 无实验支持（phase5_review 明示市场层是唯一已验证预测层） |

---

## 生产门禁总表（矩阵不变式）

1. 只有 Market Baseline (M4/O2) 允许输出最终概率，且必须附带溯源（庄家、去抽水法、Shin z、时间戳、缺失字段）。
2. 外部信号在任何情况下只能改变**状态字段**，不能改变**概率字段**，直到增量门槛全通过并获预注册授权。
3. `TIME_SAFE_VALIDATED` 状态只能由"已验证信号注册表"（当前不存在）授予；代码不得硬编码。
4. 任何回退（M4→M2→单庄、O2→O4→单庄）都必须在输出中留痕并降级为 CONDITIONAL。
5. 所有缺失 → `INSUFFICIENT_DATA`/`UNKNOWN`，概率=null；禁止随机/静态/默认概率。
6. 检测到泄漏或冻结指纹漂移 → STOP，只报告不修复。
