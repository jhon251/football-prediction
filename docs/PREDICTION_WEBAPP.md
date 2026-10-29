# PREDICTION WEBAPP — 一键赛前预测（赛程 → 赔率 → 预测器 → 比分矩阵）

> 目标交互：打开页面 → 点一场未开赛的比赛 → 点「采集赔率并预测」→ 看到胜平负概率、
> 大小球 2.5 与比分概率矩阵。全程真实 ESPN 数据，零手工输入。

## 启动

```bash
# 在仓库根目录
python -m football_prediction.cli serve --port 8600
# 浏览器打开 http://127.0.0.1:8600
```

纯标准库实现（无新增依赖）。`football_prediction.predictor` 冻结管线**未被修改**，
本层只做输入装配与输出增强。

## 组件

| 组件 | 文件 | 说明 |
|---|---|---|
| 比分概率矩阵 | `src/football_prediction/score_matrix.py` | Dixon-Coles 双变量泊松拟合 + raking（迭代比例拟合），聚合量精确复现去水概率（≤1e-9），单元格分布是市场概率的重参数化，**非独立验证信号** |
| 爆冷风险预警 | `src/football_prediction/upset_risk.py` | 等级/方向/severity 阈值逐条对齐系统 A `UpsetRiskAgent`（相对赛前概率定义），叠加比分矩阵的极端冷门比分与市场自不确定度驱动；`evidence_level: Derived` |
| ESPN 赔率适配器 | `src/football_prediction/odds_feed.py` | scoreboard 拉取未开赛赛程（六大联赛未来 3 天）与单场赛前赔率；美式赔率→小数；写读 `data/lineups/prospective/fixtures_feed.json`（字段超集，兼容 DATA-006 supervisor） |
| the-odds-api 多庄家源 | `src/football_prediction/odds_api.py` | 同一场比赛聚合 bet365/Pinnacle/William Hill 等多家并合并进 `books`；按开球时间（±15 分钟）+ 队名模糊匹配 ESPN 事件；无 key 时自动跳过（回退仅 ESPN） |
| 伤停情报源 | `src/football_prediction/injuries_feed.py` | API-Football（api-sports.io v3）伤停/停赛名单；按 P3 不变量只进 `external_signals`（状态封顶 AVAILABLE_NOT_VALIDATED，永不改概率），前端以「伤停情报卡」展示；无 key 自动跳过，接口失败软降级 |
| 编排服务 | `src/football_prediction/service.py` | 状态前置检查 → 装配 `prediction_input.v1` → 调 `predict_match` → 挂载矩阵；每次预测追加审计行到 `backtest_output/webapp_predict_log.jsonl` |
| Web 服务器 | `src/football_prediction/webapp.py` | `GET /`（单页 UI）、`GET /api/health`（含 the-odds-api 配置状态）、`GET /api/fixtures[?refresh=1]`、`POST /api/predict {event_id, force}` |
| 前端单页 | `src/football_prediction/static/index.html` | 赛程列表 / 一键预测 / 状态徽章 / 胜平负概率条 / 大小球条 / 比分矩阵热力图（6×6 + 尾部）/ Top 比分 / 期望进球 / BTTS / 溯源面板 |

## HTTP API

```bash
curl http://127.0.0.1:8600/api/fixtures?refresh=1          # 刷新并返回未开赛赛程
curl -X POST http://127.0.0.1:8600/api/predict \
     -H "Content-Type: application/json" \
     -d '{"event_id":"401878768","force":true}'            # 现场采集赔率并预测
```

错误码：`EVENT_NOT_FOUND`（404）、`MATCH_NOT_PRE`（409，已开赛——时间安全门只放行赛前赔率）、
`NO_ODDS`（409，ESPN 无完整 1X2）、`ESPN_UNREACHABLE`（502）。

## 诚实性设计（为什么很多场次显示 CONDITIONAL）

* **单庄家来源**：ESPN 目前只挂 DraftKings 一家 → 1X2 走 M2（单书 Shin）回退链，
  状态为 CONDITIONAL 而非 VALID；这是回退被如实记录，不是错误。
