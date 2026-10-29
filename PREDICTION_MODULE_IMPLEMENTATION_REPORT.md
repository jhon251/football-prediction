# PREDICTION_MODULE_IMPLEMENTATION_REPORT — 最小预测模块实现报告

- 日期：2026-09-13
- 模块：`src/football_prediction/` v0.1.0
- 规格：`PREDICTION_MODULE_SPEC.md`；矩阵：`PREDICTION_MATRIX.md`；验收基线：`CURRENT_SYSTEM_AUDIT.md`
- 机器可读版本：`PREDICTION_MODULE_IMPLEMENTATION_REPORT.json`

## 1. 交付物清单

| 项 | 路径 | 状态 |
|---|---|---|
| 算法复用层 | `src/football_prediction/market.py`（Shin 求解器 + M4/M2/O2/O4 + 回退链） | ✅ 完成 |
| 信号状态层 | `src/football_prediction/signals.py`（gate，不改概率） | ✅ 完成 |
| 冻结指纹守卫 | `src/football_prediction/provenance.py`（漂移 → STOP） | ✅ 完成 |
| 输入/输出 Schema | `src/football_prediction/schema.py`（pydantic v2） | ✅ 完成 |
| 编排器 | `src/football_prediction/predictor.py`（状态机 + 泄漏守卫 + 不确定性/置信度） | ✅ 完成 |
| CLI | `src/football_prediction/cli.py`（predict / self-check，状态化退出码） | ✅ 完成 |
| 测试 | `tests/prediction/`（40 个：单元 + 负例 N1–N10） | ✅ 全部通过 |
| 演示工件 | `backtest_output/experiments/prediction_module_v0/demo_input_*.json / demo_output_*.json` | ✅ 完成 |
| Registry 追加 | `backtest_output/experiments/prediction_module_v0/experiment_registry_append.jsonl`（6 条） | ✅ 完成 |

未改动：`src/football_simulation/**`、`backtest_output/dataset_build/freeze/**`（指纹复核不变）、全部既有 phase 目录与 registry。

## 2. 核心实现决策（与已验证基线的关系）

1. **复用而非重写**：`shin_probs` 与 phase4a `run_phase4a.py` 逐字同算法；由测试钉死——
   - 随机 q（2/3/5 结果，256×3 组）与 phase4a 求解器**逐位相等**；
   - 200 组随机庄家集合上，M4/O4 端到端概率与 phase4a `method_ftr/method_ou25` 一致（<1e-9）；
   - **真实数据全量等价**：冻结 v1.1.0 Split-A test 全部 3504 场，经模块完整输入校验路径后 M4/O2 概率与 phase4a 直接计算 **0 mismatch**（<1e-9）。
2. **回退链**（全部留痕并降级 CONDITIONAL）：FTR `M4 → M2`（单庄）；OU25 `O2 → O4 → 单庄 Shin`。M2/O4 均为 4A 已注册且已评估方法。
3. **泄漏守卫**：closing context → REJECTED；closing leg（CH/CD/CA/C> /C<）与 closing 庄家族（去 C 后命中注册表，如 B365C；**不误伤合法的 VC**）剔除并计数；label 字段（fthg/ftag/ftr/label/score…）→ REJECTED。
4. **时间安全门**：`retrieved_at >= kickoff_utc` → REJECTED；`retrieved_at` 缺失 → time_safe=UNKNOWN → CONDITIONAL。
5. **信号门**：`forward + time_safe + retrieved_at<kickoff` → candidate（AVAILABLE_NOT_VALIDATED）；retro/非 time_safe → REJECTED；`generated_at/published_at` 缺失恒为 UNKNOWN，绝不推断；`TIME_SAFE_VALIDATED` 只能来自 `validated_signal_registry.json`（当前不存在 → 不可达）；`signals_used_in_prediction` 结构性恒 false。
6. **无概率伪造**：任何缺失 → 状态字段（INSUFFICIENT_DATA/UNKNOWN/REJECTED/STOP）+ 概率=null。全模块无随机数、无默认概率、无填充值。
7. **STOP 语义**：冻结指纹漂移 → STOP（测试用临时文件模拟漂移验证）。

## 3. 验证结果汇总

| 验证 | 结果 |
|---|---|
| `tests/prediction/` 40 测试 | **OK（40/40）** |
| 全仓测试套件（含旧引擎 244 + 新增 40） | OK（见 §6 备注） |
| 真实数据等价（3504 场 × M4+O2） | **0 mismatch** |
| CLI VALID 演示 | exit 0，`overall_status=VALID`，信号=candidate，概率未受影响 |
| CLI 无赔率演示 | exit 1，`INSUFFICIENT_DATA`，概率=null |
| `self-check` 冻结指纹 | verified=true，sha256 与钉扎值一致 |

