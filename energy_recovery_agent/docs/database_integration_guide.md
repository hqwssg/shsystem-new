# 数据库接入与平台集成说明

## 1. 已实现范围

数据库接入已覆盖“输入版本发布、任务创建、工作进程领取、算法执行、结果事务写回、状态查询、结果导出”完整链路。算法计算仍在内存中执行，不在时间步循环中查询数据库，因而不会改变现有算法数值逻辑。

固定约定如下：

| 项目 | 值 |
| --- | --- |
| 数据库 | PostgreSQL 16及以上，数据库名 `carbon_emissions` |
| Schema | `energy_recovery` |
| 业务表前缀 | `simulation_` |
| 部署连接 | `SIMULATION_DEPLOYMENT_DATABASE_URL`或升级用`SIMULATION_MIGRATOR_DATABASE_URL` |
| 平台连接 | `SIMULATION_PLATFORM_DATABASE_URL` |
| 工作进程连接 | `SIMULATION_DATABASE_URL` |
| 只读查询连接 | `SIMULATION_READONLY_DATABASE_URL` |
| 健康检查连接 | `SIMULATION_ACCEPTANCE_DATABASE_URL` |
| 数据版本 | 发布后不可覆盖，修改时创建新版本 |
| 任务创建 | 项目内 `idempotency_key` 唯一；同键同内容返回原任务，同键异内容拒绝 |
| 工作进程所有权 | 300秒租约令牌，默认每60秒心跳续期 |
| 结果写入 | 单事务批量写入，成功任务按结果哈希幂等 |

## 2. 平台与算法的职责边界

平台负责界面校验、用户权限、输入文件上传、数据版本发布、任务创建和结果展示。算法工作进程只接受数据库中已发布的不可变版本与参数白名单，不接受任意命令行文本。

每份源文件同时保存为 `simulation_dataset_file` 的原始字节和 SHA-256；车站、区段、车型、储能、供电臂等常用字段另投影到关系表，供界面检索。任务执行时从数据库还原冻结快照，再调用原文件适配器。这种方式同时保证平台数据库是唯一输入渠道，以及现有文件模式可继续做回归对比。

每份算法输出均完整保存到 `simulation_result_artifact`；界面常用内容另写入结果关系表。关系投影失败时整个结果事务回滚，不会出现状态成功但结果只写入一半的情况。

## 3. 部署顺序

1. 安装 PostgreSQL 16或更高兼容版本及 Python 数据库依赖：`python -m pip install -r requirements-database.txt`。
2. 使用管理库连接创建业务数据库：`python -m database.cli bootstrap --admin-url <管理库DSN>`。
3. 通过密钥系统设置部署连接，执行`python -m database.cli --database-url $env:SIMULATION_DEPLOYMENT_DATABASE_URL migrate`。
4. 执行`python -m database.cli --database-url $env:SIMULATION_DEPLOYMENT_DATABASE_URL apply-security`，统一转移对象所有权并应用最小权限。
5. 由数据库管理员创建四个不同的LOGIN账号，分别且只能继承迁移、平台、worker或只读角色；使用`tools/verify_target_database_access.py`实测账号边界。

连接串含凭据，不得写入仓库。生产环境必须启用 TLS，并分别配置平台账号、工作进程账号和只读账号。

## 4. 导入当前数据

当前数据仍含工程占位参数，因此版本状态必须使用 `planning_placeholder`：

```powershell
python -m database.cli import-data `
  --source-dir data/real_shuohuang `
  --project-code shuohuang-energy `
  --project-name 朔黄铁路再生能量回收与调度 `
  --route-name 朔黄铁路 `
  --version-code planning-2026-09 `
  --data-status planning_placeholder `
  --source-note 正式车辆与电气参数到位前的规划版本 `
  --extra-file platform/running_diagram.xlsx=data_templates/running_diagram_template.xlsx
```

`--extra-file` 左侧是算法快照内的逻辑路径，运行图任务参数必须引用该逻辑路径，不能引用服务器任意文件。

## 5. 创建和执行任务

任务参数样例位于 `database/examples/`。创建任务示例：

```powershell
python -m database.cli create-run `
  --project-code shuohuang-energy `
  --version-code planning-2026-09 `
  --run-type timetable_audit `
  --parameters-file database/examples/timetable_audit_parameters.json `
  --requested-by platform-user `
  --idempotency-key request-20260908-0001
```

