# P2_FORWARD_ACCUMULATION_REPORT — 真实 Forward 数据累积与持续监控阶段报告

- 阶段：5.3-P1-C（forward accumulation & continuous DQ/revision monitoring）
- 报告时间：2026-09-13T05:50Z（本地 13:50）
- 边界（冻结理解，全程遵守）：不做预测增量实验、不算 Understat LL/AUC、不调 M4/O2、不接 xG 进概率、不设计 Agent/Ensemble、不用不足样本下 Understat 结论、不用历史回溯补样本、不进行 betting/ROI/EV/stake。

## 1. 交付物

| 交付物 | 路径 | 性质 |
|---|---|---|
| 只读监控器 | `forward_pipeline/monitor.py` | 新增；对 forward store **只读**，仅写自身状态与 dashboard |
| 自动 dashboard | `FORWARD_ACCUMULATION_STATUS.md/.json`（phase 目录） | 每次监控运行自动重生成 |
| 监控定时任务 | `P53P1-ForwardMonitor`（每小时；STOP 时 exit 5） | 已注册，State=Ready |
| 监控回归测试 | `tests/understat_forward/test_monitor.py`（12 项） | 全套 29/29 OK |
| 阶段报告 + registry | 本文件 + `.json` + registry 追加 | — |

## 2. Provenance 全链路（用户要求字段 → 实际落点，全部已存在且经监控器逐条校验）

| 要求字段 | 落点 |
|---|---|
| match_id / league / season | norm 记录 |
| kickoff_utc | `kickoff_utc`（冻结集 join；2026-27 赛季无冻结季 → null，by design）+ `kickoff_provider_datetime`（provider-naive-UTC 约定，显式声明于每条 run 日志） |
| retrieved_at | sidecar + norm + registry（三处一致） |
| raw response / raw sha256 | `raw/*.json`（字节精确保存）+ sidecar + registry 三方 sha 校验 |
| parser version | sidecar + registry（forward_pipeline.py:v1） |
| capture window | `window_status`（sidecar + norm + registry） |
| DQ classification | `dq_status`（词表受控：time_safe/window_late/window_early/missing/revision_observed/historical_retro/upcoming_fixture） |
| namespace | `dq_namespace=forward`（生产 store 13/13 条复核为 forward） |
| experiment/registry reference | `capture_id` → `data/registry.jsonl` 链式条目（prev_capture_id 链完整） |

**严格时间安全规则落地**：监控器对每条候选记录计算 `valid_forward_sample_vs_next_kickoff` = `dq_status==time_safe AND namespace==forward AND retrieved_at < K`（K=该联赛下一个 upcoming 开球时间）。内容"看起来像赛前数据"绝不作为判定依据：upcoming 行含任何 xG/goals 字段 → STOP（`UPCOMING_WITH_RESULT_FIELDS`）。

## 3. 持续 DQ 监控（monitor.py 检查项 → 实测）

| 监控项 | 检查方式 | 当前实测 |
|---|---|---|
| time_safe / window_late / no_results | 逐记录 dq_status 聚合 + registry captures_no_results | time_safe=0（全联赛）、window_late 250、upcoming 4088、no_results capture 1 条（D1 赛前） |
| missing timestamp | retrieved_at 逐记录校验 | 0 |
| malformed response | runs 日志 parse_error 计数 + norm 必填字段扫描 | parse_error=0、0 缺失 |
| duplicate | 同 (league, window_key) 多 capture 检测 + 重复 match_id 检测 | 无非 recheck 重复写入（WARN 级观察项 0） |
| revision event | revisions/ 文件 + registry n_revision_events | 0 事件 |
| parser/schema anomaly | 必填字段集（14 个）逐记录校验 | 0 |
| provider anomaly | result 行无 xG、upcoming 行带结果字段、retrieved_at<自家 kickoff（不可能数据） | 0 |
| 命名空间/retro 污染 | 逐记录 dq_namespace + historical_retro 检测 | 0（13/13 forward） |
| generated_at/published_at 推断 | 非 null 即 STOP | 13/13 恒 None |
| 冻结指纹 | sha256 复算 | 一致（8f885fbc…3442） |
| scheduler 存活 | last_run lag >48h → STOP | lag 0.06h（健康） |

**STOP 条件全部实现并在本次扫描中为 0 触发**；每小时任务将使任何后续触发在 ≤1 小时内可见（exit 5 + dashboard STOP 段）。

