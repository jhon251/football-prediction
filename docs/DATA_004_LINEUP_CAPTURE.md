# DATA-004：前瞻首发实时采集管线（Prospective Lineup Capture Pipeline）

> **性质：管线 + 单元测试 + dry-run + schema 验证（全部基于 mock，明确标注）。**
> 不伪造历史 time_safe 数据；当前无进行中的英超比赛，**无真实验证样本**，mock 不冒充。
> 禁止落实：不修改生产模型/config/35 条规则；不调参、不训练；不运行预测/ROI 实验；
> 不接入伤停/市场赔率；不进入 V1.3。
> 继承：DIAG-007（时间戳门槛）、DATA-001（来源审计）、DATA-003（追溯数据 time_safe=False 结论——
> **历史 FINAL XI 不得作为赛前特征**，本管线解决的是**未来赛季**的赛前捕获）。

---

## 1. 时间模型（三个时钟，全部 UTC-aware）

| 时钟 | 定义 | ESPN（实际源） |
| --- | --- | --- |
| `source_event_time` | 供应商原生的**发布时间** | **null**（ESPN 不提供） |
| `capture_time` | 本系统**轮询观察到**该状态的时刻 | 记录 |
| `kickoff_time` | 赛程开球时间（随延期/改期刷新） | 记录 |

- `information_available_time = source_event_time`（若存在）否则 `capture_time`。
- `time_safe = information_available_time < kickoff_time`（**严格不等式**，边界即失败）。
- **禁止行为**：不用抓取时间冒充发布时间（`time_trust='capture_proxy'` 明确标记）；
  不事后根据最终首发反推时间；无法证明 kickoff 前可得的记录一律 `time_safe=False`。
- capture-proxy 的成立依据：**不可变快照 + capture_time 本身就是「本系统在 kickoff 前已持有该信息」的证据**——这正是 DIAG-007 要求的时间安全证明（对系统可用性的证明，非对供应商发布时间的声称）。

## 2. 采集机制

- **启动**：`kickoff − pre_window`（默认 120 分钟）或启动时刻取较晚者；
- **轮询**：默认每 120 秒一次（可配）；`kickoff` 前持续轮询；
- **版本机制**：每次观察到的首发**内容变化** → 保存**新版本**不可变快照（`v1, v2, …`）；
  内容不变 → 不产生新版本（重复 snapshot 检测）；
- **截止**：`kickoff` 后停止赛前主快照写入（post-kickoff 观察仅记录、`time_safe=False`）；
- **答案可查询**：`last_known_pre_kickoff(event, source, kickoff)` =
  `max(capture_time < kickoff)` 的版本（dry-run 已验证可回答「kickoff 前最后一次已知首发」）。

## 3. 失败处理矩阵（实现 + 测试覆盖）

| 场景 | 处理 | 测试 |
| --- | --- | --- |
| API 暂时不可用 | 记录 poll observation（source_error）+ 重试，循环继续，不写坏状态 | ✅ 单测（failures≥1 后恢复） |
| lineup 尚未发布 | 记录 no_lineup_yet（含 poll_time），继续轮询 | ✅ dry-run E2 前段 |
| 发布后发生变化 | 内容变化 → 新版本快照 | ✅ 单测 + dry-run E1（热身伤变更 v1→v2） |
| 比赛延期 / kickoff 变化 | 周期刷新赛程；窗口延长；记录 kickoff_updated/postponed 标志；旧快照保留 | ✅ 单测 + dry-run E4 |
| 源返回赛后 FINAL XI | capture_time ≥ kickoff → 自动 `time_safe=False`，不进入 time_safe 数据集 | ✅ 边界单测 |
| source 时间戳缺失 | `source_event_time=null`、`time_trust='capture_proxy'`，按 capture 证据判定 | ✅ 单测（naive→UTC、优先级） |
| 两来源冲突 | 保留双方快照 + `conflict=true` 标记，不静默合并 | 字段已实现（当前单源 ESPN，冲突路径留待第二源接入） |

