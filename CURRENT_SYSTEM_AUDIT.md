# CURRENT_SYSTEM_AUDIT — 足球预测 AI 项目工程验收

- 审计日期：2026-09-13
- 审计范围：`C:\football` 全仓（真实代码、数据、测试、实验产物），不默认任何历史报告正确。
- 审计方法：逐文件核对 + 实时重新执行泄漏套件 + 冻结指纹重算 + Phase4A 数值独立复现。
- 结论速览：**报告链与真实工程基本一致；M4/O2 市场基线真实可运行（本次独立复现数值完全一致）；不存在任何预测 Agent/预测 API；Understat forward 管线代码真实且 dry-run 12/12 PASS，但生产 forward store 当前 time_safe 数据为 0，调度器自 2026-08-25 起停摆。**

证据标签约定：**Evidence** = 本次审计直接验证（执行/重算/逐行读码）；**Hypothesis** = 有项目内证据支持但本次未独立复现；**Unknown** = 无法从现有工件确认。

---

## 1. 系统的真实结构（Evidence）

仓库中实际存在**两套独立系统**，任何声称"当前系统"的描述必须区分二者：

| 系统 | 位置 | 性质 | 状态 |
|---|---|---|---|
| A. V1/V1.2 沙盘模拟引擎 | `src/football_simulation/`（30+ Agent、core/backtest/evaluation） | 比赛过程模拟器，合成 mock 数据 | 244 个单元测试本次全数通过（需 `PYTHONPATH=src`）；**不是**市场层预测器，35 条规则全部 tentative |
| B. Phase 2A→5.3 研究纲领 | `backtest_output/`（dataset_build、freeze/1.1.0、experiments/phase3a…phase5_3_p1） | 时间安全预测研究，真实冻结数据 | 报告/代码/registry 完整；无预测模块 |

关键事实（Evidence）：
- `docs/` 下的文档（agents.md、architecture.md、V1_2 报告等）描述的是系统 A；Phase 3B–5.3-P1 的真实工件全部在 `backtest_output/experiments/` 下。
- **系统 B 中不存在名为 Agent/manager/signal layer/prediction API 的可运行预测组件**（全仓 `def predict` 仅出现在系统 A 的回测 baseline 类中，属于研究脚本，非生产 API）。
- 用户所称"Agent 仍是研究纲领"与事实一致：`phase5_review/PHASE5_REVIEW_ARCHITECTURE_AND_ROADMAP.md` 定义了 Agent 为未来集成系统，尚未实现（仅设计）。

## 2. Frozen v1.1.0 数据集（Evidence）

- 路径：`backtest_output/dataset_build/freeze/1.1.0/baseline_dataset.jsonl`
- 本次重算 sha256：`8f885fbcc38aca3f4ea0b88a925b07db23244fccec7ed09b1f7cb55c45b13442`
- 与以下全部引用一致（Evidence）：`forward_pipeline/config.py FROZEN_DS_SHA`、`run_phase4a.py FP_DS`、Phase4A/4B/4D/5.1A/5.1D 报告头、phase3b preflight 实时输出。
- 行数 19763；`freeze_verification.json` status=FROZEN、7 项检查全 true；`freeze_integrity_recheck.json` all_consistent=true（row_checksum、schema_fingerprint、55 个源文件等）。
- 行结构：每行含 `label`（fthg/ftag/ftr）、`odds.preclosing`、`odds.closing`、`provenance`；`features` 为空数组（特征在 2A/2B 独立文件）。preclosing 命名空间实测无 C-suffix 键（本次抽查 + preflight EXP-4 全扫描 19763 行 0 违规）。

## 3. Experiment Registry 完整性（Evidence）

