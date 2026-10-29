# DATA-003：首发阵容数据获取与冻结（Lineup Data Acquisition & Freeze）

> **性质：数据获取 + 规范化 + 时间安全验证 + 版本冻结 + 数据质量审计。**
> 仅接入「首发阵容数据」；不接入伤停/xG/市场赔率/新 Agent。不运行预测实验
> （未计算 ΔBrier/LogLoss/ROI）；不修改生产模型/config/35 条规则；不调整 Elo/参数；
> 不根据数据质量结果反向修改验证规则；不进入 V1.3。
> xG 特征工程已正式停止（DIAG-009），本阶段未启用任何 xG 数据。

---

## 0. 数据源决策（与 DATA-001 审计的差异，如实记录）

DATA-001 推荐官方/Sportmonks 结构化源。本环境实测：
Sportmonks / API-Football 需 API 凭证（不可用）；FBref 与 worldfootball.net 返回 **403**；
TheSportsDB 免费测试 key 每赛季仅返回 5 场；Wikipedia API 超时；Sofascore **403**。
唯一可访问且提供两赛季结构化历史首发的是 **ESPN 公开 JSON API**
（`site.web.api.espn.com`：team schedule + per-event summary 的 `rosters` 字段，
含 `starter` 标志与阵型）。**采用 ESPN 作为实际来源**，原因已如上记录
（`MANIFEST.json` 与 `audit.json` 亦存档），非静默替换。

## 1. 时间安全结论（先行声明）

ESPN 的 summary 名单是**赛后已知的最终首发**（FINAL XI）：
- **无 `lineup_published_at`**（赛前公布时间不可追溯恢复）；
- **无 `lineup_last_change_at`**（赛前版本演变不可恢复）；
- 热身受伤等**赛前末刻变更**无法追溯。

因此按 DIAG-007 §1.2：**全部 760 条记录 `time_safe=False`、`unstable_lineup=True`，
0 场可进入时间安全主探针**。冻结数据集的价值 = 最终首发档案 + 前瞻采集管线基础
（英超 75 分钟规则使**未来赛季**的实时抓取可以满足时间安全），而非赛前输入。

## 2. 数据概览与 fingerprint

| 项 | 值 |
| --- | --- |
| **fingerprint** | `4f32ab99593cc556` |
| data_version | `MANIFEST.json`（full sha256，含 760 个原始快照哈希 + normalized CSV） |
| 来源 | ESPN 公开 JSON API（retroactive summaries） |
| 覆盖 | 2024-25：380/380；2025-26：380/380 |
| 原始快照 | `data/lineups/espn/raw/{event_id}.json`（760 个） |
| normalized | `data/lineups/espn/normalized/lineups_all.csv`（760 行） |
| 时间安全 | `lineup_published_at` 空、`lineup_last_change_at` 空、`time_safe=False`、`unstable_lineup=True`（全部） |

## 3. 数据质量审计结果

| 检查项 | 结果 |
| --- | --- |
| 两赛季覆盖率 | 760/760（各 380，含 18 场经 scoreboard 补漏） |
| 比赛映射率 | 2025-26 本地 380/380；2024-25 Understat 380/380；未映射 0 |
| 缺失率 | **0.0%**（DIAG-007 阈值 10%，满足） |
| 重复记录 | 0 |
| 球员 ID 映射 | 8360 个首发槽位、615 个唯一球员 ID（11×760 精确） |
| 阵容人数异常 | 0（全部 11 人首发） |
| 时间戳完整性 | `lineup_published_at` 完整率 **0%**（追溯源不提供） |
| unstable_lineup 比例 | **100%**（760/760） |
| 赛后信息泄漏 | 存在结构性风险（FINAL XI 冒充赛前信息）→ 已按 `time_safe=False` 全部隔离 |

## 4. 七个问题的回答

1. **数据是否完整？** 比赛覆盖完整（760/760，阵容解析 100%、人数异常 0）；但**时间安全完整性为 0%**（无公布时间戳）。
2. **时间戳是否足以满足 DIAG-007？** **不足** —— 追溯源不提供 `lineup_published_at` / `lineup_last_change_at`，无法验证 `公布时间 < kickoff`。
3. **是否存在无法解决的时间安全问题？** **存在（追溯口径）** —— 最终首发 ≠ 赛前已知首发，末刻变更不可恢复；对 2024-25/2025-26 **无法解决**；唯一出路是**前瞻实时抓取**（75 分钟规则）。
4. **有多少比赛可以进入未来主 probe？** **0 场**（全部记录未通过 DIAG-007 时间戳门槛）。
5. **fallback / unstable / missing 比例？** missing **0%**；unstable_lineup **100%**；time_safe **0%**；fallback 不适用（未运行探针）。
6. **数据 fingerprint 是什么？** `4f32ab99593cc556`（full data_version 见 `data/lineups/espn/MANIFEST.json`）。
7. **是否可以进入 DIAG-010？** **本追溯数据不可以**进入时间安全主探针。DIAG-010 需要先具备时间安全的首发数据（前瞻采集）；本冻结数据作为最终首发档案 + 采集管线基础 + 审计证据保留。

## 5. 结论与下一步（仅设计，不执行）

- 追溯期（2024-25/2025-26）的首发数据**无法满足 DIAG-007 时间安全门槛**，0 场可进入
  主探针 —— 这是数据现实，非实现缺陷；未修改任何验证规则来迁就数据。
- 下一步建议（设计待定）：**DATA-004 前瞻首发采集管线**（新赛季按 75 分钟规则实时
  抓取 `lineup_published_at` 与末刻变更，满足 DIAG-007 后 D7.2 才有时间安全基础）。

*获取与冻结完成。不运行预测实验、不修改模型、不进入 V1.3。按要求停止。*