* **大小球线策略**：预测器的 O/U 模型固定定义在 2.5 线上。ESPN 该场总进球线非 2.5
  （如 3.5）时**跳过** O/U 腿（`ou25` 置 INSUFFICIENT_DATA），绝不把别的线伪装成 2.5。
* **比分矩阵地位**：矩阵聚合量 = 去水概率（P1 不变量的延伸），但单元格分布属于
  Dixon-Coles 重参数化，`evidence_level: Derived`，不等同于已验证的 M4/O2。
* **时间安全**：`retrieved_at` = 抓取时刻，预测前重查比赛状态，开赛后一律拒绝。

## the-odds-api 多庄家源（把置信从 LOW 提到 MEDIUM/HIGH）

冻结预测器的置信分级评的是**市场输入质量**：≥2 家含 B365 且无回退 → MEDIUM，
≥4 家含 B365 → HIGH。ESPN 只有 DraftKings 一家，所以不接第二家永远是 LOW。
本层已内置 the-odds-api 适配器，配好 key 即自动合并，冻结预测器无需任何改动。

**申请 API key（免费）：**

1. 打开 <https://the-odds-api.com>，点 Sign Up（邮箱注册，无需信用卡）；
2. 免费计划 = 每月 500 credits；
3. 登录后进入 Dashboard → API Keys，复制默认 key（32 位十六进制串）。

**配置（二选一）：**

```bash
# 方式 A：环境变量
export ODDS_API_KEY="你的key"        # Windows PowerShell: $env:ODDS_API_KEY="你的key"

# 方式 B：key 文件（已 gitignore，不会入库）
echo 你的key > config/odds_api.key
```

重启服务后：页面顶栏显示「多庄家源 the-odds-api：已接入」，
`curl http://127.0.0.1:8600/api/health` 返回 `"odds_api": {"configured": true}`。

**配额成本：** 一次预测 = 1 请求 × 2 区域（eu,uk）× 2 市场（h2h,totals）= **4 credits**，
500/月 ≈ 125 次点击。预测结果页会显示剩余配额（`TOA 配额余 N`）。
配额耗尽或 key 无效时自动回退仅 ESPN，页面显示失败原因，服务不中断。

## 测试

```bash
python -m pytest tests/prediction -q
```

* `test_score_matrix.py`：聚合复现目标、分布合法、极端盘口、Top 比分排序。
* `test_service_assembly.py`：美式赔率换算、2.5/非 2.5 线提取、装配输入全链路预测、
  开赛后时间安全拒绝、服务层 404/409 分支（全部 canned 数据，无网络）。
* `test_odds_api.py`：the-odds-api 书目提取、队名模糊匹配（含 Brighton &/and、
  Internazionale/Inter Milan 案例）、开球时间容差、合并后置信升 MEDIUM/HIGH、
  无 key 回退、API 错误软失败（全部 canned 数据，无网络、不耗配额）。
* `test_upset_risk.py`：等级阈值与系统 A `UpsetRiskAgent` 逐例对齐（含小概率
  封顶压级、开放对局）、矩阵极端冷门比分归属与排序、市场分歧/熵/单书驱动、
  服务层挂载。
* `test_injuries_feed.py`：fdo 赛事匹配（昵称/时间容差/错配拒绝）、伤停提取与
  主客归属、match/competition 双路由、P3 断言（有无伤停概率逐位相等）、
  key 无效软降级。

伤停源 key（API-Football，免费 100 请求/天，每次预测 2 请求）：

```bash
# 注册：https://api-sports.io/registration （免费档；key 在 dashboard）
export API_FOOTBALL_KEY="你的key"     # 或
echo 你的key > config/api_football.key
```

注：football-data.org 曾作为伤停候选源，实测其 v4 在任何档位都没有
injuries 端点（两条可能路由均 404），已弃用；其 key（config/football_data.key）
保留但当前未被使用。
