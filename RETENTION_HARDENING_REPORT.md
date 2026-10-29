# RETENTION_HARDENING_REPORT — 窗口留存率加固报告（任务 A/B/C/D）

- 日期：2026-09-29（UTC 14:26 开始事实核查，23:00 本地完成实施）
- 性质：基础设施加固。**零模型开发**：未触碰 M4/O2、`src/football_prediction`、冻结数据集
  （sha256 终检不变 `8f885fbc…3442`）、历史实验工件、既有 raw response（append-only 保持）。
- 三个前置风险的实测裁定（不默认简报正确）：

| 风险 | 简报说法 | 实测裁定 |
|---|---|---|
| R1 | 留存率 ~83%，09-19/20 周末 45 场断档 | **确认且更严峻**：按比赛日粒度实测近 30 天 in-window 留存率仅 **7.7%–17.6%**（见 A4 仪表）——简报的 83% 口径偏宽（按场 vs 按比赛日） |
| R2 | 09-29 单日 35 次 missing | **确认**：30× SSL UNEXPECTED_EOF（连接中途被切）+ 5× WinError 10061（连接拒绝），呈突发簇状 |
| R3 | 唤醒下次触发 10/11，复赛"约 10/3-4"，覆盖未证实 | **部分推翻**：新鲜只读探测（2026-09-29T14:26Z，实时抓取 5 联赛 payload）证实复赛为 **10-10/11**，简报的 10/3-4 与实时数据不符；现有唤醒覆盖与实际复赛对齐（逐窗口核验见 A1） |

## 任务 A：窗口留存率加固

### A1 唤醒覆盖核实与修复 ✅

- `schedule_wake_triggers.py` 升级：窗口计算改为**新鲜只读探测优先**（实时 fetch 5 联赛
  payload，落盘 `probes/`，绝不写入 forward store；存储 payload 作回退）——从源头关闭
  "基于过期赛程快照排唤醒"的风险。
- 逐窗口核验清单（窗口→任务名→触发时间）：`WAKE_COVERAGE_CHECKLIST.json`（60 个唤醒时刻，
  每项含 wake_task/hold_task 名与比赛日映射）。复赛首轮逐窗口核对：
  - D1/F1（10-10 周六）→ 窗口 10-11 02:00-05:30/02:30-05:30 当地 → `Wake-01`/`Hold-01` 02:15 ✅
  - E0（10-10 周六）→ 窗口 10-11 05:30-08:30 → `Wake-01`/`Hold-01` 05:45 ✅
  - I1（10-11 周日）→ 窗口 10-12 02:00-05:00 → `Wake-02`/`Hold-02` 02:15 ✅
  - SP1（10-11 周日）→ 窗口 10-12 04:00-07:00 → `Wake-02`/`Hold-02` 04:15 ✅
  - E0（10-11 周日）→ 窗口 10-12 04:30-07:30 → 并入 04:15 时刻 ✅
  - E0 周中轮（10-12 周一）→ 窗口 10-13 08:00-11:00 → `Wake-02`/`Hold-02` 08:15 ✅
- 覆盖范围至 2027-01-14（60 时刻上限）；**1 月中旬后的窗口需重跑脚本续期**（维护项，见 §限制）。

### A2 窗口期防睡眠 ✅

- 新增 `hold_awake.ps1`：`SetThreadExecutionState(ES_CONTINUOUS|ES_SYSTEM_REQUIRED)`，
  仅在窗口期保持系统唤醒（显示可关闭，不阻止手动睡眠），进程退出自动解除；**不做全天候电源策略修改**。
- 注册配对任务 `P53P1-ForwardWindowHold-01..04`（与 Wake 任务同触发时刻，`-Minutes 175`
  = 窗口开始+15min 起保持至窗口结束+10min；ExecutionTimeLimit=4h；WakeToRun=True）。
- 修复两个实施 bug（均有验证记录）：PS 的 0x80000000 被 当作 Int32 负数导致 uint 溢出
  （改用 `[uint32]2147483649` 字面量）；`install_startup.ps1` 生成的 .cmd 含断行
  （上次会话遗留，重写为单行并逐字节验证）。

### A3 URLError 告警 ✅

- `config.py` 新增阈值：`MISSING_WARN_CONSECUTIVE=3`、`MISSING_STOP_CONSECUTIVE=6`、
  `FETCH_RETRIES=3`、`FETCH_BACKOFF_S=(5,15)`。
- `monitor.py`：新增 `consecutive_missing_by_league()`（runs 日志尾部按联赛连续 missing 计数，
  遇非 missing 归零）；单联赛 ≥3 连续 → WARN；**全部联赛** ≥6 连续 → STOP（exit 5 + dashboard
  STOP 段）；`heartbeat.consecutive_missing_by_league` 入报告。
- `scheduler.py`：新增 `fetch_with_retry`（有界 3 次重试、5s/15s 退避；全部失败才记 missing，
  reason 注明 attempts）——直接对冲 R2 的 SSL EOF 突发；capture 与 recheck 两条抓取路径均接入。
- 回归测试：`tests/understat_forward/test_retention_hardening.py`（9 项：连续计数/归零/WARN/
  STOP 全联赛判定/重试成功/重试穷尽/missing 记录 attempts/留存计数/留存判定）。全套
  `tests/understat_forward/` **38/38 OK**。附带修正：生产 runs 日志断言从"计数不变"改为
  **append-only 校验**（允许活 daemon 合法追加，禁止缩水）。

