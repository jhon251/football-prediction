# PREDICTION_MODULE_SPEC — 最小预测模块规格（v0.1.0，2026-09-13）

依据：`CURRENT_SYSTEM_AUDIT.md`（验收结论）与 `PREDICTION_MATRIX.md`（矩阵不变式）。
原则：**复用已验证的 M4/O2，不重写算法；不训练模型；不接外部信号进概率；缺数据返回显式状态。**
本模块是最小可运行预测组件（研究型预测 API/CLI），不是 Agent，不是下注系统。

---

## 1. 位置与形态

- 包：`src/football_prediction/`（与 `football_simulation` 平级，不改动旧引擎）。
- 接口：CLI（`python -m football_prediction.cli predict --input match.json [--pretty]`）+ Python API（`football_prediction.predictor.predict_match(input_dict)`）。
- 依赖：仅标准库 + numpy + pydantic（工程既有依赖）。无网络调用。

## 2. 输入 Schema（prediction_input.v1）

```json
{
  "schema_version": "prediction_input.v1",
  "match": {
    "home_team": "Arsenal",
    "away_team": "Chelsea",
    "league": "E0",
    "kickoff_utc": "2026-09-20T14:00:00+00:00"
  },
  "odds": {
    "context": "preclosing",
    "source": "football-data.co.uk style feed",
    "retrieved_at": "2026-09-19T10:00:00+00:00",
    "books": {
      "B365": {"H": 2.10, "D": 3.50, "A": 3.60, ">2.5": 1.90, "<2.5": 1.90},
      "VC":   {"H": 2.05, "D": 3.40, "A": 3.55}
    }
  },
  "external_signals": [
    {
      "source": "understat",
      "namespace": "forward",
      "dq_status": "time_safe",
      "retrieved_at": "2026-09-18T20:30:00+00:00",
      "generated_at": null,
      "published_at": null,
      "payload_digest": "sha256:..."
    }
  ]
}
```

字段规则：
- `match.*` 全部必填；`kickoff_utc` 必须 ISO8601 含时区。
- `odds.context` 只允许 `preclosing`；`closing` → 整体 REJECTED（硬门禁）。
- `odds.books`：键=庄家代码；FTR 腿 `H/D/A`，OU25 腿 `>2.5/<2.5`。数值必须有限且 > 1.0。
- `external_signals` 可选数组；`namespace` ∈ {`forward`, `dq_validation`, `historical_retro`, `unknown`}。
- 禁止出现任何标签类字段（`fthg`/`ftag`/`ftr`/`label`/`score` 等）或 C-suffix 赔率键（`B365CH` 等）→ REJECTED。

## 3. 处理管线（顺序固定）

1. **结构校验**（pydantic）：schema 违规 → 输出 `REJECTED`（附违规清单）。
2. **泄漏守卫**：
   - 检出标签字段 → REJECTED；
   - 检出 C-suffix 键 → 该键剔除并记录；若 context==closing → REJECTED。
3. **时间安全门**：
   - `odds.retrieved_at` 缺失 → time_safe=UNKNOWN → 命中结果降 CONDITIONAL；
   - `retrieved_at >= kickoff_utc` → REJECTED（赛后赔率不可作赛前输入）。
4. **冻结指纹检查**（当可定位冻结文件时）：sha256 ≠ 钉扎值 → 全输出 STOP。
5. **市场基线计算**（复用 phase4a 算法，逐字同源，等价性由测试钉死）：
   - FTR：收集各庄家 `(H,D,A)`，缺任一腿的庄家剔除；`n_books>=2` → **M4**（均值→inverse→Shin）；
     `n_books==1` → 回退 **M2**（单庄 Shin）；回退记录于 `fallback_chain`，状态降 CONDITIONAL。
   - OU25：`B365` 对齐全 → **O2**（B365+Shin）；否则 `n_books>=2` → 回退 **O4**（multi-book 均值+Shin）；
     否则单庄 → 单庄 Shin（CONDITIONAL）；无 → INSUFFICIENT_DATA。
   - 任一赔率 ≤1.0 / 非有限 → 该庄家剔除；全部剔除 → INSUFFICIENT_DATA。
   - Shin 求解退化（overround≤1）→ z=0 归一化回退（与 4A 实现一致），记录 `shin_z=0`。
6. **外部信号门**（只产生状态，永不修改概率）：
   - 逐条：`namespace==forward` 且 `dq_status==time_safe` 且 `retrieved_at < kickoff_utc` 且三时间戳齐全 → 候选（AVAILABLE_NOT_VALIDATED）；
   - `namespace in {dq_validation, historical_retro}` 或 `dq_status != time_safe` → REJECTED（该条）；
   - `generated_at`/`published_at` 缺失 → 该条 UNKNOWN（绝不推断）；
   - 汇总状态：无信号→NOT_AVAILABLE；有候选→AVAILABLE_NOT_VALIDATED；
     `TIME_SAFE_VALIDATED` 仅当来源在已验证信号注册表 `validated_signal_registry.json`（当前不存在）中 → 现阶段代码不可达；
   - `signals_used_in_prediction` 恒为 false。
