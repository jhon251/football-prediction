# DIAG-004：Elo 误差归因分析（EXP-DIAG-EPL-004）—— 实验设计

> **状态：设计阶段（本文件）。执行需另行指令；执行前本文件作为预注册（pre-registration），
> 所有阈值、代理定义、判定规则在执行期不得修改。**
> 只回答一个问题：**「当前 Agent 是否拥有 Elo 没有的信息？」**
> 纪律：诊断性质；不修改生产代码、35 条规则、config 与数据层；不进入 V1.3；
> 本文件**不包含**任何模型升级/修复方案。

---

## 0. 背景与先验（不预判，只登记）

- 冻结基线 EXP-REAL-EPL-BASE-001（380 场）：Elo Brier 0.6310 / accuracy 0.4711；
  full_system Brier 0.6592 / accuracy 0.4184。
- DIAG-001（120 场样本）：Elo 错而 Team 对 0.0083，Team 错而 Elo 对 0.0833
  （Elo 纠错频次是反向的 10 倍）；Team−Elo 残差与结果相关 **−0.2624（z≈−2.9σ）**。
- DIAG-001（冻结 380 场）：`elo_right_full_wrong` n=27，`full_right_elo_wrong` n=7。
- DIAG-003（380 场）：team_only 0.6539、team_psychology 0.6520 均方向性优于 full 0.6600，
  但仍弱于 Elo 0.6310。
- 上述数字是**先验观察**；本实验在 380 场上用预注册的统计程序独立判定，不因先验预判结论。

## 1. 四类比赛的精确定义（可复现）

对每个被测 Agent 配置（见 1.3），逐场与 Elo 的 argmax 判定交叉：

| 类别 | 记号 | 定义 |
| --- | --- | --- |
| Elo 正确比赛 | E+A* | Elo 正确（无论 Agent 对错）；再分为 E+A+ 与 E+A− |
| Elo 错误但 Agent 正确 | **E−A+** | Elo 的 top-1 ≠ 实际结果，且 Agent 的 top-1 = 实际结果（**增量信息候选**） |
| Elo 错误且 Agent 错误 | E−A− | 两者 top-1 均 ≠ 实际结果 |
| Elo 正确但 Agent 错误 | E+A− | Elo top-1 = 实际结果，Agent top-1 ≠ 实际结果（Agent 损害 Elo 信息） |

- 「正确」= 实际结果（三分类：home_win / draw / away_win）∈ {argmax 概率并列的集合}；
  **并列规则**：若最高概率并列多结果且实际结果在其中 → 判正确（预注册）。
- 样本：全部 380 场（数据按赛季时间顺序）；另附 120 场固定样本子集供与 DIAG-001 对照。
- 敏感性分析（预注册，不改变主判定）：
  1. top-2 正确（实际结果 ∈ 概率前二）重算四分类；
  2. 弃用 argmax，改用概率层面的连续检验（见第 4 节 S2 的 Murphy 分解）。

### 1.3 被测 Agent 配置（三个主配置 + 一个补充）

| 配置 | 来源 | 备注 |
| --- | --- | --- |
| full_system | 冻结基线 records.json（380 场） | 生产全流水线 |
| team_only | DIAG-003 `preds_part2.json`（380 场，400 模拟，seed 20240101） | 纯 Team 通道 |
| team_psychology | DIAG-003 `preds_part1.json`（380 场） | DIAG-001 最优配置 |
| team_only_linear（补充） | DIAG-003 `preds_part2.json` | 加性探针臂，仅作补充观察，不进入主判定 |

**无需任何新模拟**：全部预测已存在于冻结/缓存产物，执行期只做确定性分析。

## 2. Elo 错误样本的三型分类（代理定义，预注册）

### 2.0 数据现实（决定代理而非真值分类）

- 真实伤停名单/首发阵容：**DATA_UNAVAILABLE**。冻结记录 `unknowns` 的四个字段
  （away_lineup / home_lineup / injuries / weather）对全部 380 场恒定出现 → **零变异**，
  不能作为分类变量。
- 真实比赛事件（红牌/点球/乌龙/关键换人）：**DATA_UNAVAILABLE**（数据层无事件级数据）。
- 可用的 Elo 外部信息：`congestion_14d`（赛程拥挤度，Elo 不使用）、
  半场实际比分（`actual_ht_*`）、双模型 expected_goals。