## 4. 对最终问题的回答

1. **当前 Market 预测是否真实可运行？** 是。M4/O2 是纯函数（preclosing odds → 概率），本模块已将其投入可运行状态，并在全部 3504 场 test 集上与 Phase 4A 验证结果逐位一致。
2. **当前 Agent 是否真实存在？** 否。不存在任何 Agent/manager/ensemble。`src/football_simulation` 的 30+ Agent 是沙盘模拟层（合成数据、35 条规则全部 tentative），不构成预测 Agent。
3. **当前预测功能完成度？** 按 `PREDICTION_MATRIX.md` 维度 B：Market Baseline（v0 范围）≈100%（实现+验证+CLI+测试）；Market + External Signal Candidate ≈40%（仅状态管理，无信号可接入——forward store time_safe=0）；Validated Signal Model 与 Agent/Ensemble = 0%（按矩阵禁止实现，需预注册授权）。
4. **哪些输入可以真实预测？** 只有 PRE_CLOSING 赔率：FTR 需 ≥2 庄家 H/D/A（→M4，1 庄→M2 回退）；OU25 需 B365 over/under（→O2，或多庄→O4 回退）。Elo/xG/阵容等一切市场外输入当前都不可预测。
5. **哪些输入必须返回 UNKNOWN/INSUFFICIENT_DATA？** 无赔率或赔率全非法 → INSUFFICIENT_DATA；`retrieved_at` 缺失 → time_safe=UNKNOWN（结果 CONDITIONAL）；信号时间戳缺失 → UNKNOWN；kickoff 不可解析 → REJECTED；closing/label 注入 → REJECTED；指纹漂移 → STOP。
6. **Understat 何时允许进入预测？** 严格条件链：数据在 forward 命名空间、窗口内采集（dq_status=time_safe）、`retrieved_at < 目标比赛 kickoff_utc`、DQ 通过 → 才成为 candidate（AVAILABLE_NOT_VALIDATED）；再通过预注册增量门槛（≥300 time_safe 场/联赛-季 + 完整赛季 + ΔLL≥0.003 + 方向稳定 + max|窗口ΔLL|≤0.02 + AUC 不劣于市场 + 泄漏套件全 PASS）并写入验证注册表后，才可标 TIME_SAFE_VALIDATED 并进入模型——在此之前**永不改变概率**。历史回溯数据永久排除。
7. **距离最终 Agent 目标还有哪些硬门槛？**（按 5.3 re-scope 与 phase5_review）
   - G1 修复：forward scheduler 复苏与持续运行（当前停摆 19 天，0/300 time_safe）；
   - Understat xG 完整赛季前向累积（5 联赛 × ≥300 场）+ T+24h/T+7d revision audit 无重大漂移；
   - 预注册增量实验全门通过且 registry 记录；
   - （可选）lineup 前向管线 ≥150 time_safe/联赛-季；
   - 以上全部通过后才允许设计 Agent/Ensemble（再次预注册），且 Agent 永远以 M4/O2 为对照组；不得宣称 Agent 优于 Market 直至有 registry 级证据。

## 5. 已知局限（如实声明）

- 不确定性/置信度是**描述性**指标（熵、跨庄离散度、回退惩罚），不是模型后验；置信度不是"预测正确率"。
- OU25 主路径依赖 B365 对价；无 B365 时走 O4（4A 中 n=3371，精度略异）。
- 模块不提供 HTTP API（旧引擎的 FastAPI 可选依赖未启用；CLI + Python API 已满足"按现有工程架构"最小要求）。
- 时间戳信任模型：`retrieved_at` 由调用方声明，模块只做一致性检查；真实前向预测必须由调用方保证赔率采集纪律（这是 5.3 协议的领地）。

## 6. 备注与偏差记录

- 实现中发现并修复：`book_dispersion_max` 首版跨腿取全局极差（0.2138）→ 改为逐腿离散度最大值（0.0227）；C-suffix 守卫首版会误伤合法庄家 `VC` → 改为"去 C 后命中注册庄家表"的精确规则。两处均有回归测试。
- 全仓根测试套件需要 `PYTHONPATH=src`（审计缺口 G3）：设置后含新增测试全数通过；未设置时旧引擎 backtest 子目录 12 个模块 ImportError（与本模块无关，未修改旧引擎）。
- 审计缺口 G1（forward 管线停摆）**未修复**：按"只报告不掩盖"纪律，重启 scheduler 需另行授权。
