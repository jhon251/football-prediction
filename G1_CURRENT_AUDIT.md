# G1_CURRENT_AUDIT — Understat Forward Scheduler 停摆审计

- 审计时间：2026-09-13T04:37Z（本地 UTC+8 12:37）
- 对象：`backtest_output/experiments/phase5_3_p1_understat_forward/forward_pipeline/scheduler.py` 及其部署/运行痕迹
- 前提确认（接受现状，不篡改）：M4/O2 3504 场 0 mismatch；P1 dry-run 12/12 PASS；生产 forward store 0 条 time_safe；scheduler 自 2026-08-25T15:45Z 停摆约 19 天；T+24h/T+7d revision audit 未执行。

---

## 1. 停摆真实原因（结论）

### 已确认（Evidence）

**R1 | 无任何 OS 级持久化机制 —— 根本原因。**
- 计划任务查询：全系统无任何匹配 `football/understat/forward/5.3/data` 的用户任务；精确查询 `*understat* / *forward* / *5.3*` = 0 个任务。
- 启动项：HKCU Run 键无相关条目；Startup 文件夹只有 `DATA006-LineupCaptureSupervisor.cmd`（lineup 管线的），**无 understat forward scheduler 对应项**。
- `SCHEDULER_RUN_REPORT.md` 自述部署方式为 "daemon mode, poll 600s, deployed 2026-08-25T10:03Z as a **managed background job**" —— 即终端后台进程，无 supervisor、无看门狗、无计划任务。
- 对照组（同仓 DATA-006 lineup 管线）通过 Startup `.cmd` → `watchdog.ps1` 存活至今（本次审计时 PID 14800 自今晨 09:59 开机后运行中）——证明本仓已有可行持久化模式，understat scheduler 部署时未采用。

**R2 | 进程随终端/机器消亡，且日志戛然而止。**
- `data/scheduler_state.json` last_run = 2026-08-25T15:45:23Z；`data/scheduler_runs.jsonl` 最后一批条目 15:44:37–15:45:23Z，无任何关闭/异常记录。
- 机器自 08-25 以来多次重启（本次审计时本次开机时间为 2026-09-13 09:59 本地）。
- **精确死亡时刻：Unknown** —— 无关机前心跳/退出记录，无法区分"终端关闭"与"关机"，只能确认 15:45:23Z 后再无任何运行痕迹。

**R3 | revision recheck 计划被新 capture 整体覆盖（潜在缺陷，审计中发现）。**
- `scheduler.py` one_cycle：每当新窗口 capture 成功，`st["revision_rechecks"][lg]` 被**整体替换**为新 capture 的 t24/t7d，旧基线的待执行 recheck 被孤儿化。
- 实例：08-24T15:22Z 基线的 T+24h recheck 应于 08-25T15:22Z 执行；但 08-25T10:02Z 的 captured_late 已把 E0/SP1/I1 的 recheck 重置为 t24=08-26T10:02Z → 15:44Z 周期到达时 `revision_due` 返回空，08-24 基线 recheck 被静默跳过。F1 的 recheck 从未进入最终 state。

**R4 | revision recheck 执行后不标记完成 → 一旦 t24 过期将每个 poll 重复 capture（失控缺陷，未触发）。**
- `revision_due` 只判断 `now >= t24 or now >= t7d`，执行后 state 不更新 → t24 过期后每 600s 重复 fetch+capture，直至进程死亡。因进程 08-25 死亡而**从未触发**（runs 动作统计中 0 条 revision_recheck）。

**R5 | SCHEDULER_RUN_REPORT.md 与实际状态不一致。**
- 报告称 T+24h recheck "executed by the daemon"（due 2026-08-25T15:22Z）；实际：runs 日志 0 条 revision_recheck，state 中 recheck 指向 08-26/09-01 且从未执行。报告的括号注记是预期写法，不是已发生事实——按审计纪律如实指出。

### 系统性弱点（Evidence，均为代码级确认）

- **R6** daemon 主循环无逐周期异常守卫：`load_state` JSON 损坏或任何意外异常 → 进程直接死亡（输出重定向时为静默死亡）。
- **R7** 无锁文件：双开会双 capture（append-only 下无害但污染 provenance 连续性）。
- **R8** RUNS_LOG/STATE 硬编码生产 store → 无法在沙箱测试 scheduler 而不写生产数据（这也是此前从未有 scheduler 级测试的原因）。
- **R9** provider 时间按 UTC 处理仅为代码注释（documented caveat），未进入 config/日志——窗口边界可能偏移数小时（偏保守方向：倾向 window_late）。
- **R10** 无运营缺口检测：停摆 19 天在系统自身任何日志/状态中都不可见（只能靠外部人工发现）。