- 因此三型分类**全部基于预注册代理**；无法落入任何代理的场次归入 **UNCLASSIFIED**，
  占比如实报告，不做强行归因。

### 2.1 三型代理定义（阈值在执行期冻结，不得事后挪动）

设 `cong = max(congestion_14d_home, congestion_14d_away)`，
`tact = |tactical_advantage_nohome|`（重建层，主场剥离版），
`tact_p80` = 380 场重建层 `tact` 的 80 分位（执行期一次算定并冻结），
`trans_gap = |transition_risk_home − transition_risk_away|`，
`score_surprise = |实际总进球 − full_system.expected_goals|`，
`ht_reversal = sign(半场主−客进球) ≠ 0 且 ≠ sign(全场主−客进球)`。

| 类型 | 代理规则（在 Elo 错误样本内判定） | 依据 |
| --- | --- | --- |
| 随机事件型 | `score_surprise ≥ 2.0` **或** `ht_reversal` | 比分显著偏离双模型预期 / 半场被逆转，指向不可建模的赛场事件 |
| 战术/风格型 | `tact ≥ tact_p80` **或** `trans_gap ≥ 0.15` | 对位/转换风险极端，指向风格性原因 |
| 信息缺失型 | `cong ≥ 3` **或** `|elo_diff| ≤ 15` | 赛程拥挤（Elo 不使用的信息）/ Elo 低把握区（伤停等缺失信息最可能改变结论的区域） |
| UNCLASSIFIED | 以上皆不满足 | 如实记录，不猜测 |

- **优先级（每场至多一类）**：随机事件型 > 战术/风格型 > 信息缺失型 > UNCLASSIFIED。
- **诚实性备注（预注册）**：战术/风格型所用信号是 TeamState（Elo 派生）的产物
  （DIAG-001 已证），若该类在 Elo 错误组过度表达，其解读是「Elo 派生信号在 Elo 错误时
  呈极端/反向」，而非「独立风格信息」；信息缺失型没有真实伤停数据，只能证明
  「赛程/低把握区」与 Elo 错误的关联，不能证明伤停因果。
- **对照组**：对 **Elo 正确比赛** 应用同一套代理规则，计算各型占比；
  用 Fisher 精确检验判断某型是否在 Elo 错误组显著过度表达（见第 5 节判据）。

## 3. 需要的数据字段（来源与可用性）

| 字段 | 来源 | 可用性 | 用途 |
| --- | --- | --- | --- |
| match_id / kickoff / 主客队 / 实际比分 | `data/historical/epl_2025_26.json` | 已存在 | 四分类、顺序、对照组 |
| 实际半场比分 `actual_ht_home/away_goals` | 冻结 `records.json` | 已存在 | 随机事件型代理（ht_reversal） |
| elo 1X2 概率 | 冻结 `records.json`（predictions.elo） | 已存在（确定性） | E 侧判定 |
| full_system 1X2 + expected_goals | 冻结 `records.json` | 已存在 | Agent 侧判定 + score_surprise |
| team_only / team_psychology 1X2（380 场） | DIAG-003 `preds_part1/2.json` | 已存在 | Agent 侧判定 |
| `unknowns` 列表 | 冻结 `records.json` | 已存在但**零变异** | 仅作数据可用性声明 |
| `congestion_14d`（主/客） | 诊断重建层（`reconstruct_prematch_layer`） | 已存在 | 信息缺失型代理 |
| `tactical_advantage_nohome`、`transition_risk_*` | 诊断重建层 | 已存在 | 战术/风格型代理 |
| `elo_diff` | 诊断重建层 | 已存在 | 信息缺失型代理（低把握区） |
| 真实伤停/首发名单 | — | **DATA_UNAVAILABLE** | 无法真值分类，仅代理 |
| 真实比赛事件（红牌/点球/乌龙/换人） | — | **DATA_UNAVAILABLE** | 随机事件型仅代理 |
| 杯赛/欧战赛程、旅途、教练变更、转会 | — | **DATA_UNAVAILABLE** | 相关子分析标 INSUFFICIENT EVIDENCE |

## 4. 统计方法（全部预注册）

1. **四分类计数与置信区间**：各类计数/占比（n=380 与 120 子集），
   Clopper-Pearson 双侧 95% CI。
2. **McNemar 对称性（S3）**：以 E+A− 与 E−A+ 为不一致对，
   二项精确双侧检验 `P(E−A+ ≥ observed | 不一致对总数, 0.5)`。
   若 E−A+ 显著多于 E+A− → Agent 纠错 Elo 的方向不对称。
