# DATASET_FREEZE_SPEC.md（Dataset Freeze 机制）

## 1. 原则
- 未来**任何数据变化**（新增赛季、替换文件、修正行）→ 产生**新 Dataset Version**，**禁止静默覆盖**。
- 冻结 = 产物 + manifest + 全部政策文档的可验证快照。

## 2. Freeze Manifest 字段

```json
{
  "dataset_id": "HIST_FD_5L_2015_2026",
  "dataset_version": "1.0.0",
  "status": "FROZEN",
  "build_timestamp": "<UTC ISO>",
  "build_config": {
    "build_spec_sha256": "<DATASET_BUILD_SPEC.md>",
    "canonical_schema_sha256": "<CANONICAL_SCHEMA.md>",
    "contract_sha256": "<DATASET_CONTRACT.md>",
    "registry_sha256": "<FEATURE_AVAILABILITY_REGISTRY.md>",
    "policy_sha256": "<policy/*.md 合并哈希>"
  },
  "policy_version": "policy.v1",
  "dataset_manifest": {
    "canonical_files": 55,
    "excluded_files": 17,
    "in_progress_files": 1,
    "raw_rows": 19765,
    "basic_qc_rows": 19763,
    "tier_date_only_rows": "<构建时计算>",
    "tier_datetime_rows": "<构建时计算>"
  },
  "source_fingerprint": {
    "manifest_ref": "manifests/sha256_manifest.json",
    "sha256_of_sha256_manifest": "<manifest 文件自身哈希>"
  },
  "schema_fingerprint": "<canonical 字段集合的有序哈希>",
  "row_checksum": "<产出文件 sha256>",
  "row_count": 19763,
  "limitations": ["L1", "L2", "L3", "L4", "L5"]
}
```

## 3. 版本规则
- 版本号 `X.Y.Z`：X=数据范围变化（加联赛/赛季）；Y=schema/policy 变化；Z=修正（同范围重建）。
- 例：补 2026-27 → `2.0.0`；修正尾部空行处理规则 → `1.1.0`。
- 每次 freeze 生成 `freeze/<dataset_version>/` 目录（产物 + manifest + 文档快照），旧版本**永不移除**。

## 4. 校验（解冻/复核用）
1. `sha256(磁盘 canonical 文件) == sha256_manifest.json`（逐文件）
2. `sha256(产物) == row_checksum`
3. 行数 == row_count
4. policy 文档哈希 == 记录值
5. 任一不一致 → 该版本状态降级 `TAMPERED`，不得用于训练/评估

## 5. 变更触发清单（产生新版本的事件）
- 新增/替换任何 canonical CSV（含 SP126 转正）
- excluded/canonical manifest 变化
- 政策文档（schema/temporal/registry/contract）任何修改
- DQ 报告升级（如 L2 被源证据更新）
