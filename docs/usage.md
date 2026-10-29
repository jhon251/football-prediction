# 使用指南

## 环境

* Python 3.10+；依赖仅 `pydantic>=2`、`numpy`（已内置所需的一切）。
* 测试用 `unittest`（标准库）运行：`python -m unittest discover -s tests`。
* 生成 mock 数据：`python scripts/generate_fixtures.py`（合成数据，非真实统计）。

## CLI

```bash
football analyze MATCH_ID [--runs 10000] [--seed 12345]
                        [--counterfactuals] [--convergence]
                        [--output report.json] [--explanation explain.txt]
                        [--config my.json]
football simulate MATCH_ID --runs 10000 [--seed 12345]
football scenarios MATCH_ID [--runs 10000]
football trace MATCH_ID
football post-match MATCH_ID [--runs 2000]
football demo
football api [--host 127.0.0.1] [--port 8000]
```

内置 match id：`match-demo-001`（待赛：Arsenal vs Chelsea，合成数据）、`match-demo-000`（已完赛，用于学习/评估演示）。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/matches/analyze` | `{"match_id", "runs"?, "seed"?}` → 完整报告 |
| GET | `/matches/{match_id}` | 缓存的最新报告 |
| POST | `/matches/{match_id}/simulate` | 仅模拟统计（1X2、期望进球） |
| GET | `/matches/{match_id}/scenarios` | 剧本分布 + 长尾 |
| GET | `/matches/{match_id}/probabilities` | 1X2/比分/O-U/BTTS/半全场 |
| GET | `/matches/{match_id}/risks` | 爆冷 + 风险 + 置信度 + 失效条件 |
| GET | `/matches/{match_id}/trace` | Reasoning Trace |
| GET | `/health` | 健康检查 |

```bash
curl -X POST http://127.0.0.1:8000/matches/analyze \
     -H "Content-Type: application/json" \
     -d '{"match_id": "match-demo-001", "runs": 5000, "seed": 42}'
```

## 配置（`config/default.json`）

```json
{
  "simulation": {"default_runs": 10000, "seed": 12345,
                 "convergence_threshold": 0.005,
                 "convergence_runs": [1000, 5000, 10000, 50000]},
  "director": {"freeze": true, "run_convergence": false,
               "run_counterfactuals": false, "counterfactual_runs": 2000},
  "learning": {"store_path": "learning_store.json"},
  "api": {"host": "127.0.0.1", "port": 8000}
}
```

用户配置（JSON，或安装 PyYAML 后支持 YAML）通过 `--config` 合并覆盖默认值。模拟次数支持 1,000 / 5,000 / 10,000 / 50,000 / 100,000 任意配置。

## 输出契约

最终报告 `MatchPredictionReport` 与需求 §44 一一对应（`match / result_probability / score_probability / goals_probability / btts / half_time_full_time / scenarios / upset_risk / risk / confidence / failure_conditions / explanation / counterfactuals / convergence / trace / data_quality`）。所有概率内部 0~1，展示层转百分比。

## 可复现性

相同 WorldState + 相同 seed ⇒ 完全相同的比赛与统计。跨机器、跨进程稳定（RNG 用 PCG64 + 稳定字符串哈希派生，不依赖 PYTHONHASHSEED）。调试：`football trace MATCH_ID` 展示每一步 Agent 决策与证据。

## 学习与评估

```bash
football post-match match-demo-000
```

产出：8 项准确度（结果/比分/剧本/战术/事件/O-U/BTTS/半全场/爆冷检测）、期望进球误差、预测成败记录、Candidate Rule 提案；全部写入 `learning_store.json`。核心知识规则**不会**被自动修改。
