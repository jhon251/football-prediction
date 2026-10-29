# TEAM_NORMALIZATION_REPORT.md（Team Normalization Dictionary 报告）

性质：只读，基于 FROZEN v1.0.0 与项目内三源文件；不修改任何数据。
产物：`team_alias_registry.json`（163 条）+ `team_registry_selfcheck.json` + `team_alias_registry.sha256`。

## 1. 完成情况
- 扫描 Frozen Dataset 全部 **163 个源队名**（E0 34 / SP1 31 / I1 35 / D1 30 / F1 33）。
- 每队记录：source_name / canonical_name / league / valid_from / valid_to / seasons / aliases / confidence / evidence / review_required / notes。
- 规则：**显式映射（证据）→ 否则身份映射**；**严禁字符串相似度自动合并**。

## 2. 归一化口径
- 身份映射（canonical = source）：104 条 —— 全部 confidence=HIGH（不改变任何身份，天然正确）。
- 显式 canonical 化：59 条，来源仅三类：
  1. **文件证据**（understat 原始 JSON / ESPN lineup / DATA-006 live 真实队名）；
  2. **用户点名**（Man United/Manchester United、Nott'm Forest/Nottingham Forest、Ath Madrid/Atl. Madrid）；
  3. **无歧义通用名**（如 Sociedad→Real Sociedad、Ein Frankfurt→Eintracht Frankfurt）。
- **反例保留（未合并）**：`Paris FC` ≠ `Paris SG`；`Ajaccio GFCO` ≠ `Ajaccio`；`Ath Bilbao` ≠ `Ath Madrid`。

## 3. 关键变体处理
| 源 | canonical | aliases |
|---|---|---|
| Man United | Manchester United | Man United / Manchester United |
| Nott'm Forest | Nottingham Forest | Nott'm Forest / Nottingham Forest |
| Ath Madrid | Atletico Madrid | Ath Madrid / Atl. Madrid（2026-27 格式） |
| Hull | Hull City | Hull（fd）/ Hull City（DATA-006） |
| Ath Bilbao | Athletic Club | Ath Bilbao（fd）/ Athletic Club（DATA-006） |
| La Coruna | Deportivo La Coruña | La Coruna / Dep. A Coruna（2026-27） |

## 4. REVIEW_REQUIRED = **85**
- 定义：非英超、且 canonical=source（无项目内跨源文件证据）的球队。
- 说明：这些球队在项目内**没有** ESPN/understat/DATA-006 数据可作别名证据 → 身份映射（正确、不合并）+ 标记 REVIEW_REQUIRED，等未来西班牙/意大利/德国/法国数据源到达后补充别名。**非英超跨源 join 当前不可行（L5 维持）。**

## 5. 自检结果
| 检查 | 结果 |
|---|---|
| canonical collision（同一 canonical 被多个源名合并） | **0** ✓ |
| same source → multiple canonical | **0** ✓ |
| multiple source → one canonical（错误合并） | **0** ✓ |
| unmapped source names | **0** ✓ |
| impossible league | **0** ✓ |
| fingerprint | `c1e7b55e355dbbbb9aed9e5d4ee9a2ba87148ac3055194f7b079121a580d3088` |

## 6. 结论
规范化字典通过全部自检；英超具备跨源别名证据（可 join），非英超为身份映射 + REVIEW_REQUIRED（跨源 join 被 L5 阻塞，符合预期）。Frozen Dataset 与原始 CSV 零改动。
