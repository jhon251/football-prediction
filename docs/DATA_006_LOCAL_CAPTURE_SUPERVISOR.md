# DATA-006：本地长期运行采集方案（Local Long-Running Capture Supervisor）

> **⚠️ 线状态：PAUSED（2026-09-29）** —— lineup 前向采集线实际停摆（1 场真实比赛、
> 0 time_safe、最新 manifest 2026-08-23），工程产出对 forward validation 无效。
> 暂停原因、恢复条件与处置边界见
> `backtest_output/data_005_lineup_live/PAUSED_STATUS.md`（不删除任何数据；
> supervisor 进程/启动项的停止需另行授权）。本文件以下内容保留为历史工程设计记录。

> **性质：工程设计 + 最小实现 + 测试 + 文档（不等待真实比赛、不产生样本）。**
> 目标：将 DATA-005 capture runner 与 DeepSeek Harness 生命周期**彻底解耦**，
> 消除「后台任务无法跨回合持续运行」这一已证实的工程限制，使 time_safe 样本
> 随真实赛季自然积累。
> 纪律：DATA-004/005 的时间安全规则与数据结构**不变**；不修改生产模型/V1.2
> baseline/config/35 条规则；不进入 DIAG-010；不运行预测实验；不计算
> ΔBrier/LogLoss/ROI；禁止赛后补抓与 time_safe 伪造；不需要现在产生样本。

---

## 1. 架构总览

```
fixtures_feed.py ──(ESPN scoreboard, 未来 7 天, 6 联赛)──▶ fixtures_feed.json
                                                               │
                                                               ▼
supervisor.py（长生命周期，独立于 Harness 运行）
  ├─ 读取 feed，逐场规划短生命周期 capture job（窗口 = kickoff−120min .. kickoff+20min）
  ├─ 窗口开启时 spawn「未改动的 DATA-005 runner」子进程（run-seconds 恰好覆盖窗口）
  ├─ 监控子进程：kickoff 前异常退出 → 重启（上限 3 次）；kickoff 后绝不重启
  ├─ 窗口结束 → 依据 store 是否有记录判定 complete / window_missed
  ├─ heartbeat / audit log / state 全部独立落盘
  └─ 崩溃恢复：重启后从 state 续跑；kickoff 已过而 supervisor 停机 → window_missed
                                                               │
                        数据/审计/日志（结构不变）              ▼
        backtest_output/data_005_lineup_live/store + data/lineups/prospective/supervisor/
```

**推荐方案：Windows Scheduled Task（单一常驻任务）**——开机自启 + 登录自启 +
任务级重启-on-failure（3 次/5 分钟间隔），supervisor 内部再按比赛窗口 spawn
短生命周期子进程。理由：无需安装服务/凭据，维护面最小，重启策略双层兜底，
且与「每次比赛一个短生命周期 job」的既定模式一致（第 6 点）。

## 2. 组件清单

| 组件 | 作用 |
| --- | --- |
| `scripts/lineup_capture/fixtures_feed.py` | 抓取 6 联赛（esp.1 优先、eng.1 次之、fra/ita/ned/bund 工程样本）未来 7 天 Scheduled/Pre-Game 比赛 → `data/lineups/prospective/fixtures_feed.json` |
| `scripts/lineup_capture/supervisor.py` | 常驻 supervisor：规划/启动/监控/恢复/审计（`--run-forever`、`--once`、`--max-runtime`、`--max-restarts`） |
| `scripts/lineup_capture/supervisor_launcher.ps1` | 任务启动器（日志追加到 `supervisor/launcher.log`） |
| `scripts/lineup_capture/install_task.ps1` | `Register-ScheduledTask` 安装/卸载（`-Uninstall`） |
| `scripts/lineup_capture/tests/test_supervisor.py` | 6 个单测（无网络、无真实 spawn，FakeRunner 注入） |

## 3. 启动/停止机制

- **常驻启动**：Scheduled Task（AtStartup + AtLogOn）→ `supervisor_launcher.ps1` →
  `python supervisor.py --run-forever --poll 60 --max-restarts 3`。
