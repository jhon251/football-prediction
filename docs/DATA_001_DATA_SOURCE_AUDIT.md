# DATA-001：数据源可行性与获取审计（Data Source Feasibility & Acquisition Audit）

> **性质：审计报告 —— 无数据接入、无预测实验、无模型改动、无运行产物。**
> 目标：评估候选数据源是否满足 DIAG-007 新数据验证协议的接入标准，为后续 DATA-002 接入做准备。
> 纪律：不修改生产模型与 config；不接入数据；不运行预测实验；不调参；不增加 Agent；不进入 V1.3。
> 继承：V1.2 冻结基线、DIAG-005 增量验证框架、DIAG-006 数据价值评估、DIAG-007 接入标准。

---

## 0. 关键前提（审计口径）

DIAG-007 要求 `xg_generated_at < kickoff`。**本审计的诚实结论先行**：

> 公开 xG 源（Understat/FBref）**不提供逐记录的原生生成时间戳**，且只发布**赛后** xG。
> 因此「对当前预测场次的赛前 xG 快照」**不存在**；可满足 DIAG-007 的方式是：
> **滚动口径**（`xG 特征 = 截至 t−1 的滚动 xG`，其"生成时刻" = 窗口内最后一场比赛的结束时间，
> 天然 < 下一场 kickoff，泄漏结构上不存在）+ **运营侧版本快照**（防供应商事后修订）。
> 若要求「供应商原生生成时间戳字段」，公开源全部不满足 → 只能升级商业源。

---

## 1. xG/xGA 数据源审计