## 4. 测试与验证结果

- **单元测试 9/9 通过**（`scripts/lineup_capture/tests/test_pipeline.py`）：
  时间戳边界（1s 前=安全/恰在 kickoff=不安全/1s 后=不安全）、时区（naive 强制 UTC）、
  原生发布时间优先级、不可变快照（同路径异内容→异常）、重复快照（内容不变→单版本）、
  阵容变化→新版本、源异常→安全降级、比赛延期→窗口延长且记录保留。
- **dry-run 4 mock 事件**（`backtest_output/data_004_lineup_capture/dryrun/`，全部 `mock=True`）：

| 事件 | 场景 | versions | time_safe | 结果 |
| --- | --- | --- | --- | --- |
| MOCK-E1 | 正常 + 末刻伤停变更 | 2 | 2/2 | last-known-pre-kickoff=11 人（含变更）✅ |
| MOCK-E2 | 正常无变化 | 1 | 1/1 | 重复内容不产生新版本 ✅ |
| MOCK-E3 | 源故障后恢复 | 1 | 1/1 | 安全降级后恢复捕获 ✅ |
| MOCK-E4 | 延期/kickoff 变化 | 1 | 1/1 | 窗口延长、标志记录 ✅ |

- **immutability check**：全部快照 sha256 与记录一致（OK）。
- **store fingerprint**：`9b304f4853d47597`（dry-run 产物）。
- **schema 验证**：所有记录经 pydantic `CaptureRecord/LineupState/CaptureManifest`
  `model_validate` 往返校验（verify 步骤内置）。

## 5. 验收标准回答（七问）

1. **是否能够真实捕获赛前首发？** 机制就绪（ESPN 适配器 + polling + 版本快照 + dry-run 验证）；
   真实验证需**下一真实赛季**（当前无进行中的英超比赛；本阶段不伪造）。
2. **是否能够证明信息在 kickoff 前可用？** 能（capture-proxy 证据）：不可变快照 +
   `capture_time < kickoff` 严格判定；原生发布时间缺失时 `time_trust='capture_proxy'` 明确标记，
   绝不冒充发布时间。
3. **是否能够捕获末刻首发变化？** 能：内容变化→新版本（dry-run E1 热身伤停变更 v1→v2 已验证）。
4. **是否能够保存不可变历史快照？** 能：写入即不可变（冲突→异常），sha256 全程校验，
   禁止覆盖。
5. **数据源故障时是否安全降级？** 能：错误→记录+重试+继续，不产生坏状态（单测验证）。
6. **是否可以在未来真实赛季形成 ≥100 场 time_safe 样本？** 管线能力上可覆盖整个赛季
   （380 场 polling 成本极小）；**但**取决于源是否在 kickoff 前发布首发（ESPN capture-proxy
   机制可行），且**必须真实赛季实弹验证**——mock 不算样本，本阶段不作此承诺。
7. **是否满足 DIAG-007 的所有准入条件？** 设计按 DIAG-007 对齐（严格时间戳门槛、
   缺失率阈值、不插补、版本管理、时间可信度标记）；单测 + dry-run + schema 校验通过；
   实弹验证待下一赛季。

## 6. 产物

- `scripts/lineup_capture/`（models / adapters / storage / pipeline）+ `tests/test_pipeline.py`（9 测试）
- `scripts/data_004_lineup_capture.py`（CLI：`--dry-run` / `--verify` / `--fingerprint` /
  `--capture-loop --event <id>`）
- `backtest_output/data_004_lineup_capture/dryrun/`（mock 快照、记录、observations、manifests、
  dryrun_results.json、9 个冻结目录哈希）
- 未来实弹存储目录预留：`data/lineups/prospective/`（未写入——无真实验证样本）

*管线建立完成。mock 数据不冒充真实验证样本；不进入 V1.3。按要求停止，等待下一步指令。*
