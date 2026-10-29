# G1_IMPLEMENTATION_REPORT — Understat Forward Scheduler 恢复实施报告

- 日期：2026-09-13（UTC 05:01 恢复运行）
- 审计依据：`G1_CURRENT_AUDIT.md/.json`
- 改动范围：仅 `phase5_3_p1_understat_forward/forward_pipeline/`（config.py、scheduler.py）+ 新增 `watchdog.ps1`、`install_startup.ps1` + 新增 `tests/understat_forward/`
- 未触碰：冻结数据集（sha256 终检不变）、`pipeline.py` 采集语义、M4/O2 与预测模块、全部历史实验工件、已有 raw response（append-only 保持）

## 1. 修复内容（对应审计 R3–R10）

| 审计项 | 修复 | 落点 |
|---|---|---|
| R3 recheck 计划被新 capture 覆盖（孤儿化） | league loop 之前快照 pending 计划，loop 之后对快照执行/覆盖执行；逾期检查点不再被静默丢弃 | `scheduler.one_cycle` |
| R4 recheck 不标记完成 → 失控重复 capture | 执行后写 `t24_done/t7d_done`；`revision_due` 跳过已完成检查点；同周期已有 capture 时以 `revision_recheck_covered_by_capture` 覆盖（同一 diff vs first capture），不重复 fetch | `scheduler.revision_due/_run_revision_rechecks` |
| R6 daemon 无异常守卫（静默死亡） | 逐 league `try/except`→`league_cycle_error`；整周期守卫→`cycle_error`；recheck 守卫→`recheck_cycle_error`；全部落 runs 日志 | `scheduler.one_cycle/daemon` |
| R7 无锁 | `scheduler.lock`（pid+mode+acquired_at），新鲜期 30 分钟；过期接管；`--once/--daemon` 均遵守 | `scheduler.acquire_lock/refresh_lock/release_lock` |
| R8 状态/日志硬编码生产 store | state/runs-log/lock 全部由 `store` 参数派生（默认仍为生产 `data/`，向后兼容）；沙箱可测 | `scheduler._runs_path/_state_path/_lock_path` |
| R9 provider-UTC caveat 隐式 | `config.PROVIDER_DATETIME_CONVENTION` 显式常量，写入每条 run 日志 | `config.py` + `log_run` |
| R10 停摆不可见 | `last_run` 距今 > `GAP_ALERT_HOURS`(48h) → 记录 `operational_gap_detected`（含 gap_hours） | `scheduler.one_cycle` |
| 部署/进程/锁缺失（R1） | ① 用户级计划任务 `P53P1-UnderstatForwardScheduler`（每 15 分钟 `--once`，IgnoreNew 防并行，StartWhenAvailable 补跑）已注册 **Ready**；② `watchdog.ps1`（5 分钟巡检，锁过期即重启 daemon）+ `install_startup.ps1`（Startup 文件夹安装器） | 新增文件 + 计划任务 |

新增 CLI：`scheduler.py --status`（只读输出 state/lock/最近 runs/capture 计数）。

## 2. 恢复运行实录（生产 store，真实 fetch）

2026-09-13T04:59:34Z `--once`：
- `operational_gap_detected` gap_hours=445.2（停摆首次进入系统自身日志）；
- 5 联赛真实补采：`captured_late`（window_status=window_late，**excluded from future validation**），registry 8→13 条，链式 prev_capture_id 完整，raw sha256 与 sidecar/registry 三方一致；
- E0/SP1/I1 逾期 revision recheck 以 `revision_recheck_covered_by_capture` 补执行：scheduled_points_covered=[t24,t7d]，**pre_registered_points_missed={t24:True, t7d:True}**，延迟 t24=427.0h、t7d=283.0h 如实记录；diff vs first capture（08-24 基线）观测结果 **n_revision_events=0**（基线 9–16 场 xG 未被修订）；
- F1 无待执行 recheck（其计划在部署前即孤儿化，见审计 R3 实例），本轮 capture 的 revision_events 已覆盖同等观测；
- 05:00:15Z 幂等复跑：5 联赛全 `skip_dup`，0 新 capture，registry 保持 13 条。

## 3. 当前持久化状态（如实）

| 层 | 状态 |
|---|---|
| 计划任务（15 分钟 `--once`） | ✅ 已注册，State=Ready，NextRunTime 正常；首跑 LastTaskResult=3（命中 daemon 锁被拒 → 防双跑按设计生效），registry 未增加任何重复 capture |
| daemon（600s 轮询）+ watchdog（5 分钟巡检） | ✅ 本次会话内已启动并运行（watchdog 检测无新鲜锁 → 拉起 daemon PID 18116；daemon 每 cycle 刷新锁；心跳 last_run 持续更新） |
| Startup 文件夹自启（重启后自动拉起 watchdog） | ⚠️ **未完成**：本执行环境的沙箱拒绝写入 Startup 文件夹（PowerShell 与 bash 均 Permission denied）。已提供 `install_startup.ps1`（含 -Uninstall）；需在正常终端手动执行一次：`powershell -ExecutionPolicy Bypass -File install_startup.ps1`。在此之前，机器重启后由计划任务层（15 分钟 `--once`）维持采集，仅丢失常驻 daemon 层 |

## 4. 回归测试

`tests/understat_forward/test_scheduler.py`：**17/17 OK**（离线、一次性沙箱、注入 fetch；生产 store 仅只读断言"未被触碰"）。覆盖：
- 窗口判定与 DQ（in-window→time_safe；window_late 永非 time_safe）；
- 幂等（同窗口二跑 skip_dup、0 新 capture）；
- forward namespace 拒绝 retro 注入（2020 赛季 → RuntimeError）；
- raw sha256/sidecar/registry 三方一致；generated_at/published_at 恒 None；
- fetch 失败 → missing 日志 + 0 capture；schema drift → STOP flag + 0 capture；
- 运营缺口检测（72h → gap 条目）；每条日志携带 provider-UTC 约定；
- league 级故障隔离（SP1 missing，E0/I1 照常 captured）；
- R6 守卫（load_state 损坏 → cycle_error 记录，daemon 存活返回 0）；
- recheck 单次执行无失控（R4）、逾期点 missed 标注 + 延迟（R3 语义）、同周期 capture 覆盖（无多余 fetch）；
- 锁：新鲜锁拒绝、过期锁接管、持锁时 daemon 拒启（exit 3）。

另：sandbox 实网验证（真实 fetch、一次性沙箱、事后丢弃）确认端到端真实链路：5 联赛 captured_late、174 window_late + 1578 upcoming_fixture、registry/sidecar/sha 完整。

## 5. 硬性禁止遵守情况

未把 dry-run 当真实数据（dry-run 工件未动）；未把 window_late 当 time_safe（全部窗口外补采诚实标注）；未使用 CLOSING/historical_retro（store 内 0 条）；未推断 generated_at/published_at（新 5 条 sidecar 实测恒 None）；未修改冻结数据（终检 sha256 不变）；未让 Understat 触碰 M4/O2 概率（预测模块未改）；未设计 Agent/Ensemble/增量实验/betting。
