# DIAG-008：Understat 滚动 xG/xGA 增量价值验证（EXP-DIAG-EPL-008）

> 唯一目标：判断**严格时间安全**的 Understat rolling xG/xGA 是否能在**冻结 Elo** 基础上提供可统计区分的增量预测价值。
> 纪律：探针框架**逐字复用 DIAG-005**（`exp_diag_005_run.py`），未为 xG 重新设计；未修改生产模型/config/35 条规则；未调 Elo 参数；未搜索窗口（window=10 冻结）；未调整权重；未训练模型；未接入其他数据源；未进入 V1.3。

## 0. 执行摘要与答案

**问题：严格时间安全的 Understat rolling xG/xGA 是否具备 Elo 外增量？**

**答案：INSUFFICIENT EVIDENCE —— 所有 xG 特征均未通过预注册成功标准，未发现其具备 Elo 外预测增量。**
（不使用『接近显著』『有潜力』等替代措辞——正式判定即 INSUFFICIENT EVIDENCE。）

- 冻结 Elo 基线 Brier：0.6310（380 场）。
- xG 数据：DATA-002 冻结 `rolling_2025.csv`，data_version `ae9e746b4654d8ad…`（fingerprint ae9e746b4654d8ad），window=10，严格 datetime<kickoff，未重新抓取。

## 1. 方法（与 DIAG-005 完全可比）

- 测试集边界：全部 380 场（与 DIAG-005 相同）。
- walk-forward：探针展开窗口只用严格先前比赛（与 DIAG-005 相同）。
- 探针：`(Elo 概率动态三分位 × 特征动态中位数)` 条件频率 + 回退链（<20 → elo 分层 <20 → 原 Elo；最小历史 30）。**逐字复用 DIAG-005 代码。**
- **执行披露（非框架变更）**：置换循环使用同一数学的**纯向量化实现**（`exp_diag_008_fast.py`）；每个源在写入结果前都通过与逐字实现的**逐场一致性校验**（探针概率 max|Δ|=0.00，fallback 标记完全一致）——框架数学零改动，仅执行方式不同。
- 置换 rng 注记：每个源使用独立的 `rng(default_rng(20240101))` 实例（同一预注册 seed 的相同 iid 均匀流；与 DIAG-005 共享游标方式仅抽取顺序不同，均为无偏蒙特卡洛估计）。
- 置换：seed 20240101，10000 次（与 DIAG-005 相同）；主置换 = 源特征值重排，次级 = 结果向量重排（透明参考）。
- 统计口径：三类 Brier、LogLoss、Murphy 信息项 C（与 DIAG-005 相同）。

## 2. 单源结果（全部预注册判据）

| xG 特征 | ΔBrier | ΔLogLoss | Murphy C | 置换 p（源值） | 置换 p（结果向量，次级） | split-half（前/后） | 一致 | 有效样本 | fallback | 判定 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| xG for 差（主队滚动 xG for − 客队滚动 xG for） | +0.0082 | +0.0117 | -0.0029 | 0.0891 | 0.8413 | +0.0049/+0.0115 | 否 | 370 | 16% | INSUFFICIENT EVIDENCE |
| xG against 差（主队滚动 xG against − 客队滚动 xG against） | +0.0029 | +0.0042 | -0.0034 | 0.0040 | 0.6714 | +0.0004/+0.0053 | 否 | 370 | 16% | INSUFFICIENT EVIDENCE |
| xG 净值差（主队 xG净 − 客队 xG净） | +0.0050 | +0.0073 | -0.0029 | 0.0161 | 0.7745 | +0.0001/+0.0099 | 否 | 370 | 16% | INSUFFICIENT EVIDENCE |
| home/away 分离：主队滚动 xG for | +0.0161 | +0.0262 | -0.0012 | 0.8460 | 0.9721 | +0.0022/+0.0300 | 否 | 370 | 16% | INSUFFICIENT EVIDENCE |
| home/away 分离：客队滚动 xG for | +0.0111 | +0.0194 | -0.0010 | 0.3020 | 0.8981 | +0.0082/+0.0139 | 否 | 370 | 16% | INSUFFICIENT EVIDENCE |

**成功标准（五项全部满足才算 EVIDENCE）**：
- ΔBrier ≤ -0.003；
- 置换 p < 0.0071（源值置换）；
- split-half 一致（前/后 190 场 ΔBrier 均 < 0）；
- 有效样本 ≥ 100；
- fallback 率 ≤ 30%。

注：`xg_against_diff` 的置换 p=0.0040 < 0.0071（该特征与结果的关联在置换检验下可检测），但其 ΔBrier=+0.0029 > 0（探针仍**差于** Elo）且 split-half 不一致 → 按预注册五项标准仍判 INSUFFICIENT EVIDENCE。（如实记录，不用『接近显著』措辞替代正式判定。）

## 3. 组合探针（预注册规则）

- 无单源通过成功标准 → 按预注册规则**不执行**组合探针（不允许为寻找增益而事后组合特征）。

## 4. 结论

**PRIMARY（证据强）：**
- （无 —— 无任一 xG 特征达到预注册成功标准）
**SECONDARY（证据中等）：**
- 各特征 ΔBrier / Murphy C 与置换 p 见第 2 节表（如实记录，不加工）
**UNCONFIRMED（证据不足，不猜测）：**
- xG/xGA 的 Elo 外增量：INSUFFICIENT EVIDENCE（与 DIAG-005 射门统计类代理无增量的结果方向一致；无证据 ≠ 证明无用）

**NEXT（仅设计，不执行；不修改生产模型、不进入 V1.3）：**
1. DIAG-009（设计待定）：跨赛季复测 xG 探针（2024-25 冻结数据隔离保留，可作为第二赛季样本）。
2. DATA-003（设计待定）：首发/伤停数据接入（DIAG-006/007 优先级），届时按 DIAG-007 协议做 D7.2/D7.3 验证。

## 5. 可复现

- 冻结基线：EXP-REAL-EPL-BASE-001（`7c52c6bdfa37`）及 EXP-DIAG-EPL-001~005 哈希清单在 `backtest_output/diag_008_xg_validation/baseline_manifest_*.json`。
- 产物：`probes.json`（逐场探针概率+特征+回退标记）、`stats.json`、`experiments.jsonl`（EXP-DIAG-EPL-008）。
- xG 数据 fingerprint：DATA-002 `ae9e746b4654d8ad`（full `ae9e746b4654d8addb582bb3acf445ccbf575c72c31ede3f4f93be39f25cfa27`）。
- 探针框架代码与 DIAG-005 逐字一致（未重新设计）。