| 文件 | 条目数 | ID 形态 |
|---|---|---|
| `phase3b_training/experiment_registry.jsonl`（主） | 72 | `EXP_{market,lr,lgbm}_{ftr,ou25}_{fixed_A,rolling_*}_*` |
| `phase3c_analysis/experiment_registry_append.jsonl` | 12 | `EXP_ablation_A1..A6_*` |
| `phase4a_market_baseline/…` | 62 | `EXP_market_{M1..M5,O1..O4}_*` |
| `phase4b_execution/…` | 15 | `EXP_cal_M4/O2_*` |
| `phase4d_calibration_stability/…` | 24 | `EXP_calstab_*` |
| `phase5_1a_calibration_closure/…` | 96 | `PHASE5.1A\|season\|outcome\|method` |
| `phase5_1d_closing/…` | 24 | `PHASE5.1D\|…` |
| `phase5_2_xg_dq/…` | 16 | `PHASE5.2\|XG-1..6、源清单`（含 **FAIL** 两条：XG-1 timestamp、XG-5 coverage） |
| `phase5_2b_spi_dq/…` | 15 | `PHASE5.2B\|SPI-1..6 + N1..N8` |
| `phase5_3_p1_understat_forward/…` | 27 | `PHASE5.3P1\|dryrun + 5 联赛`、`PHASE5.3P1B\|scheduler runs` |

- 总计 363 条；Phase 4A 的 `EXP_market_*` 条目内嵌 `dataset_sha256` 与 `feature_version_2B` 指纹（抽样一致）。
- ID 无重复、无跨文件冲突（本次逐行解析核对）。
- Registry 为"主文件 + 各 phase append"的分布式设计，非单一中心文件（与最终交付要求 `experiment_registry_append.jsonl` 的惯例一致）。
- 仅设计/评审类目录（phase3a_design、4c_review、5.2c/2d/2e/2f、5.3_rescope、phase5_review）无 registry 条目——与其"不执行实验"的定位一致，不算缺口。

## 4. 逐 Phase 验收（结论 → 证据）

### 4.1 Phase 3B — Market 优于 LR/LightGBM
- 判定：**Evidence（本次实时复验）**。
- `phase3b_preflight/exp_preflight_tests.py` 本次重新执行：EXP-1..6 全 PASS，6 个合成负例全 DETECTED，frozen unchanged=True，"no model files" 确认不留落盘模型。
- `PHASE3B_TRAINING_REPORT.md` 数字：FTR market .5337/.9719 vs lr .5147/1.007 vs lgbm .4657/1.0887；OU25 同序。训练代码 `run_baselines.py` 存在，72 条 registry 条目对应 72 个 model_reports/rolling 文件。

### 4.2 Phase 3C — 传统特征/Elo 无增量
- 判定：**Evidence（报告+代码+registry 齐全；消融数值本次未独立重跑，A0 基线数值与 3B 市场基线一致）**。
- `run_ablation.py` + `FEATURE_ABLATION_REPORT.json`（A0..A6）+ `ELO_COMPARISON_REPORT` + 12 条 registry。

### 4.3 Phase 4A — M4/O2 市场基线
- 判定：**Evidence（本次数值独立复现，逐位一致）**。
- 本次用冻结数据重算 Split A Test：M4 acc=0.534 / LL=0.9707 / brier=0.5776（n=3504）；O2 acc=0.5799 / LL=0.6725 / brier=0.2399；M1/M2/O1/O4 亦全部与报告一致。
- `run_phase4a.py` 含真实 Shin 二分求解器（z=0 回退）、multi-book ≥2 政策、preclosing-only 结构、冻结 sha 校验。
- 弱点（如实记录）：`ODDS-P1_negatives` 中 `NEG_C_suffix_in_input`、`NEG_label_as_input` 是结构性/同义反复式断言，强度弱于 phase3b 的行为级负例；真实防线是"方法只读 preclosing 命名空间"的结构约束 + preflight 套件。不构成缺陷，但不应宣称其等价于行为级泄漏测试。

### 4.4 Phase 4B — 校准与分段诊断
- 判定：**Evidence（报告/代码/registry 齐全）**。identity/isotonic/piecewise 三映射 × M4 三结果 × O2 两结果 = 15 条 registry；isotonic 单次 Test 上改善 home/away LL（0.7426→0.62、0.6218→0.5682），OU25 ECE≈0.01 无增益空间。

