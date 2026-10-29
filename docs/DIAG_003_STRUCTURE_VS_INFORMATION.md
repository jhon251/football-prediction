# DIAG-003：融合结构瓶颈 vs 信息量瓶颈（EXP-DIAG-EPL-003）

> 保持诊断性质：不进入 V1.3、不修改生产模型、不优化任何参数。本实验回答两个问题：
> **Q1（样本稳定性）**：EXP-DIAG-EPL-001 在 120 场固定样本上实测最优的 `team_psychology`（Brier 0.6579 < full 0.6677）在**全部 380 场**上是否仍然优于 `full`？
> **Q2（结构 vs 信息）**：把 Team 通道在引擎中的融合方式改为**加性探针**（`team_only_linear`）后，与 Elo 的差距是否明显缩小？—— 缩小则支持『融合结构是瓶颈』；不缩小则支持『信息量本身不足』（与 EXP-DIAG-EPL-001 Q9 的『Team 残差为反信息』一致）。

## 1. 实验设计

全部 4 个臂在**完全相同**的数据（2025-26 EPL）、样本（**全部 380 场**）、seed（20240101）、模拟次数（400）与 walk-forward 设置下运行，其余 Agent 完全不变：

| 臂 | 配置 | 引擎中的 Team 融合 |
| --- | --- | --- |
| full | 全流水线（生产原样） | 乘性（生产原样） |
| team_psychology | 仅 Team + Psychology 开启（DIAG-001 实测最优配置） | 乘性（生产原样） |
| team_only | 仅 Team 开启 | 乘性（生产原样） |
| team_only_linear | 仅 Team 开启 | **加性探针**（见下） |

**加性探针定义（机制探针，非调参、非最终模型）**：

1. 射门质量组合。生产：`mean = μ0 × (0.6+0.8·att) × (1−0.18·(def−0.5))`。
   探针：`mean = μ0 × (0.69+0.8·att−0.18·def)` —— 在 att=def=0.5 处**精确相等**、一阶 Taylor 等价；二者之差正是被检验的二阶交叉项。
2. 主场优势。生产：`lam ×= (1+home_adv)`。
   探针：`lam = lam0 + base × home_adv` —— 在 home_adv=0 处精确相等；乘性版增量 ≈ lam0×home_adv，加性版 = base×home_adv，lam0/base 通常在 [0.55, 1.35] 内 → **尺度注记（SCALE NOTE，非混杂）**：幅度可比但不恒等，未做任何系数拟合。
3. 门将因子 `p_goal = xg × (1−0.35·(gk−0.5))` 是单因子（无交叉项可拆）→ 两臂保持不变。

实现：运行期 monkey-patch（DIAG-002 同款）：子类先用**输入变换**把生产公式改写为加性等价式，再调用**未改动**的生产 `_attack_intensity` / `_sample_shot`，逐字段还原世界状态。生产源码零修改。

### 1.1 忠实性验证

- full 的 120 场样本子集 vs 冻结 EXP-DIAG-EPL-001 缓存：最大绝对差 home_win=0.0、draw=0.0、away_win=0.0、expected_goals=0.0 → **完全一致（沙箱忠实）**
- team_psychology 的 120 场样本子集 vs 冻结 EXP-DIAG-EPL-001 缓存：最大绝对差 home_win=0.0、draw=0.0、away_win=0.0、expected_goals=0.0 → **完全一致（沙箱忠实）**
- team_only 的 120 场样本子集 vs 冻结 EXP-DIAG-EPL-001 缓存：最大绝对差 home_win=0.0、draw=0.0、away_win=0.0、expected_goals=0.0 → **完全一致（沙箱忠实）**
- 新跑的 full-380 Brier 0.6600 vs 冻结基线 full_system-380 0.6592（seed/模拟次数不同，预期在蒙特卡洛噪声内一致，作为第二锚点）。

## 2. 核心指标（380 场）

| 模型/臂 | n | Accuracy | Brier | LogLoss | ECE |
| --- | --- | --- | --- | --- | --- |
| full（新跑，400 模拟） | 380 | 0.4237 | 0.6600 | 1.0904 | 0.0420 |
| team_psychology（新跑） | 380 | 0.4263 | 0.6520 | 1.0775 | 0.0099 |
| team_only（新跑） | 380 | 0.4263 | 0.6539 | 1.0802 | 0.0126 |
| team_only_linear（新跑） | 380 | 0.4263 | 0.6541 | 1.0808 | 0.0153 |
| Elo（冻结记录，确定性） | 380 | 0.4711 | 0.6310 | 1.0478 | 0.0152 |
| full_system（冻结基线 380） | 380 | 0.4184 | 0.6592 | 1.0885 | 0.0350 |
| random（均匀 1/3） | 380 | 0.3333 | 0.6667 | 1.0986 | 0.0000 |

### 2.1 120 场样本子集（与 EXP-DIAG-EPL-001 的连续性）