3. **置换检验（S1）**：H0 = Agent 预测对实际结果没有超出 Elo 的信息。
   固定 Elo 与 Agent 的全部预测，将 380 场的**实际结果向量**随机置换
   （permutation seed = **20240101**，10,000 次），统计置换下
   `#(E−A+) ≥ 观测值` 的占比作为单侧 p。
4. **Murphy 分解的条件信息检验（S2，概率层面，主检验）**：
   对每个被测配置、每场的实际结果 y 计算
   `A = P_agent(实际结果)`、`E = P_elo(实际结果)`，
   `Brier_A − Brier_E = E[(A−E)²] + 2·E[(A−E)(E−y)]`。
   - `E[(A−E)²]` = 噪声项（恒 ≥0）；
   - `C = E[(A−E)(E−y)]` = 信息项：C<0 表示 Agent 相对 Elo 的偏离**朝正确方向**。
   置换检验：实际结果向量随机置换（同 seed 20240101，10,000 次），
   单侧 p = P(C_置换 ≤ C_观测)。DIAG-001 的负残差相关对应 C>0（反信息）；
   本检验给出带推断的正式版本。
5. **Elo 错误子集内的条件分离**：在 Elo 错误场次中报告
   Agent 对实际结果的平均概率 vs 其余两结果的平均概率（描述性）。
6. **三型分类检验**：对每型，比较 Elo 错误组与 Elo 正确组的该型占比，
   Fisher 精确检验（单侧，错误组过度表达方向）。
7. **多重检验**：3 个主配置 × 3 个主检验（S1/S2/S3）= 9 次；
   预注册显著性水平 α = 0.05/9 ≈ **0.0056**（Bonferroni），
   报告原始 p 与校正后判定。

## 5. 成功判据（判定规则，执行期不得挪动）

对主问题「Agent 是否拥有 Elo 没有的信息」，仅当**任一主配置**满足下列**任一**条件时
回答「是（有证据）」：

- **S1**：置换检验 p < 0.0056，且 E−A+ 计数 > 置换分布中位数；
- **S2**：Murphy 信息项 C < 0 且置换 p < 0.0056；
- **S3**：McNemar 检验 p < 0.0056 且方向为 E−A+ > E+A−。

若三个条件均不满足 → 结论措辞固定为：
**「INSUFFICIENT EVIDENCE：未发现 Agent 拥有 Elo 之外预测信息的证据」**
（并注明：无证据 ≠ 证明没有；这会是「信息增量不足」主线（DIAG-003 结论）的又一支柱）。

三型分类的归因判据：某型在 Elo 错误组显著过度表达（Fisher p < 0.05，原始 p）
→ 该型记录为「与 Elo 错误相关的可解释类别」；否则该型标 INSUFFICIENT EVIDENCE。
**UNCLASSIFIED 占比如实报告**；若 UNCLASSIFIED 占比 ≥ 40%，三型分类整体结论
降级为 INSUFFICIENT EVIDENCE（代理覆盖不足，不强行解释）。

## 6. 停止条件

1. 只执行第 4 节预注册的分析（纯确定性分析冻结/缓存产物 + 重建层；
   **无新模拟、无新特征、无模型改动、无参数调整**）。
2. 任何字段缺失或零变异 → 相关子分析标 INSUFFICIENT EVIDENCE 并继续；
   **不得在执行期发明未注册的代理或阈值**。
3. 写完报告（含四分类表、S1–S3 结果、三型分类表、UNCLASSIFIED 占比、
   固定措辞结论）后**停止**；不进入修复、不提模型升级方案、不进入 V1.3。

## 7. 执行期产物（预注册）

- 输出目录：`backtest_output/diag_004_elo_error/`
  - `classification.json`（四分类逐场标注 + 三型代理标注）
  - `stats.json`（S1/S2/S3 置换与检验结果、置信区间、Fisher 检验）
  - `baseline_manifest_*.json`（冻结目录完整性哈希，沿用既有工具）
  - `experiments.jsonl`（注册条目 **EXP-DIAG-EPL-004**）
- 报告：`docs/DIAG_004_ELO_ERROR_ATTRIBUTION.md`
- 执行成本：零新模拟；预计运行时间 < 5 分钟（含 10,000×3 次置换）。

---

*本设计不包含任何模型升级/修复建议；执行以本文件为唯一依据。*