### A4 留存率仪表 ✅

- `FORWARD_ACCUMULATION_STATUS.md/.json` 新增 "Matchday retention" 段：近 30 天按比赛日
  粒度 in-window 捕获率 + 全历史率 + 赛季末外推。判定口径：比赛日 D 留存 ⇔ 存在
  `window_status=in_window` 的 capture 覆盖 D 且 retrieved_at ∈ W(D)（W(D)=当日最晚开球+5h..+8h，
  与调度器窗口同定义）。
- 当前实测（2026-09-29）：留存率 E0 9.1% / SP1 17.6% / I1 7.7% / D1 10.0% / F1 9.1%；
  按当前留存率外推赛季末 time_safe：E0 71 / SP1 115 / I1 66 / D1 55 / F1 61 —— **全部远低于
  300 门槛（差 185–245）**。外推明确标注"按当前留存率的外推，非承诺；300 门槛不降"。
  该表正是加固前基线；10-11 复赛轮是机制生效后的第一个可比观测点。

### A5 观察验收 ✅（演练路径）+ 真实窗口待证

- **演练窗口（2026-09-29 22:52:52 当地，准时触发）**：临时 `P53P1-DrillCapture`（隐藏 capture
  路径）+ `P53P1-DrillHold`（防睡眠保持）同时触发——Capture result=3（命中 daemon 锁被拒=
  防双跑+capture 路径执行到锁检查）、Hold state=Running（SetThreadExecutionState 生效，
  2 分钟后自动释放）。触发→隐藏运行→锁检查→防睡眠保持，链路全程验证；演练任务已清理，
  生产 store 未受影响（captures 保持 53，无新批次写入）。
- **24h 检查点**：已注册 `P53P1-Retention24hCheck`（2026-09-30 22:54 自动重跑 monitor 并
  刷新 dashboard）——留存机制组件注册后的 ≥24h 持续运行将有自动落盘证据。
- **如实标注**：①Wake-from-sleep（WakeToRun=True）属 OS 承诺，会话内无法安全模拟真实睡眠
  （会挂起本会话），**未经真机睡眠验证**；首个真实窗口 **2026-10-11 02:15**（复赛轮）将由
  monitor/日志自动留证，是留存机制的最终实测点。②60 时刻覆盖至 2027-01-14，之后需重跑
  `schedule_wake_triggers.py` 续期（赛程变动时同理）。

## 任务 B：前向赔率采集管线设计（只设计，未写码）✅

`FORWARD_ODDS_ACQUISITION_DESIGN.md`（JSON 版 `.json`）。要点：候选 4 源评审（The Odds API
首选：双层时间戳语义+免费额度可承载+5 联赛覆盖；Betfair 备选（辖区 UNKNOWN）；OddsPortal
REJECTED-for-primary（ToS 禁抓+时间语义弱）；Pinnacle UNKNOWN（准入））；`forward_odds`
命名空间与 DQ 词表；快照不可变、价格变动≠修订；retrieved_at<kickoff 判定；到
prediction_input.v1 的映射与**庄家映射表预注册依赖**；管线草图逐项复用 xG 模式。
**三项决策请求留待用户：选源 → API key → 实现授权。**

## 任务 C：lineup 线处置 ✅

- `backtest_output/data_005_lineup_live/PAUSED_STATUS.md`：显式 **PAUSED（2026-09-29）**，
  含事实（1 场/0 time_safe/manifest 2026-08-23）、原因（ESPN 路径无法证明 time-safe 语义、
  恢复条件远未满足）、恢复条件（三项全满足才可申请）、处置边界（不删任何数据）。
- `docs/DATA_006_LOCAL_CAPTURE_SUPERVISOR.md` 头部加 PAUSED 指针（原内容保留为历史设计记录）。
- 未越权事项（如实列出，未实施）：supervisor 进程/启动项仍在运行，是否停止待授权；
  本线**不建议修复**——恢复条件第 1 条（时间语义可证明）在当前源上无法满足，修复无意义。

## 任务 D：顶层文档补图 ✅

README 新增"研究主线地图"：系统 A（沙盘，合成数据，非预测器）vs 系统 B（backtest_output
Phase 2A→5.3 真实研究主线，M4/O2 唯一已验证预测器）、当前位置、当前硬门槛、阅读指引。
消除审计缺口 G2。

## 纪律红线遵守声明

冻结数据集只读校验（终检 sha256 一致）；未接纳 historical_retro；未伪造 time_safe
（今日 0 新 capture，间歇期如实 skip_dup）；未修改 M4/O2/预测模块/历史实验/既有 raw response；
未做增量实验/未接信号进概率/无 Agent/Ensemble/betting/ROI/EV；300 门槛未降；
FAIL/UNKNOWN 如实登记（R3 简报数据不符、留存率严峻基线、wake-from-sleep 未验证等均如实写明）。

## 遗留与建议（不自行实施）

1. 10-11 复赛轮为留存机制首个真实观测点；建议当日查看 `FORWARD_ACCUMULATION_STATUS.md`。
2. 2027-01 中旬前重跑 `schedule_wake_triggers.py` 续期唤醒覆盖。
3. lineup supervisor 进程/启动项是否停运，待授权。
4. 赔率管线三决策（选源/key/实现授权）待用户。
