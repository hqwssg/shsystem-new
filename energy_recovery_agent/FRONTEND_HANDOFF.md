# 重空协同算法阶段交付 · 前端联调说明

包标识为 `frontend_backend_code_20261108_stage_v2`，构建时间为 `2026-11-08T21:35:00Z`。源码版本、接口冻结版本和数据等级以 [包清单](FRONTEND_HANDOFF_MANIFEST.json) 为准。

本包用于运行重空协同算法、对接数据库接口和展示仿真结果。数据包括从朔黄资料提取的线路、站点、供电臂边界和区间统计，也包括模型参数、工程假设与规划占位。现场运行、正式节能率和储能投资结论需要补齐正式数据并重新验收。

## 前端如何展示结果

| 字段或状态 | 页面处理 |
| --- | --- |
| `ready_for_integration` | 当前包可供联调时启用任务与结果页 |
| `ready_for_conclusions=false` | 页面标明“阶段仿真结果”，关闭正式结论和现场下发入口 |
| `action=no_feasible_solution` | 显示“本轮未推荐可采用方案”，保留诊断，优化量留空 |
| `reason=baseline_infeasible` | 显示基线没有满足硬约束，提示查看始发间隔、股道和区段占用 |
| `headway_preflight` | 展示可调整范围、阻断车次及间隔缺口，单位为秒 |
| `improvement` 为空 | 显示“未评价”，保留已算出的基线值 |
| `planning_sensitivity` | 储能结果标为“规划敏感性分析”，保留搜索完整性和数据条件提示 |

能力和输入可信度可从以下登记读取。[能力登记表](docs/algorithm_stability_registry.json) · [输入完整性](docs/input_completeness_registry.json) · [假设台账](data/real_shuohuang/assumptions.json)

## 启动和核验

```bash
python -m pip install --require-hashes -r requirements-lock.txt
python run_project.py --help
python run_project.py smoke --only verify_database_contract verify_interface_contract_freeze verify_energy_settlement_correctness
```

软件运行环境为 Python 3.11 至 3.12。需要重建或复核源数据时，请在完整工作区使用共享数据管理器。包内提供运行视图，原始工作簿、原始电表记录和正式数据接收区由项目方另行管理。全量 `validate-data` 会检查这些原件的存在性。

解压后可按 [SHA-256 校验清单](CHECKSUMS.sha256) 核对文件。算法命令生成的结果位于其指定的输出目录。JSON 和 CSV 保留稳定机器键名，中文报告和参数说明可直接供页面使用。

## 接入文件

| 文件 | 用途 |
| --- | --- |
| [本次变更](FRONTEND_CHANGELOG_20261108_STAGE.md) | 页面需要调整的结果判断和数据提示 |
| [机器可读变更](FRONTEND_CONTRACT_CHANGES_20261108_STAGE.json) | 新字段、语义变化与兼容范围 |
| [接口冻结](database/interface_contract_freeze.json) | 六类任务、平台操作与状态约束 |
| [输入输出映射](database/io_mapping.json) | 前端参数与数据库投影对应关系 |
| [查询示例](database/platform_query_examples.sql) | 任务与结果查询 |
| [部署说明](README.md) | 运行、数据库配置和命令 |

滚动实验任务按影子验证口径使用。需到正式环境重新验收权限、正式设备映射、实测初始储能电量和完整运行约束后，才能评估生产接入。