### 4.5 Phase 4D — 校准跨季不稳定
- 判定：**Evidence（报告+24 条 registry）**。rolling 逐季 isotonic 增益：ftr/home 1 正 5 负、ftr/away 1 正 5 负、ou25/over 1 正 5 负 → 方向不稳定，verdict=Evidence（不稳定这一事实本身）。

### 4.6 Phase 5.1-A — 校准分支关闭
- 判定：**Evidence**。M1 全局 isotonic / M2 entropy / favorite / draw-band 全部 CLOSE（mean improvement −0.0034…−0.0121，同号比例 0–5/24）。泄漏门 EXP-1..6 + CS-1/CS-2 PASS。

### 4.7 Phase 5.1-D — CLOSING 亚门槛
- 判定：**Evidence**。CLOSING=CONDITIONAL（非 SAFE）；ΔLL FTR +0.0014 / OU25 +0.0024，低于 0.003 门槛；AUC 无排序增益；CLOSE-1..4 PASS，5 个负例全 DETECTED。已注册排除 VCA/VCD/VCH（VC Bet preclosing 列在冻结 2B 中误归 closing 命名空间——已知问题，冻结资产不修，登记为 caveat）。

### 4.8 Phase 5.2 — 历史时间安全外部数据获取失败
- 判定：**Evidence**。XG-DQ：XG-1（无逐行 generated_at）FAIL、XG-5（覆盖 28/30 单元缺失）FAIL；Understat rolling=PARTIAL（构造可复现但历史时间点值保真不可证明）；SPI（5.2B）：SPI-4/5=UNKNOWN、SPI-3/6=PARTIAL；5.2C–5.2F 逐源评审后 5.2-F 正式关闭"历史 time-safe 外部信号"路线并强制转为 Forward Validation。
- registry 中 FAIL/UNKNOWN 记录被如实保留，未被"补全为 PASS"。

### 4.9 Phase 5.3-P1 — Understat forward accumulation
- 判定：**Evidence（管线代码与 dry-run 真实）+ 重要 Operational Gap（见 §6）**。
- 代码：`forward_pipeline/pipeline.py`（append-only capture、sha256、sidecar、窗口 DQ、frozen 只读 join、revision audit、missing=skip-and-count、chained registry、manifest+强制声明）、`scheduler.py`（schema drift → STOP flag、去重、窗口调度、T+24h/T+7d 复检）、`config.py`（窗口 T+3h..T+6h、5 联赛、MIN=300/联赛-季）。
- dry-run：`dryrun_validation_result.json` 12/12 PASS + 9 个合成负例全 DETECTED；本次逐行阅读 `dryrun_validate.py` 确认检查逻辑真实（一次性沙箱、不触碰生产 store）。
- 命名空间隔离（Evidence，代码级）：forward 命名空间拒绝非当前赛季注入（retro-injection guard，N1 测试）；`dq_validation` 命名空间的赛后数据标注 `historical_retro` 且被排除出 forward 集（N1b 扫描确认无混入）；冻结数据集只读且每次 capture 前 sha 校验。
- `generated_at/published_at` 恒为 None（provider 不暴露 → UNKNOWN，绝不推断），sidecar 与 norm 记录双层落实。

## 5. 泄漏/危险接线扫描（Evidence）

- CLOSING 当 SAFE：无。M4/O2 结构上只读 `odds.preclosing`；5.1-D 明确 CLOSING=CONDITIONAL 且从未进入基线。
- Test 二次使用：无。EXP-1 fixed split 隔离 + CS-1 rolling 隔离本次实时 PASS；各 phase 报告均声明 Test 单次评估。
- Label leakage：无。方法签名只接受 odds；EXP-3 registry 合规 + EXP-4 全扫描 PASS。
- 历史回填：无。forward 管线 retro-injection guard 生效；5.3 re-scope 文档明确历史 retro "永久不可进入"。
- 未验证外部信号接入模型：**不存在任何此类代码**（全仓无 xG→模型、Elo→主预测层的生产路径；Elo 定位为保留特征+诊断基线，CLOSE 优化方向）。
- Betting/ROI/EV：无任何下注/盈利代码或宣称；各报告含显式禁止声明。

