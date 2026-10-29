# P2_RUNTIME_OBSERVATION_STATUS — 运行时观察基线与事件核对单

- 观察起点：2026-09-13T05:55Z（本地 13:55）
- 性质：只读观察。不修改 M4/O2、Prediction Module、冻结数据、历史实验；不使用 historical_retro；不用 window_late/no_results 补样本；不推断 generated_at/published_at；不把 Understat 接入预测概率；不做增量实验/Agent/Ensemble/betting/ROI/EV/stake；不为产生 PASS 构造测试比赛或伪造 time_safe。

## 1. 观察起点基线（全部实时核验）

| 项 | 状态 |
|---|---|
| daemon（600s） | 运行中，lock 持有（PID 18116），last_run=05:53Z，13 captures，0 stop_flags |
| 计划任务 Scheduler（15 分钟 `--once`） | Ready，实际运行 result=3（命中 daemon 锁被拒 = 防双跑按设计生效） |
| 计划任务 Monitor（每小时） | Ready，实际运行 result=0（0 STOP） |
| 监控器扫描 | overall OK；WARN 仅 HEARTBEAT_GAP 445.2h（已记录的 G1 历史停摆） |
| time_safe | **0**（真实窗口未开启；首窗预计 2026-09-13T20:30Z 起，E0 13:00Z/15:30Z 开球） |
| 五联赛 recheck 计划 | t24=2026-09-14T04:59Z、t7d=2026-09-20T04:59Z（各联赛） |
| revision drift | 0 事件 |
| 冻结指纹 | 8f885fbc…3442 一致 |

## 2. 事件核对单（每项发生时只做客观记录与验证）

| # | 事件 | 验证程序 | 状态 |
|---|---|---|---|
| E1 | 首条合法 time_safe | 监控器自动捕获 `first_time_safe`（match/league/season/kickoff/retrieved_at/capture_id）；验证：14 项 provenance 完整、retrieved_at>自家 kickoff（无不可能数据）、retrieved_at<下一目标 kickoff（可容许性）、namespace=forward、dq_status=time_safe 且 window_status=in_window、raw sha256 三方一致 | 待真实窗口（今晚起） |
| E2 | 五联赛均产生合法 time_safe | dashboard 逐联赛 time_safe_distinct>0 且 first_time_safe 均非空 | 待 E1 后 |
| E3 | 首批 T+24h 按期执行 | runs 日志 `revision_recheck*` 条目，`pre_registered_points_missed.t24=false` → 记为**正式 scheduled observation** | 待到期（2026-09-14T04:59Z 后首个 capture 周期） |
| E4 | 首批 T+7d 按期执行 | 同上，`.t7d=false` | 待 2026-09-20T04:59Z 后 |
| E5 | revision_event | revisions/ 值级 diff + registry n_revision_events；max\|ΔxG\| 报告 | 持续监控（当前 0） |
| E6 | raw sha256 变化 | 监控器逐 capture 记录 recheck_raw_sha256 vs baseline_raw_sha256；**raw hash 跨 capture 变化本身是预期**（upcoming 赛程演进），语义修订以值级 diff 为准 | 持续监控 |
| E7 | scheduler 持续稳定 | 心跳 lag ≤48h（>则 STOP SCHEDULER_STALLED）；每 cycle 全分支日志 | 持续（当前健康） |
| E8 | monitor 持续 0 STOP | 每小时扫描；STOP→exit 5 + dashboard STOP 段 | 持续（当前 0） |
| E9 | 时间安全/命名空间/provenance/污染异常 | 13 项 STOP 检测 + WARN 观察 | 持续（当前 0 STOP / 1 已记录 WARN） |

## 3. 预注册判定口径（在事件发生前固定，防事后挪动）

1. **"按期"定义**：recheck 的执行粒度 = capture 周期（比赛日之间无 capture）。某检查点计为**按期执行**（正式 scheduled observation）当且仅当：在其 scheduled_at 之后的**第一个 capture 周期**内执行，且 `latency = executed_at − scheduled_at ≤ 24h`（即仍处于 T+24h..T+48h 窗口内）。latency>24h → missed=true（照实报告）。
2. **G1 历史逾期 recheck 永久保持** `pre_registered_points_missed=true / observational`，永不重新包装为正式预注册结果（现有 3 条 covered_by_capture 记录不变）。
3. **time_safe 判定不可协商**：仅 `dq_namespace=forward ∧ dq_status=time_safe（in-window 采集）`；可容许性另需 `retrieved_at < 目标 kickoff`。window_late/no_results/upcoming 永不入有效样本。
4. **raw sha256 跨 capture 变化 ≠ 修订**：语义修订仅以 revisions/ 值级 diff 与 n_revision_events 为准。
5. 样本门槛（≥300 time_safe/联赛-季、完整赛季）不因进度降低。

## 4. 硬违规 → 立即 STOP（只报告，不自行绕过）

retrieved_at≥kickoff 被用作 time_safe 依据、historical_retro 混入、forward namespace 污染、scheduler 重复写入（非 recheck）、raw hash/provenance 丢失、revision audit 无法证明、store 非预期修改、冻结指纹变化、任何时间安全规则被绕过。以上由监控器 13 项 STOP 检测每小时自动巡查，触发即 exit 5 + dashboard STOP 段。

## 5. 当前判定

- **P2 维持 PENDING**：E1–E4 均未到真实时间；不修改代码制造完成条件。
- 运行时健康：全部组件运行中，观察自动化（600s/15min/60min 三层）已就位，事件发生即被客观记录。
- 预计事件时间线（依据真实赛程，非承诺）：E1 首窗 2026-09-13T20:30Z 起；E3 首批按期 t24 于 2026-09-14T04:59Z 后首个 capture 周期；E4 于 2026-09-20 后。