7. **不确定性**（描述性，非模型后验）：FTR 熵（bits）、跨庄隐含概率最大离散度、shin z；等级规则写入输出 notes。
8. **置信度**：HIGH=两市场均 VALID 且 ≥4 庄家且 time_safe；LOW=任一 CONDITIONAL/缺失/高离散；否则 MEDIUM。置信度不是"预测正确率"。

## 4. 输出 Schema（prediction_output.v1）

见 `PREDICTION_MATRIX.md` 维度 D。核心字段：

```json
{
  "schema_version": "prediction_output.v1",
  "model_version": "football_prediction 0.1.0 (market M4/O2, shin solver pinned to phase4a run_phase4a.py)",
  "prediction_utc": "…",
  "match": {"home_team": "…", "away_team": "…", "league": "E0", "kickoff_utc": "…"},
  "ftr": {
    "status": "VALID",
    "probabilities": {"home": 0.4478, "draw": 0.2621, "away": 0.2901},
    "method": {"method_id": "M4", "norm": "shin", "input": "multi-book", "n_books": 2,
               "shin_z": 0.0342, "books_used": ["B365", "VC"], "fallback_chain": []},
    "evidence_level": "Evidence",
    "evidence_refs": ["phase3b", "phase4a"]
  },
  "ou25": {"status": "CONDITIONAL", "probabilities": {"over": 0.53, "under": 0.47}, "method": {"method_id": "O2", …}},
  "market_data": {"context": "preclosing", "source": "…", "retrieved_at": "…",
                  "missing_fields": ["VC >2.5"], "overround_ftr": 1.0431, "book_dispersion_max": 0.011},
  "external_signals": {"overall_status": "NOT_AVAILABLE", "signals_used_in_prediction": false, "signals": []},
  "data_quality": {"time_safe_status": "TIME_SAFE", "completeness": "PARTIAL", "leakage_guards": {"closing_input_rejected": false, "label_field_detected": false, "csuffix_keys_dropped": 0}},
  "uncertainty": {"ftr_entropy_bits": 1.5472, "grade": "MEDIUM", "notes": ["…"]},
  "confidence": {"grade": "MEDIUM", "reasons": ["ou25 fallback"]},
  "frozen_dataset_provenance": {"referenced_sha256": "8f885fbc…", "verified": true},
  "forbidden_use": "research prediction only; no betting / ROI / EV / stake / profit claims"
}
```

不变式（实现必须保证，负例测试逐条覆盖）：
- P1 概率仅来自 Shin/归一化去抽水，永远和为 1（±1e-9）；无输入→null。
- P2 无赔率绝不输出概率（无随机、无默认值、无历史均值填充）。
- P3 信号不改概率。
- P4 每次输出带 `prediction_utc`、`model_version`、方法参数、庄家清单、缺失字段。
- P5 回退必记录且降级。
- P6 检出泄漏/指纹漂移 → STOP 且概率=null。

## 5. 测试计划

单元测试（正常路径）：
- T1 Shin 求解器 vs 手算样例（三结果/两结果，overround>1）。
- T2 与 phase4a `run_phase4a.py` 的 `shin_probs/method_ftr/method_ou25` 在 ≥200 组随机赔率上逐位等价（钉死"复用而非重写"）。
- T3 M4 多庄合成样例：概率和=1、z>0。
- T4 O2 B365 样例。
- T5 完整端到端 `predict_match`：VALID、schema 完整、time_safe。

负例测试（每条必须落到指定状态）：
- N1 无赔率 → INSUFFICIENT_DATA，概率=null。
- N2 context=closing → REJECTED。
- N3 注入 `B365CH` 键 → 剔除+记录（不参与计算）。
- N4 注入 label 字段 → REJECTED。
- N5 `retrieved_at >= kickoff_utc` → REJECTED。
- N6 赔率 ≤1.0 / NaN → 剔除该庄家；全剔除 → INSUFFICIENT_DATA。
- N7 retro namespace 信号 → 该条 REJECTED，overall 不为 TIME_SAFE_VALIDATED。
- N8 信号缺 `generated_at` → 该条 UNKNOWN，不推断（值保持 null）。
- N9 单庄 FTR → M2 回退 + CONDITIONAL。
- N10 冻结指纹漂移（临时伪造指纹文件）→ STOP。

## 6. 明确不做

不训练/不加载任何 ML 模型；不调用网络；不修改冻结数据；不做校准层（5.1-A 已关闭）；不使用 CLOSING；不做 Agent/Ensemble；不做 betting/ROI/EV/stake；不把沙盘引擎 `football_simulation` 的输出当市场层预测。

## 7. 验收标准

全部测试通过；CLI 端到端演示一次 VALID 输出 + 一次 INSUFFICIENT_DATA 输出；registry 追加文件记录本模块及其测试（遵循各 phase append 惯例）。