## 6. 真实工程与报告的不一致 / Operational Gap（如实指出，不代报告补全）

| # | 发现 | 严重度 | 说明 |
|---|---|---|---|
| G1 | **Forward store 停摆**：`data/scheduler_state.json` last_run=2026-08-25T15:45Z；今日 2026-09-13 已停摆约 19 天。`revision_rechecks` 中 T+24h（08-26）与 T+7d（09-01）复检均已到期但从未执行。生产 forward store 8 次 capture，**time_safe 记录 = 0**（全部 window_late/no_results） | 高 | "12/12 硬门槛 PASS" 仅指 dry-run 机制验证；管线当前**不在运行**，且从未在窗口内成功捕获过。距 ≥300/联赛-季 门槛差距巨大 |
| G2 | 根 README 与 docs 只描述系统 A（沙盘引擎），没有任何顶层文档映射 Phase 2A–5.3 研究纲领的真实位置与状态 | 中 | 新接手者（包括本次审计前的任何调用方）需要自行发现 `backtest_output/` 才是研究主线 |
| G3 | 根目录测试套件在未 `pip install -e .` / 未设 `PYTHONPATH=src` 时 12 个模块 ImportError（145 测试 12 errors）；设置后 244 测试全通过 | 低 | 环境问题，非代码回归；README 未写明此前置条件 |
| G4 | Phase4A 的 ODDS-P1 负例测试部分为同义反复（见 §4.3） | 低 | 防线真实存在（结构约束+preflight），但负例本身不构成行为级证明 |
| G5 | scheduler 将 Understat provider 本地时间按 UTC 处理（代码内注明 documented caveat），窗口边界可能偏移数小时 | 低 | 偏向产生 window_late（保守方向），但会造成 time_safe 窗口漏捕/迟捕 |
| G6 | 冻结 2B 中 VCH/VCD/VCA 误归 closing 命名空间 | 低 | 已在 5.1-D 登记并以注册表方式排除；冻结资产不修改，处理正确 |

## 7. 当前预测能力盘点（回答"现在能预测什么"）

- 真实可运行的预测能力 = **市场基线 M4（FTR）/ O2（OU25）**，本次已独立复现其历史指标；二者是纯函数（输入 preclosing odds → 概率），可直接服务新比赛预测。
- 无 Agent、无 signal layer、无 prediction API；`src/football_simulation` 的概率输出是沙盘模拟产物（合成数据、规则全 tentative），**不得**冒充市场层预测。
- Understat forward 数据当前 0 条 time_safe → 任何"市场外信号"输入今天都必须返回 NOT_AVAILABLE；即便未来有 time_safe 数据，在通过预注册增量门槛（≥300/联赛-季、完整赛季、ΔLL≥0.003 等）之前只能标 `AVAILABLE_NOT_VALIDATED`，不得改变预测概率。
- Unknown（无法确认，需后续验证）：scheduler 是否已被外部手段（如 Windows 计划任务）重启；`data_005_lineup_live` 是否在别处继续累积（本仓内最后记录 1 场真实比赛、0 time_safe 版本）。

## 8. 结论

1. Phase 3B→5.3-P1 的报告链与真实工程**一致**，本次未发现任何"报告 PASS 但工件缺失/造假"情形；FAIL/UNKNOWN 均被如实登记。
2. 唯一重大 Operational Gap 是 **G1：forward 管线停摆、time_safe=0**——这不推翻任何历史结论，但意味着 Forward Validation 路线当前没有可用数据，预测矩阵中"外部信号"各模式只能处于未实现/不可用状态。
3. 冻结指纹无变化；泄漏套件实时复验通过；不存在越权接线。
4. 允许进入下一步（最小预测模块）实现：基座 = M4/O2 复用，外部信号仅做状态管理，不做概率混合。