滚动任务使用 `database/examples/rolling_rescheduling_parameters.json`。其中 `storage_devices` 数组保存每台设备的SOC、在线/停运状态和当前可用充放电功率；数组随任务参数写入数据库并进入请求摘要。显式提供时必须覆盖当前储能预设的全部设备，不能同时提交旧的汇总SOC。设备级字段和输出见 `rolling_storage_device_runtime_state.md`。

历史扰动回放任务使用 `database/examples/historical_disturbance_replay_parameters.json`。先将符合 `data_templates/historical_disturbance_replay_template.json` 的文件随数据版本发布到 `simulation_dataset_file`，再通过 `disturbance_history_relative_path` 引用快照内逻辑路径。该参数与任务级 `storage_devices` 互斥；回放来源摘要和逐轮结果分别输出为 `disturbance_replay_manifest.json` 与 `disturbance_replay_cycles.csv`。完整合同见 `historical_disturbance_replay_interface.md`。

联合参数稳健性任务使用 `run_type=joint_parameter_robustness`。先把符合 `data_templates/joint_parameter_ranges_template.json` 的区间合同随版本发布，再用必填参数 `parameter_ranges_relative_path` 引用快照内逻辑路径。详细输出和结论边界见 `joint_parameter_robustness.md`。

设备额定容量、额定充放电功率、充放电效率、初始SOC和SOC上下限不属于任务参数，而来自数据版本的 `simulation_storage_device`。工作进程会把这些数据库行生成 `storage_devices.json` 并纳入不可变输入快照；算法存在该文件时以逐设备数据为准。详见 `database_storage_device_algorithm_binding.md`。

工作进程每次安全领取一个任务；并行工作进程通过 `FOR UPDATE SKIP LOCKED` 避免重复领取：

```powershell
python -m database.cli worker-once --lease-seconds 300 --heartbeat-interval-seconds 60 --resource-profile standard
```

平台以 `run_id` 查询状态。状态为 `succeeded` 后再查询结果表；状态为 `failed` 时显示 `error_message`，不要展示旧结果。

需要核对状态迁移时使用 `python -m database.cli status --run-id <运行ID> --include-events`。

工作进程领取时生成一次性 `lease_token`。输入冻结、心跳、结果提交和失败写回都必须同时匹配 `run_id + worker_id + lease_token` 且租约未过期。平台取消任务或过期任务被重新领取后，旧工作进程的写回会被拒绝。默认执行器在等待算法子进程期间每60秒续租；续租失败会终止子进程。工作进程还按 `quick/standard/fine` 档位执行总墙钟预算，搜索型任务超时后最多执行一次有限降级，成功结果附带 `solver_resource_report.json`。超时不得解释为模型不可行，完整规则见 `solver_resource_budget_and_degradation.md`。

过期任务通常在下一次领取前自动回收，也可主动执行：

```powershell
python -m database.cli recover-expired --max-attempts 3
python -m database.cli cancel-run --run-id <运行ID> --reason operator_cancelled
```

## 6. 界面展示建议

总览页读取 `simulation_timetable_audit_summary`、`simulation_result_kpi` 和 `simulation_optimization_decision`。其中 `action=keep_baseline` 表示现有运行图无需替换，`action=optimize` 才表示应展示选中候选，`action=no_feasible_solution` 表示本次搜索没有得到可采用方案。

滚动优化返回 `commit_status=withheld_infeasible` 时必须映射为 `action=no_feasible_solution`：候选详情和冲突仍可展示，但平台不得下发新增发车，也不得将其写入下一轮锁定历史。`committed_infeasible_experiment_only` 只允许离线实验任务使用，生产任务应拒绝该配置。完整语义见 `rolling_infeasible_commit_gate.md`。

平台可提交 `run_type=rolling_rescheduling`，并从 `simulation_rolling_control_event` 按轮次读取安全状态时间线。`waiting_for_observation` 表示本轮已扣留并等待新状态；`manual_intervention_required` 表示连续失败达到阈值，必须由调度员处置；`recovered_automatically` 和 `recovered_after_observation` 表示已恢复且可执行门禁通过后的运行图。详见 `rolling_safety_degradation_state_machine.md`。

