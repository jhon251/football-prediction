# G1_VALIDATION_REPORT — Scheduler 恢复验证报告

- 验证时间：2026-09-13（UTC 04:37 审计起，05:04 任务首跑观察止）
- 方法：离线沙箱回归（注入 fetch、一次性 store）+ 沙箱实网端到端 + 生产运行 + 计划任务/锁行为观测
- 诚实声明：验证期间**没有任何 in-window 时段**，故未产生也无法产生任何真实 time_safe 记录；所有沙箱数据为合成比赛、事后丢弃；所有生产写入均为真实 fetch 且诚实标注。

## 1. 验证矩阵（用户要求逐项）

| # | 验证项 | 方法 | 结果 | 证据 |
|---|---|---|---|---|
| 1 | scheduler 启动/停止 | watchdog 拉起 daemon（PID 18116）+ `--status` 心跳 + 锁获取/释放/拒绝 | PASS | lock={pid:18116,mode:daemon}；heartbeat last_run 每 cycle 更新 |
| 2 | 重复运行幂等性 | 生产二连跑 + 沙箱 T2 | PASS | 第二轮 5×skip_dup、registry 13 条不变；沙箱同窗口二跑 0 新 capture |
| 3 | forward namespace 负例 | 沙箱注入 2020 赛季 capture（T5）+ 生产 13 条 sidecar 复核 | PASS | RuntimeError(retro injection)；13/13 条 dq_namespace=forward |
| 4 | historical_retro 拒绝 | 信号/捕获层守卫（dry-run N1b 沿用）+ 生产 store 复核 | PASS | 生产 store historical_retro=0；守卫未改动 |
| 5 | retrieved_at 缺失 | 管线路径不可能缺（capture 强制写）；特征可容许性由预测模块门 N5/N8 覆盖（前轮已验） | PASS（按层分工） | 管线层：retrieved_at 恒写入 sidecar+norm；预测层：缺失→UNKNOWN→CONDITIONAL |
| 6 | retrieved_at >= kickoff | 预测模块硬门（REJECTED）；scheduler 窗口门（window_early/window_late） | PASS | 两层语义分离且互补（capture 保真 vs 特征可容许） |
| 7 | provider 时间异常 | schema drift 守卫（T9）+ `_parse_dt` 回退（1970，文档化）+ 显式 UTC 约定（T13/每条日志） | PASS | drift→STOP flag+0 capture；窗口偏移方向保守（偏向 window_late） |
| 8 | raw response hash | 沙箱 T14 + 生产 13 条 raw sha256 vs sidecar vs registry 三方复核 | PASS | 0 不一致 |
| 9 | append-only | 重复 capture 拒绝（C08 沿用）+ 生产链式 registry prev_capture_id 全链完整 | PASS | 13 条链 intact；重复文件名触发 RuntimeError |
| 10 | revision audit | 沙箱 T6/T7（单次执行、无失控、missed 标注、同周期覆盖）+ 生产补执行 | PASS | E0/SP1/I1 补执行：points=[t24,t7d]、missed={t24:true,t7d:true}、t24 延迟 427.0h、t7d 283.0h、n_revision_events=0；新一轮 t24=2026-09-14T05:59Z、t7d=2026-09-20T05:59Z |
| 11 | no silent failure | T8/T9/T10/R6 测试 + 生产运行日志 | PASS | fetch 失败→missing、drift→STOP flag、损坏 state→cycle_error（daemon 存活）、72h 缺口→operational_gap_detected；生产实录 gap=445.2h |
| 12 | 未伪造比赛/时间 | 全部沙箱测试使用合成数据+一次性 store 并丢弃；生产 5 条 capture 均为真实 fetch（understat.com HTTP 200，raw sha256 记录在案） | PASS | 无任何合成数据进入生产 store |

## 2. 当前真实状态（截至 2026-09-13T05:04Z）

- **真实 time_safe 数量：0**（与停摆前一致——恢复时刻无任何窗口开启；不伪造）。
- 生产 store：13 条 capture（8 条停摆前 + 5 条本次真实补采 window_late），链完整、sha 全对、命名空间纯净；dq 总量：window_late 250、upcoming_fixture 4088、time_safe 0、historical_retro 0。
- 运行层：daemon（600s）+ watchdog 运行中；计划任务每 15 分钟 `--once`（Ready，首跑被锁拒绝=防双跑生效）；Startup 自启待用户手动安装（沙箱拒绝写入，见实施报告 §3）。
- 补采的 5 条 window_late 记录（含 08-26..09-12 错过的比赛日数据）**永远不进入 future validation**——仅作 provenance 连续性与观测用途。

## 3. 仍需等待的真实窗口与首次真实 capture 验收标准

下一个真实窗口（provider 赛程，按 provider-naive-UTC 约定）：各联赛 2026-09-13（周日）比赛日开球后 T+3h..T+6h，即约 2026-09-13T23:00Z..2026-09-14T03:00Z 区间（E0/SP1/I1/F1/D1 各自随实际开球时间浮动）；之后每个比赛日一次。

首次真实 time_safe capture 的验收清单：
1. run 日志出现 `captured_in_window`（非 captured_late）；
2. 该 capture 的 norm 记录 `dq_status=time_safe` 且 `window_status=in_window`；
3. registry 新条目 raw_sha256 与 raw 文件/sidecar 一致，链式 prev_capture_id 延续；
4. `retrieved_at` 早于下一次预测目标的 kickoff（供未来增量实验的特征可容许性）；
5. 时间累计进入 ACCUMULATION_STATUS（目标 ≥300 time_safe/联赛-季，完整一赛季，期间 T+24h/T+7d recheck 按期执行、延迟接近 0）。

## 4. 最终结论

- **scheduler 是否恢复：是** —— 代码硬化完成、真实补采与幂等/锁行为经生产验证、双层持久化（计划任务已注册 + 本次会话内 watchdog/daemon 运行中）；唯一残留：Startup 自启需用户手动执行一次安装器（沙箱权限拒绝，未伪造完成）。
- **是否产生真实 time_safe：否**（当前无窗口，0 条，不伪造）——首个 time_safe 预计在下一真实窗口，按 §3 清单验收。
- **revision audit 是否执行：预注册时点已错过（不可追补）；逾期补执行已完成并如实标注** —— E0/SP1/I1 的 T+24h/T+7d 以 out-of-schedule 方式补执行（观测性，n_revision_events=0）；全部 5 联赛已排定新的按期 recheck 计划。