| 维度 | Understat | FBref（StatsPerform/Opta） | Opta / StatsBomb（商业） |
| --- | --- | --- | --- |
| 提供 xG/xGA | ✅ 逐场逐射门 xG/xGA | ✅ 逐场 xG/xGA（StatsPerform 模型） | ✅ 逐事件 xG（模型可配） |
| 覆盖范围 | EPL + 五大联赛 + 欧战 | EPL + 全球广覆盖 | 全量职业赛 |
| 历史数据 | ✅ 多赛季（≥2014） | ✅ 极长历史 | ✅ 长历史（付费） |
| 赛前快照 | ❌ 无逐场赛前 xG（仅赛后） | ❌ 同左 | ⚠️ 部分供应商提供 live xG（赛后修订） |
| 赛后修订 | ⚠️ 模型稳定、修订罕见 | ⚠️ StatsPerform 模型偶有更新 | ⚠️ 有修正流程 |
| 版本 fingerprint | ✅ 可（抓取快照即版本） | ✅ 可（需冻结抓取快照） | ✅ 可（供应商版本号） |
| 时间戳满足（DIAG-007） | ⚠️ 仅滚动口径 + 快照 | ⚠️ 同左 | ⚠️ 部分可含生成时间戳 |
| 成本 | 免费（无官方 API，用 [Python 库/抓取](https://dev.to/odeeb/understat-xg-data-export-how-to-pull-expected-goals-programmatically-python-csv-4l4b) 或 [Apify](https://apify.com/mirthful_radish/understat-xg-football-scraper)） | 免费查看/抓取（ToS 灰色，无 API） | 高（Opta 机构级；StatsBomb EPL 付费） |

**结论**：Understat 是**性价比最高**的 xG 源（免费、模型稳定、历史充分）；FBref 是
覆盖与历史的**备选**（但需冻结快照应对 StatsPerform 模型更新）；商业源（Opta/StatsBomb）
时间戳与版本管理最规范，但成本高，仅在免费源无法通过 DIAG-007 校验时考虑。

---

## 2. 首发阵容数据审计

| 维度 | 官方（PL 官方/俱乐部） | Sportmonks | TheSportsDB / API-Football |
| --- | --- | --- | --- |
| lineup_published_at | ⚠️ 规则保证 75 分钟前（[givemesport](https://www.givemesport.com/why-premier-league-team-lineups-are-announced-75-minutes-before-kick-off/)），但官方公开源未必带机器时间戳字段 | ⚠️ 提供 [lineups & formations](https://docs.sportmonks.com/v3/tutorials-and-guides/tutorials/lineups-and-formations) 与 [predicted lineups](https://docs.sportmonks.com/v3/tutorials-and-guides/tutorials/includes/predicted-lineups)；真实首发时间戳需以抓取时间记录 | ⚠️ 有 lineups 端点，时间戳以抓取为准 |
| lineup_last_change_at | ❌ 一般无 | ⚠️ 需自行记录抓取时间差 | ❌ 一般无 |
| 历史覆盖 | 逐场可回溯 | ✅ 结构化历史 | ⚠️ 免费档限制 |
| 缺失率估计 | 低（规则强制公布） | 低 | 中 |
| 是否满足 DIAG-007 | ⚠️ 满足「公布 < kickoff」事实，但需运营侧记录 `lineup_published_at`（抓取时刻），`last_change_at` 无法原生获得 | 同左 | 同左 |

**结论**：首发数据的**时间戳事实**由联赛规则保证（75 分钟前），DIAG-007 的
`lineup_published_at` 可由运营侧抓取时刻近似满足；`lineup_last_change_at` 在免费/中端源
基本缺失，需接受「最终版本在 kickoff 前抓取」这一折中并明确标注。Sportmonks 是
结构化历史覆盖最完整的中端选择。

---

## 3. 伤停数据审计

| 维度 | Premier Injuries | API-Football（api-sports） | Goalserve / 商业 |
| --- | --- | --- | --- |
| confirmed injury | ✅ 专注确认伤停（[Injury Data](https://www.premierinjuries.com/newsroom/injury-data)、[about](https://www.premierinjuries.com/about)） | ⚠️ 有 injuries 端点，但含存疑/恢复中混排 | ⚠️ 有 injuries 字段 |
| 时间戳可靠性 | ⚠️ 更新时刻可记录，但「确认时刻」未必原生结构化 | ⚠️ 以 API 返回/抓取时刻为准 | ⚠️ 中 |
| 历史覆盖 | ✅ 多赛季 | ⚠️ 免费档受限 | ✅ 付费 |
| 标注一致性 | ✅ 单一标准（confirmed/doubtful 分类） | ⚠️ 分类粗糙，需二次清洗 | ⚠️ 中 |
| 传闻/媒体推测 | ❌ 排除（本审计不采用 FotMob/媒体聚合） | ⚠️ 需自行过滤 | ❌ 排除 |

**结论**：Premier Injuries 是**唯一专门满足「confirmed injury + 时间戳 + 单一标准」**
的公开源，最接近 DIAG-007 §1.3；其「确认时刻」仍需运营侧在抓取时记录并冻结快照。
媒体聚合（FotMob/Rotowire 等）含推测，按纪律**排除**。

---

## 4. 成本与工程评估

| 数据源 | 价值 | 可获取性 | 成本 | 时间戳可靠性 | 推荐等级 |
| --- | --- | --- | --- | --- | --- |
| Understat xG | 高（DIAG-006 #1） | 高（免费抓取） | ≈0 | 中（滚动口径+快照） | **推荐（第一目标）** |
| FBref xG | 高 | 中（ToS 灰色） | ≈0 | 中（需版本冻结） | 备选 |
| Opta/StatsBomb xG | 高 | 低（商业谈判） | 高 | 高（原生版本） | 仅在免费源失败后 |
| 首发阵容（官方/Sportmonks） | 高（DIAG-006 #2） | 高 | 低-中 | **高（75 分钟规则）** | **推荐（并行第二目标）** |
| 伤停（Premier Injuries） | 中 | 中 | 低-中 | 中（确认时刻需记录） | 推荐（第三目标） |
| 媒体伤停聚合（FotMob 等） | 低 | 高 | ≈0 | 低（推测/事后） | **不投入** |
| 商业伤停/阵容（Goalserve 全量） | 中 | 低 | 高 | 中 | 不优先 |

**回答三个问题**：

1. **哪个数据源最适合作为第一个接入目标？**
   **Understat xG**（价值最高、成本≈0、模型稳定、历史充分；以滚动口径 + 版本快照满足
   DIAG-007 时间戳要求）。**首发阵容（官方 75 分钟规则 + Sportmonks）作为并行第二目标**
   —— 它的原生时间戳最强、与 Elo 结构性正交，且与伤停可打包同源。

2. **哪些数据源理论价值高但工程成本过高？**
   Opta / StatsBomb / Wyscout 级商业源：时间戳与版本管理最规范，但需商业采购、数据管线、
   法律条款，工程与预算成本远超当前诊断阶段所需；仅在免费源无法通过 DIAG-007 校验，
   且结论被第二赛季复测证实非噪声后，才值得投入。

3. **哪些数据源不值得投入？**
   无时间戳/推测性的媒体伤停聚合（FotMob、Rotowire 等）——按 DIAG-007 纪律严格排除；
   FBref 若无法在接入时冻结版本（StatsPerform 模型更新会导致历史值漂移），也不值得投入
   （改用 Understat）。

---

## 5. 结论与下一步

- 审计结论：**xG（Understat）与首发阵容（官方/75 分钟 + Sportmonks）是满足 DIAG-007
  接入标准的首选目标**；伤停（Premier Injuries）为第三目标；商业源暂缓；媒体伤停排除。
- 所有公开源均需**运营侧时间戳记录 + 版本快照**来满足 DIAG-007 的时间戳与版本要求；
  这一操作性折中已在审计中明确，不构成泄漏（滚动口径 + <kickoff 记录）。
- 下一步（仅设计，不在本阶段执行）：按 DIAG-007 §3 顺序，DATA-002 先接入 Understat xG
  并冻结版本，再接入首发/伤停。

*审计完成。不接入数据、不运行实验、不修改模型、不进入 V1.3。按要求停止。*