## 2. 用户审计清单逐项核验（Evidence，代码+工件双重确认）

| 项 | 结论 |
|---|---|
| scheduler 启动入口 | `scheduler.py --once / --daemon`；08-25 以 managed background job 方式手动启动（报告自述），无持久化 |
| 任务计划/进程/锁 | 0 个计划任务；现无 scheduler 进程；无锁机制 |
| 日志 | `data/scheduler_runs.jsonl` 185 条、动作全覆盖（window_not_open 7 / no_results 37 / skip_dup 138 / captured_late 3 / **revision_recheck 0**）；missing_log 0 条 |
| 异常处理 | fetch/parse/drift 均有分支记录；但 daemon 主循环无兜底异常守卫（R6） |
| capture window 计算 | `window_status`：T+3h..T+6h after last fulltime（provider dt 按 UTC，caveat R9）；in_window/window_late/window_early/no_results 判定逻辑与协议一致（dry-run C05/N4/N6 已证） |
| UTC vs provider 本地时间 | 隐式约定，注释级存在（R9） |
| append-only 写入与去重 | capture 层拒绝重名文件（C08）；scheduler skip_dup 按 window_key；本次链完整性复核：8 条 registry 链 intact、raw sha256 全部匹配 sidecar 与 registry、parser_version 一致 |
| forward namespace guard | 拒绝非当前赛季注入（dry-run N1）；本次复核 8 条 sidecar `dq_namespace=forward` 全部一致 |
| historical_retro 排除 | dq_validation 命名空间隔离（dry-run N1b）；生产 store 0 条 historical_retro |
| retrieved_at 与 kickoff_utc 比较 | 管线层：窗口基于 fulltime；预测层（prediction module）：`retrieved_at < kickoff_utc`。二者语义不同且互补（结果采集保真 vs 特征时间可容许性），无混用 |
| time_safe/window_late/no_results 判定 | 判定正确；生产 store 实测：window_late 76、upcoming_fixture 2510、**time_safe 0** |
| T+24h/T+7d revision audit | **从未执行**（R3/R4/R5 三重缺陷叠加 + 进程死亡） |
| manifest/sha256/parser version/registry | 5 份 manifest 存在（冻结于首轮 capture，n_captures 按冻结时点）；sha 链/链式 registry 完好 |
| 静默失败/"在跑但没采集" | scheduler 自身每个分支都有日志（无进程内静默失败）；但**进程级死亡是完全静默的**（R6/R10），且 08-24 基线 recheck 被 recheck 覆盖缺陷静默吞掉（R3） |

## 3. 推测与未知（明确区分）

| 项 | 等级 | 说明 |
|---|---|---|
| 进程死于终端关闭或关机 | **Hypothesis** | 与无持久化 + 多次重启一致，但死亡瞬间无直接证据 |
| 若进程存活至 08-26T10:02Z，R4 失控将触发 | **Hypothesis** | 代码级必然，但当时未发生 |
| 停摆期间（08-26..09-12 各比赛日窗口）数据永久缺失 | **Evidence** | 各窗口关闭且从未捕获；未来只能以 window_late 补采（excluded from validation），time_safe 累积只能从恢复后的首个真实窗口起算 |
| provider 是否在停摆期间修订过历史 xG 值 | **Unknown** | 只能通过 re-fetch diff 观测（将作为 out-of-schedule recheck 执行并如实标注） |
| 外部是否有自动重启机制 | **Unknown→已排除** | 计划任务/启动项/进程三方面核查均无；结论改为：不存在（Evidence） |

## 4. 影响评估

- 历史结论不受影响：M4/O2、dry-run 12/12、冻结指纹均与本停摆无关（本审计未发现任何数据被篡改痕迹；append-only + sha 链完好）。
- Forward Validation 路线损失：08-26 至今各联赛所有比赛日的 time_safe 窗口全部错过（约 3-4 个比赛日/联赛），对应比赛只能以 window_late 存在或缺失，**不可进入 future validation**（协议规定，未改变）。
- 恢复后 time_safe 起算点 = 恢复后首个真实 in-window capture（预计为恢复当夜的 00:00–03:00Z 窗口，若 daemon 持续存活）。

## 5. 修复前提核对（进入实施前）

- 不触碰冻结数据 ✅（scheduler 仅只读 sha 校验）
- 不接纳历史回溯 ✅（retro guard 不动）
- 不伪造 time_safe ✅（修复不改变任何 DQ 判定；无法证明时间安全时仍返回 window_late/UNKNOWN）
- 不改 M4/O2、不改历史实验结果、不覆盖已有 raw response ✅（append-only 不变）