运行图页读取 `simulation_timetable_running_arc`；能量图读取 `simulation_energy_time_slice`；供电臂结算页读取 `simulation_power_arm_settlement`。候选列表读取 `simulation_optimization_candidate`，场景稳健性读取 `simulation_scenario_result`，问题和建议分别读取 `simulation_audit_issue`、`simulation_optimization_suggestion`。

报告、图片和原始 CSV/JSON 从 `simulation_result_artifact` 下载。详情表用于交互查询，工件用于审计、复核和复现实验，两者不能互相替代。

## 7. 数据一致性和重试

- 版本内容以 SHA-256 标识；已发布版本禁止同名覆盖。
- 平台重试创建任务时必须复用项目内 `idempotency_key`；同键请求的版本、任务类型、参数、请求人或代码版本变化都会因请求 SHA-256 不一致而拒绝。
- 每次运行冻结输入清单并写入 `simulation_run_input_snapshot`；重复冻结仅接受相同版本和输入 SHA-256，不再静默忽略冲突。
- 活跃任务由租约令牌排他拥有；心跳只能延长尚未过期的当前租约，不能复活旧租约。
- 租约过期后任务重新进入 `pending`；累计达到默认3次尝试后进入 `failed`，避免无限重跑。
- 每次状态转换与结果写入在同一事务追加 `simulation_run_state_event`，`state_version` 单调递增且运行内唯一。
- 成功结果由结果清单 SHA-256 标识；完全相同的重试返回幂等成功，不同结果不能覆盖已成功任务。
- 结果表、结果工件和任务成功状态在同一事务提交。
- 工作进程异常写入 `failed` 和诊断信息，不删除输入快照。
- 文件路径在还原前执行规范化和目录边界检查，防止路径穿越。

## 8. 交付文件

| 文件 | 用途 |
| --- | --- |
| `database/migrations/001_core.sql` 至 `007_joint_parameter_robustness.sql` | 可执行的版本化 DDL |
| `database/io_mapping.json` | 输入、参数和输出的机器可读映射 |
| `database/platform_api_contract.json` | 平台操作、状态机和查询边界 |
| `database/platform_query_examples.sql` | 平台按任务查询状态、KPI、明细、事件和工件元数据的只读SQL |
| `database/delivery_package_manifest.json` | 交付版本、任务类型、运行边界和入口的机器可读清单 |
| `database/security_roles.sql` | 可选的生产最小权限角色脚本 |
| `database/postgres.py` | 导入、领取、快照和事务写回仓储 |
| `database/worker.py` | 数据库任务适配器及参数白名单 |
| `database/cli.py` | 部署、导入、运行和导出命令入口 |
| `tools/deploy_database.ps1` | 安装依赖、建库、迁移、授权和健康检查的一键入口 |
| `tools/run_database_worker_loop.py` | 可由服务管理器托管的常驻任务工作进程 |
| `tools/database_healthcheck.py` | PostgreSQL版本、迁移、表、角色和权限矩阵健康检查 |
| `tools/verify_target_database_access.py` | 四类目标登录账号、TLS、角色继承和实际拒绝行为核验 |
| `tools/run_database_five_run_acceptance.py` | 由平台、worker、只读三个独立账号执行五类任务闭环 |
| `tools/build_database_delivery_package.ps1` | 按显式白名单生成数据库交付目录、校验和与压缩包 |
| `tools/verify_database_delivery_package.py` | 同时核验交付目录和解压后压缩包内容 |

当前机器已在仅监听`127.0.0.1:55432`的PostgreSQL 16测试实例完成迁移、四账号权限、分角色五类任务、并发领取、幂等、租约和事务回滚验收。最新五任务报告位于`outputs/database_postgres_segregated_e2e_acceptance_v4/DATABASE_FIVE_RUN_E2E_REPORT.md`，账号探测位于`outputs/target_platform_predeployment/local_four_account_access.json`。该本地实例使用信任认证且未启用TLS，只能证明部署前代码链路；上线前仍须在目标平台复验TLS、真实账号、备份恢复和实际并发负载。

面向外部部署与平台联调的完整说明见 `database_delivery_package_guide.md`，职责和页面语义见 `database_platform_integration_handoff.md`，人工签字项见 `database_platform_integration_checklist.md`。构建后的交付包保留项目内相对目录，可覆盖到同版本完整算法项目中使用；它不是脱离算法主项目的独立可执行程序。