## 4. Revision Audit（新计划）

- 当前活跃计划：5 联赛各一套（t24=2026-09-14T04:59Z 起算各自的 +24h，t7d=+7d）；本轮窗口 capture 将按 R3 修复语义刷新各联赛计划，逾期检查点不再被静默丢弃。
- 已执行记录（runs 日志）：3 条 `revision_recheck_covered_by_capture`（G1 逾期补执行，明确标注 `pre_registered_points_missed={t24:true,t7d:true}`、延迟 427.0h/283.0h）——**性质为观测性数据，不计入预注册实验结果**。
- old/new hash：监控器为每条 recheck 执行附 `recheck_raw_sha256` 与 `baseline_raw_sha256`（原始响应级；raw hash 因 upcoming 赛程变化必然不同，语义比较以 `n_revision_events`/`revisions/` 值级 diff 为准，当前 0 修订、max|ΔxG|=0）。

## 5. 样本进度（dashboard 实测 2026-09-13T05:46Z）

| 联赛|赛季 | 已见已赛 | time_safe | window_late | upcoming | 赛季覆盖% | time_safe覆盖% | 距300场 | 距完整赛季 |
|---|---|---|---|---|---|---|---|---|---|
| E0|2026 | 37 | **0** | 37 | 371 | 9.7 | 0.0 | 300 | 343 |
| SP1|2026 | 46 | **0** | 46 | 366 | 12.1 | 0.0 | 300 | 334 |
| I1|2026 | 33 | **0** | 33 | 372 | 8.7 | 0.0 | 300 | 347 |
| D1|2026 | 25 | **0** | 25 | 281 | 8.2 | 0.0 | 300 | 281 |
| F1|2026 | 33 | **0** | 33 | 297 | 10.8 | 0.0 | 300 | 347 |

- 重大 revision drift：无（0 事件）。
- **门槛不因样本不足而降低**：300 场/联赛-季与完整赛季要求原样保留；所有 window_late 存量（250 条）不得计入。

## 6. 阶段完成标准核对（9 项）

| # | 标准 | 状态 |
|---|---|---|
| 1 | scheduler 持续稳定运行 | ✅（daemon 心跳 0.06h lag；watchdog+计划任务双层；已生产验证） |
| 2 | 产生真实 time_safe 数据 | ⏳ **PENDING**——首个真实窗口约为今晚 20:30Z 起（E0 13:00Z/15:30Z 开球 → 最后开球+3h）；恢复时刻不存在任何 in-window 时段，不伪造 |
| 3 | 5 联赛形成有效 forward 样本 | ⏳ **PENDING**（当前有效样本=0；随各联赛首个 in-window capture 起累积） |
| 4 | provenance/DQ 全链路可审计 | ✅（监控器逐记录校验 + 本报告字段映射） |
| 5 | T+24h/T+7d 按新计划执行 | ✅ 已排定（到期 2026-09-14T04:59Z 起）/ 首批按期执行待明日验证 |
| 6 | 无重大污染/时间安全违规 | ✅（monitor 实测 STOP=0） |
| 7 | 不触碰冻结数据与 Market Baseline | ✅（指纹复核一致；M4/O2 与预测模块零改动） |
| 8 | 完整阶段报告与 registry | ✅（本文件 + registry 追加） |
| 9 | 明确样本量与下一阶段门槛差距 | ✅（§5：每联赛距 300 场 time_safe 全额 300；距完整赛季 281–347 场） |

**结论：P2 的基础设施与治理层全部就绪并通过验证；累积性标准（#2/#3/#5 的实际发生）依赖真实比赛窗口与时间推进，本报告不宣布 P2 完成，不提前进入增量实验。** 按当前节奏（每比赛日 5 联赛各约 8–10 场 in-window），≥300 场/联赛-季需约一个完整赛季的持续累积，与 5.3 re-scope 的"首个完整赛季"评估窗口一致。

## 7. 自动化运行说明

- daemon（600s）+ watchdog：运行中（本会话拉起）；重启后由 15 分钟计划任务层接管采集，Startup 自启待用户手动 `install_startup.ps1` 一次。
- 计划任务：`P53P1-UnderstatForwardScheduler`（15 分钟 `--once`）、`P53P1-ForwardMonitor`（每小时监控；STOP→exit 5）。
- 人工检查入口：`python forward_pipeline/scheduler.py --status`；`python forward_pipeline/monitor.py`；dashboard 文件自动刷新。