- **比赛生命周期**：每个 job 由 supervisor 内部管理——窗口未开 → `pending`（不 spawn）；
  窗口开 → spawn runner（`run-seconds` = 至 kickoff+20min 的剩余秒数，runner 自停）；
  窗口结束 → `complete` / `window_missed`。
- **停止**：卸载任务（`install_task.ps1 -Uninstall`）或删除 feed + 杀进程；
  每次 START/STOP/RESTART/PLAN/COMPLETE/MISSED 均写入 `supervisor_audit.log`（追加式）。

## 4. 故障恢复机制

| 场景 | 行为 |
| --- | --- |
| 子进程 kickoff 前异常退出 | 重启（`restarts < max_restarts=3`），每次 RESTART 审计 |
| 子进程 kickoff 后退出 | **不重启**；窗口结束按 store 记录判 complete/missed |
| supervisor 自身崩溃 | Scheduled Task 重启-on-failure（3 次/5min）；重启后从 state 续跑 |
| supervisor 停机期间比赛已 kickoff | 恢复后该 job → `window_missed`，**禁止事后补抓** |
| feed 过期/为空 | supervisor 继续空转，等待下次 refresh（`fixtures_feed.py` 手动或计划运行） |
| 同一比赛重复入 feed | `plan_jobs` 按 event_id 去重（已存在 job 不重建） |

## 5. 数据目录与 heartbeat 设计

- 捕获数据（结构不变）：`backtest_output/data_005_lineup_live/store/`
  （raw/{event}/…、normalized/{event}.jsonl、observations/{event}.jsonl、manifests/…）。
- 运营数据（新增）：`data/lineups/prospective/supervisor/`
  - `supervisor_heartbeat.json`：每次 tick 写入（timestamp、各 job 状态、running 列表）；
  - `supervisor_audit.log`：追加式审计（START/STOP/RESTART/PLAN/COMPLETE/WINDOW_MISSED/ERROR）；
  - `supervisor_state.json`：崩溃恢复依据（job 状态/restarts/pid）；
  - `logs/{event_id}.log`：子进程 stdout/stderr；
  - `launcher.log`：任务启动器日志。
- heartbeat 的用途：外部监控（Get-ScheduledTaskInfo / 文件时间戳）可判断 supervisor
  是否存活（>2×poll 未更新 = 异常）。

## 6. 时间安全（继承，未改动）

- `information_available_time < kickoff` 严格判定；ESPN 无原生 published_at →
  `time_trust='capture_proxy'`；kickoff 后首次捕获 → `time_safe=False`，不得补救。
- supervisor 不参与时间判定——只负责「在窗口内运行未改动的 runner」；
  任何对时间安全规则的修改均被禁止。

## 7. 最小测试与冒烟结果

- 单测 6/6（`test_supervisor.py`）：窗口数学、停机错过（window_missed 且不 spawn）、
  重启上限、窗口后 complete（依据 store 记录）、heartbeat/audit 落盘、state 续跑。
- 冒烟（合成 feed，无网络）：SMOKE-FUTURE → `pending`；SMOKE-PAST → `window_missed`
  （captured=False）；audit/heartbeat/state 全部生成 ✓。
- 全量测试：DATA-004 管线 9/9、supervisor 6/6、诊断套件 6/6（exit 0）。

## 8. 操作手册（部署后）

```powershell
# 1) 安装常驻任务（推荐方案 A）
powershell -ExecutionPolicy Bypass -File scripts\lineup_capture\install_task.ps1
# 2) 刷新 fixtures feed（可由任务手动或定期运行）
python scripts\lineup_capture\fixtures_feed.py
# 3) 检查
Get-ScheduledTask -TaskName DATA005-LineupCaptureSupervisor
Get-Content data\lineups\prospective\supervisor\supervisor_heartbeat.json
Get-Content data\lineups\prospective\supervisor\supervisor_audit.log -Tail 20
# 4) 卸载
powershell -ExecutionPolicy Bypass -File scripts\lineup_capture\install_task.ps1 -Uninstall
```

方案 B（独立进程）：`python scripts\lineup_capture\supervisor.py --run-forever` 前台/
nssm 注册服务；方案 A 为推荐。

*工程设计与最小实现完成。不等待真实比赛、不产生样本、不修改时间安全规则。按要求停止。*
