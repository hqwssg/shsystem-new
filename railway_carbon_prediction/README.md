# 铁路碳排放趋势预测模块

朔黄铁路机辆/肃宁/原平三个分公司的碳排放趋势预测模块，按《技术实现方案——孤立森林—GRA—滑动窗口 LSTM》实现，并针对真实数据做了口径还原、小样本降级与平台集成改造。

## 1. 核心结论

- **可行，但不能直接用报表 `co2_t` 训练**：2019—2025 年电力排放因子发生 5 次切换（0.8843→0.5703→0.5568→0.5366→0.5306），2025 年肃宁/原平供热面积折算系数由 0.9224 改为 0.380/0.334。直接训练会把“核算口径变化”学成“减排趋势”。
- 系统同时保存 **报表口径** 与 **可比口径**：建模用可比口径（固定 2025 年电力因子、0.9224 GJ/m² 供热系数），对外展示/报送用报表口径。
- 2025 年内燃机车批量退役是已知结构断点，柴油由“台数×单机强度”独立预测，不进入 LSTM 目标。
- 2025 年留出测试：机辆 SW-LSTM（W=12）MASE=1.09、MAPE=9.75%；肃宁 Ridge（W=6）MASE=0.48、MAPE=10.56%；原平 GBM（W=6）MASE=0.64、MAPE=8.15%。
- 2026 年 BAU 预测：机辆 91.39 万 tCO2e（同比 -2.89%）、肃宁 2.54 万 t（报表 2.24 万，-2.31%）、原平 3.00 万 t（报表 1.80 万，+7.86%）。

> 详细评审见 [docs/01_方案可行性评审与修订.md](docs/01_方案可行性评审与修订.md)，异常算法设计 V2 见 [docs/09_异常值识别算法设计V2.md](docs/09_异常值识别算法设计V2.md)，评测见 [docs/05_模型评测与预测报告.md](docs/05_模型评测与预测报告.md)。
> 
> 算法设计 Word 文档：[docs/铁路碳排放趋势预测算法设计_V1.1.docx](docs/铁路碳排放趋势预测算法设计_V1.1.docx)。
> 
> 数据库字段说明：[docs/10_数据库字段详细说明.md](docs/10_数据库字段详细说明.md)。
> 
> 因子版本迁移：[sql/003_factor_snapshot.sql](sql/003_factor_snapshot.sql)；历史快照回填：`python scripts/backfill_factor_snapshots.py`。
> 
> 非机辆牵引电力修正：[sql/004_fix_non_jlg_traction.sql](sql/004_fix_non_jlg_traction.sql)。
> 
> 入库锁与覆盖审计：[sql/005_ingest_guard_audit.sql](sql/005_ingest_guard_audit.sql)。
> 
> 平台模块（Vue3 + Spring Boot）：[railway_carbon_platform/README.md](railway_carbon_platform/README.md)。

## 2. 目录结构

```
railway_carbon_prediction/
├─ config/                  # 配置示例
├─ data/raw/                # 三个分公司原始 Excel（已复制）
├─ data/external/           # 气温、煤价、煤产量等外部因子
├─ sql/                     # 建表 + 种子数据
├─ src/carbon_prediction/   # 业务代码
│  ├─ data.py               # 口径还原、缺失推算、排放计算
│  ├─ features.py           # 特征面板
│  ├─ gra.py                # 灰色关联
│  ├─ anomaly.py            # 异常检测 V1（历史对照）
│  ├─ anomaly_v2.py         # 异常检测 V2：双通道森林/断点/日历/多变量/关注表
│  ├─ dataset.py            # 滑动窗口/标准化
│  ├─ models.py             # SW-LSTM + 基线
│  ├─ pipeline.py           # 导入/训练/预测/接入/复核编排
│  ├─ api.py                # FastAPI 接口
│  └─ reporting.py          # 图表与 Excel
├─ scripts/                 # 命令行入口
├─ docs/                    # 设计、接口、评测、运维文档
└─ artifacts/               # 模型、图表、Excel
```

## 3. 快速开始

### 3.1 安装依赖

```bash
pip install -r requirements.txt
```

### 3.2 配置