| 模型/臂 | Brier（120 子集） | Brier（DIAG-001 原值） | Elo（120 子集） |
| --- | --- | --- | --- |
| full | 0.6677 | 0.6677 | — |
| team_psychology | 0.6579 | 0.6579 | — |
| team_only | 0.6633 | 0.6633 | — |
| team_only_linear | 0.6643 | — | — |
| Elo | — | — | 0.6483 |

### 2.2 配对差异（380 场，臂间共享 seed，逐场配对）

| 配对 | 逐场 Brier 差均值 | std | SE | t |
| --- | --- | --- | --- | --- |
| full − team_psychology（正=team_psychology 更好） | +0.00798 | 0.13375 | 0.00686 | 1.16 |
| team_only − team_only_linear（正=加性更好） | -0.00023 | 0.01389 | 0.00071 | -0.32 |

### 2.3 阶段稳定性（380 场按时间三分）

| 配置 | 早段 Brier | 中段 Brier | 晚段 Brier |
| --- | --- | --- | --- |
| full | 0.6439 | 0.6790 | 0.6569 |
| team_psychology | 0.6292 | 0.6703 | 0.6563 |
| team_only | 0.6297 | 0.6721 | 0.6598 |
| team_only_linear | 0.6282 | 0.6751 | 0.6589 |
| elo | 0.6115 | 0.6498 | 0.6316 |

## 3. Q1：team_psychology 的样本稳定性（380 场）

120 场样本：full=0.6677，team_psychology=0.6579（优势 −0.0098）。380 场：full=0.6600，team_psychology=0.6520，配对差均值 +0.00798（t=1.16）。
→ **方向稳定、未达显著**：380 场上 team_psychology 仍优于 full（优势 +0.00798，120 场样本为 +0.0098，幅度相当），但 t=1.16 未达显著 → 『team_psychology 稳定优于 full』不足以确立；优势方向一致，需更大模拟量确认。

## 4. Q2：融合结构瓶颈 vs 信息量瓶颈（380 场）

与 Elo（380 场 0.6310）的差距：team_only 0.6539（差 +0.0229），team_only_linear 0.6541（差 +0.0231）。加性探针配对差均值 -0.00023（t=-0.32）。
加性探针缩小的 Elo 差距：-0.00023。
→ 加性探针未改善（甚至更差）→ **融合结构瓶颈假设未获支持**；Team-only 与 Elo 的差距更可能来自信息量本身（DIAG-001 Q9：Team 残差与结果负相关，z≈−2.9σ），而非乘性融合方式。

expected_goals（380 场均值 ± std）：full 2.23±0.29；team_psychology 4.11±0.10；team_only 4.13±0.08；team_only_linear 4.14±0.10。
（team_only / team_only_linear 的 xG 明显高于 full —— Team 单独运行时没有 Tactical cc 的强度阻尼，与 DIAG-002 B_off 观测一致；两臂共享该 regime，配对比较不受影响。）

## 5. 结论（严格按证据强度措辞）

**PRIMARY（证据强）：**
- （无）
**SECONDARY（证据中等）：**
- Team(+Psychology) 核心在 380 场上方向性优于 full：team_only 0.6539、team_psychology 0.6520 vs full 0.6600，且 ECE 明显更优（0.0126/0.0099 vs 0.0420）——DIAG-001『边际通道损害核心』的方向在全赛季复现
- 120 场样本子集上 full/team_psychology/team_only 与冻结 EXP-DIAG-EPL-001 逐字段一致（沙箱忠实性锚点）
**UNCONFIRMED（证据不足，不猜测）：**
- team_psychology 优于 full 的方向在 380 场保留（+0.00798，t=1.16）且幅度与 120 场相当（+0.0098），但未达显著
- 加性 Team 融合未改善（配对差 -0.00023，t=-0.32）：融合结构瓶颈假设未获支持，信息量不足为更一致解释

**NEXT EXPERIMENT（仅设计，不执行、不修改生产模型）：**
1. Q1 方向稳定但 t=1.16：用更大模拟量（≥2000，同一 seed/样本）复测 full vs team_psychology（380 场），确认优势是否随蒙特卡洛噪声下降而显著。
2. Q2 未达阈值：**不再把『融合结构』作为首要嫌疑**（DIAG-002 与 DIAG-003 两次独立探针均未支持）；转向信息源诊断——第二赛季数据、球员/伤停信息能否改变 Team 残差的反信息方向（DIAG-001 Q9，z≈−2.9σ）。
3. 跨赛季复测（需先获取第二赛季真实数据）。

## 6. 可复现

- 冻结基线：EXP-REAL-EPL-BASE-001（`7c52c6bdfa37`）、EXP-DIAG-EPL-001、EXP-DIAG-EPL-002 —— 哈希清单在 `backtest_output/diag_003_structure_info/baseline_manifest_*.json`。
- 沙箱产物：`preds_part1.json` / `preds_part2.json`（4 配置 × 380 场，400 模拟，seed 20240101）、`validation_part1/2.json`。
- 注册表：`backtest_output/diag_003_structure_info/experiments.jsonl`（EXP-DIAG-EPL-003，`synthetic_data=false`，`market_data=false`）。
- 生产源码零修改；加性探针仅存在于本诊断脚本的运行期。
