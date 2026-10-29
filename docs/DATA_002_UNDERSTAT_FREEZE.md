# DATA-002：Understat xG/xGA 数据获取与冻结

> **性质：数据获取 + 清洗 + 时间安全设计 + 版本冻结 + 数据质量审计。**
> 仅获取与冻结数据，**不运行预测实验**（未计算 ΔBrier / LogLoss / ROI）、
> 不修改生产模型 / config / 35 条规则、不增加 Agent、不调参、不训练模型、不进入 V1.3。
> 继承：V1.2 冻结基线、DIAG-005 增量验证框架、DIAG-007 验证协议、DATA-001 审计结论。

---

## 0. 冻结数据概览

| 项 | 值 |
| --- | --- |
| **data_version** | `ae9e746b4654d8addb582bb3acf445ccbf575c72c31ede3f4f93be39f25cfa27` |
| **fingerprint** | `ae9e746b4654d8ad` |
| 来源 | Understat `getLeagueData/EPL/{season}` |
| 抓取时间 | 2026-08-19T05:14:42+00:00 |
| 解析版本 | `data_002_understat_freeze.py:v1` |
| 覆盖赛季 | 2024-25（隔离保留）、2025-26（主验证） |
| 滚动窗口 | 10 场（预注册） |

冻结产物（`data/xg/understat/`）：
- `raw/2024.json`、`raw/2025.json`（原始快照，sha256 见下）
- `normalized/matches_{season}.csv`（逐场：比赛 id、UTC 时间、主/客队、进球、双方 xG/xGA）
- `normalized/rolling_{season}.csv`（逐场：主/客队滚动 xG for/against、xG 差）
- `MANIFEST.json`（data_version + 全部文件 sha256）

---

## 1. 数据是否完整 —— **是**

| 检查项 | 2024-25 | 2025-26 |
| --- | --- | --- |
| 比赛数 | 380 | 380 |
| 已完赛（isResult） | 380 | 380 |
| xG/xGA 缺失 | 0 | 0 |
| 重复比赛 | 0 | 0 |
| 队名映射未命中 | 0 | 0 |
| 与本地真实比赛逐场对应（日期+队+比分） | — | **380/380 精确一致** |

## 2. 数据是否满足 DIAG-007 —— **是（滚动口径，已文档化）**

- 时间安全：对比赛 t，滚动特征只使用 `datetime < t.datetime` 的**严格先前**比赛；
  **不使用当前比赛的赛后 xG**、不使用含当前结果的 rolling、不使用未来信息；
  供应商后续修订不覆盖冻结版本（raw + normalized 均以 sha256 冻结）。
- 与 DIAG-007 §1.1 的对应：Understat **不提供逐记录原生 `xg_generated_at`**，
  故采用 DATA-001 审计预注册的**滚动口径**——滚动特征的有效「生成时刻」=
  窗口内最后一场比赛的结束时间（< 下一场 kickoff，泄漏结构上不存在），
  并以**抓取时刻 + 版本快照**满足版本管理要求。

## 3. 哪些记录被排除及原因 —— **无（0 排除）**

- 重复、缺失、未映射均为 0，无记录被排除。
- 2024-25 赛季（380 场）按纪律**隔离保留**，不进入主验证数据。
- 记录但**不排除**的异常值（如实报告）：2024-25 有 6 场 xG>5
  （如 Arsenal 6.05 vs Leicester、Tottenham 5.41 vs Man United、Chelsea 5.83 vs Southampton
  等），均为真实大比分场次，属合法数据而非错误；2025-26 无 xG>5 场次。

## 4. 是否存在任何无法解决的时间安全问题 —— **无（验证用途）**

- 泄漏检查：`leakage_detected=False`（两个赛季均通过）。
- 唯一注意项（非安全问题）：本地数据集 kickoff 标注为 `20:00:00Z` 而 Understat 为
  `19:00:00`（UTC）——**1 小时时区差**（UK 夏令时 BST=UTC+1 所致）；仅影响时刻字段，
  不影响日期对齐（按 `日期 + 主/客队 + 比分` 对齐已 380/380 精确一致），对验证无影响。
- 滚动特征的前 10 场为 None（赛季内无更早历史），符合预注册的 10 场热身窗口，
  与冻结 Elo 基线的赛季内 walk-forward 纪律一致，不构成泄漏。

## 5. frozen dataset fingerprint

- **data_version（复合）**：`ae9e746b4654d8addb582bb3acf445ccbf575c72c31ede3f4f93be39f25cfa27`
- **fingerprint**：`ae9e746b4654d8ad`
- raw sha256：`2024 = 3f192deb…`；`2025 = a5426263…`
- normalized sha256：`matches_2024/2025.csv`、`rolling_2024/2025.csv`（见 `MANIFEST.json`）

## 6. 是否可以进入 DIAG-008 —— **是（等待指令）**

数据完整、无泄漏、队名映射 100%、逐场对应 100%、版本已冻结。满足 DIAG-007 接入标准
（滚动口径）。**本阶段不运行预测实验**；DIAG-008 将在此冻结版本之上，按 DIAG-005
探针框架对 xG 单源做增量验证（ΔBrier ≤ −0.003、置换 p < 0.0071、split-half 一致）。

---

*数据获取与冻结完成。不运行预测实验、不修改模型、不进入 V1.3。按要求停止，等待下一步指令。*
