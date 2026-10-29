# MATCH_REGISTRY_SPEC.md（Match Registry 设计）

性质：只读设计 + 只读生成（`match_registry_v1.jsonl`，19,763 行）；**不执行 DATA-006 join**。

## 1. Registry 字段
`match_id / league / season / canonical_home / canonical_away / kickoff_date / kickoff_time_local / kickoff_utc / temporal_tier / source_file / source_row / source_fingerprint`

- `match_id` = sha256(league|season|source_file|source_row)[:16]，可复现、可追溯回 Frozen Dataset → source CSV → source row。
- `canonical_home/away` 来自 `team_alias_registry.json`。
- `source_fingerprint` = 该行来源 CSV 的 SHA256（= source manifest 值）。

## 2. 分层身份规则
- **TIER_DATETIME（2019-20+）**：身份候选键 = `(canonical_home, canonical_away, kickoff_utc)`；12,459 行全部含 kickoff_utc（DST 已验证）。
- **TIER_DATE_ONLY（2015-18）**：仅 `(canonical_home, canonical_away, kickoff_date)` 日期级；`kickoff_time_local/kickoff_utc` 恒 null；**禁止伪造**；**禁止日期级强行与 DATA-006 lineup join**。

## 3. Collision 规则
- DATETIME 层以 `(canonical_home, canonical_away, kickoff_utc)` 去重检测 → **实测 0 碰撞**。
- 未来发现 collision：**STOP 并报告，不自动解决**。

## 4. 追溯链
`match_registry_v1.jsonl` → `provenance.source_file/source_row/source_hash` → `baseline_dataset.jsonl` → canonical CSV（`sha256_manifest.json` 校验）。

## 5. 约束
- 不修改 Frozen Dataset；不导入 DATA-006；不执行跨源 join。
- 产物指纹：`match_registry_v1.sha256` = `6ff0f82fcc918a01…`（全量值见文件）。