复制 `.env.example` 为 `.env`，按实际修改数据库与 API Key。默认连接：

```
127.0.0.1:3306 / root / 123456 / carbon_emissions
```

### 3.3 初始化数据库

```bash
python scripts/init_db.py
```

### 3.4 导入 2019—2025 历史数据

```bash
python scripts/import_history.py
```

### 3.5 异常筛查、训练、预测（一键）

```bash
python scripts/run_pipeline.py
```

或分步：

```bash
python scripts/anomaly_scan.py
python scripts/train_all.py --orgs JLG,SNF,YPF --as-of 2025-12
python scripts/forecast.py --horizon 12 --as-of 2025-12
python scripts/make_report.py
```

### 3.6 启动 API

```bash
python scripts/run_api.py
# http://127.0.0.1:8000/docs
```

请求头：`X-API-Key: dev-key`（生产环境务必修改）。

## 4. 主要接口

| 方法   | 路径                                            | 用途             |
| ---- | --------------------------------------------- | -------------- |
| GET  | `/health`                                     | 健康检查（无需鉴权）     |
| GET  | `/api/v1/prediction/orgs`                     | 组织列表           |
| GET  | `/api/v1/prediction/series`                   | 月度排放宽表         |
| POST | `/api/v1/prediction/ingest/monthly`           | 月度增量接入（幂等）     |
| GET  | `/api/v1/prediction/anomalies`                | 待复核异常          |
| GET  | `/api/v1/prediction/anomalies/watch`          | 关注级监控（不进复核队列）  |
| GET  | `/api/v1/prediction/anomalies/quality-report` | 月度数据质量汇总       |
| POST | `/api/v1/prediction/anomalies/{id}/review`    | 人工复核           |
| POST | `/api/v1/prediction/train`                    | 异步训练（全量/微调/自动） |
| GET  | `/api/v1/prediction/jobs/{job_id}`            | 训练任务状态         |
| POST | `/api/v1/prediction/forecast`                 | 未来一年预测并写库      |
| GET  | `/api/v1/prediction/forecast`                 | 查询预测结果         |
| GET  | `/api/v1/prediction/gra`                      | 灰色关联结果         |
| GET  | `/api/v1/prediction/models`                   | 模型注册表          |
| POST | `/api/v1/prediction/policy/factors`           | 推送政策/外部因子      |

完整字段与示例见 [docs/04_接口文档.md](docs/04_接口文档.md)。

## 5. 数据库

- 库：`carbon_emissions`（与大平台同库）
- 所有本模块表统一前缀：`prediction_`
- 核心表：`prediction_org`、`prediction_activity_monthly`、`prediction_emission_monthly`、`prediction_anomaly`、`prediction_model`、`prediction_forecast`、`prediction_policy_factor`、`prediction_gra_result`
- 宽表视图：`prediction_v_carbon_monthly`

详见 [docs/03_数据库设计.md](docs/03_数据库设计.md)。

## 6. 口径与数据处理约定

| 事项              | 处理                             |
| --------------- | ------------------------------ |
| 电力因子年度切换        | 建模用固定 0.5306；报表用当年因子           |
| 2025 供热系数调整     | 肃宁/原平按 0.9224 还原物理热力；报表保留原值    |
| 2019—2020 机辆周转量 | 按 2021—2025 同月“周转量/电量”中位数推算    |
| 2019—2023 牵引电力  | 按 2024—2025 同月辅助用电占比中位数拆分，合计不变 |
| 2019—2021 肃宁天然气 | 年总量按 HDD 权重分摊到 12 个月           |
| 2024 机辆天然气      | 按用户说明剔除，用 2023 年同月值补全          |
| 2025 柴油退役       | 独立柴油模块按台数强度预测，不进入 LSTM         |

## 7. 可复现性

- 全局随机种子：`20260928`
- 数据版本：`prediction_dataset_version`
- 模型工件：`artifacts/models/{model_id}/`（权重 + scaler + 元数据）
- 训练指标：`artifacts/reports/metrics_{org}.json`
- 评测口径：2019—2024 训练、2024 验证选参、2025 留出测试、2019—2025 重训后预测 2026
