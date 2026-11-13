# 数据库部署与联调交付包说明

## 1. 交付目标

本交付包供数据库管理员、平台后端开发和算法部署人员共同使用，覆盖 PostgreSQL 建库、迁移、最小权限、输入版本发布、五类任务提交、常驻工作进程、平台查询和验收。界面开发不在本包范围内，但界面所需字段和查询来源已经给出。

交付包必须与同一版本的完整算法项目配套使用。数据库工作进程会调用项目根目录中的 `run_project.py` 和算法模块，不能只复制数据库目录后独立运行算法。

## 2. 固定合同

统一冻结清单为 `database/interface_contract_freeze.json`，详细边界见 `docs/interface_contract_freeze.md`。交付或升级前必须运行 `python tools/verify_interface_contract_freeze.py`，确认冻结文件哈希、任务参数白名单、DDL枚举和示例请求一致。

| 项目 | 约定 |
| --- | --- |
| PostgreSQL | 16及以上 |
| 数据库 | `carbon_emissions` |
| Schema | `energy_recovery` |
| 表前缀 | `simulation_` |
| 当前迁移 | `001-007` |
| 输入模式 | 已发布不可变数据版本 + 任务参数 + 冻结运行快照 |
| 输出模式 | 关系结果和完整工件在同一事务提交 |
| 五类任务 | `dispatch`、`timetable_audit`、`timetable_optimization`、`rolling_rescheduling`、`joint_parameter_robustness` |

## 3. 部署

前提是目标机已安装 Python 3.9及以上和 PostgreSQL 16及以上，部署账号具有建库、建 schema、建角色和授权权限。真实连接串只能通过环境变量或平台密钥系统提供。

首次部署：

```powershell
powershell -ExecutionPolicy Bypass -File tools/deploy_database.ps1 `
  -AdminUrl $env:POSTGRES_ADMIN_URL `
  -DeploymentDatabaseUrl $env:SIMULATION_DEPLOYMENT_DATABASE_URL `
  -HealthcheckDatabaseUrl $env:SIMULATION_ACCEPTANCE_DATABASE_URL
```

数据库已经存在时：

```powershell
powershell -ExecutionPolicy Bypass -File tools/deploy_database.ps1 `
  -DeploymentDatabaseUrl $env:SIMULATION_MIGRATOR_DATABASE_URL `
  -HealthcheckDatabaseUrl $env:SIMULATION_ACCEPTANCE_DATABASE_URL `
  -SkipBootstrap
```

脚本依次安装 Python 数据库依赖、创建数据库、执行未应用迁移、建立四类 NOLOGIN 权限角色并运行健康检查。重复执行不会重复应用已经登记的迁移。

生产登录账号由数据库管理员创建，并分别且只能继承 `simulation_migrator`、`simulation_platform`、`simulation_worker` 或 `simulation_readonly`。交付 SQL 不创建带密码的 LOGIN 账号。部署连接、平台连接、worker连接、只读连接不得共用账号；环境变量模板见`database/database.env.example`。

## 4. 数据版本发布

规划数据必须标记 `planning_placeholder`；正式数据通过门禁后才允许使用 `official` 或 `derived_from_official`。运行图、历史扰动和联合参数区间应作为版本文件一并发布：

```powershell
python -m database.cli import-data `
  --source-dir data/real_shuohuang `
  --project-code shuohuang-energy `
  --project-name 朔黄铁路再生能量回收与调度 `
  --route-name 朔黄铁路 `
  --version-code planning-2026-09 `
  --data-status planning_placeholder `
  --extra-file platform/running_diagram.xlsx=data_templates/running_diagram_template.xlsx `
  --extra-file platform/historical_disturbance_replay.json=data_templates/historical_disturbance_replay_template.json `
  --extra-file platform/joint_parameter_ranges.json=data_templates/joint_parameter_ranges_template.json
```

发布版本不可覆盖。任何文件变化都必须使用新 `version_code`，平台应保存返回的版本 ID 和内容 SHA-256。

## 5. 五类任务联调

参数样例位于 `database/examples/`，总清单位于 `five_run_acceptance_manifest.json`。每次请求必须提供项目内唯一 `idempotency_key`；网络重试时复用相同键和完全相同内容。

```powershell
python -m database.cli create-run `
  --project-code shuohuang-energy `
  --version-code planning-2026-09 `
  --run-type dispatch `
  --parameters-file database/examples/dispatch_parameters.json `
  --requested-by platform-integration `
  --idempotency-key acceptance-dispatch-001
```

其余四类任务只需替换 `run-type`、参数文件和幂等键。平台不得提交白名单之外的算法命令行参数。

开发环境可单次领取：

```powershell
python -m database.cli worker-once --lease-seconds 300 --heartbeat-interval-seconds 60
```

常驻进程入口：

```powershell
python tools/run_database_worker_loop.py
```

生产环境应由 Windows 服务、systemd、容器编排或平台进程管理器托管该入口，并配置自动重启、标准输出采集和单实例唯一 `SIMULATION_WORKER_ID`。优雅停止会在当前子任务结束后退出；执行中的算法由租约和心跳保护。

## 6. 平台查询

机器合同为 `database/platform_api_contract.json` 和 `database/io_mapping.json`。可直接复核的只读 SQL 位于 `database/platform_query_examples.sql`。

平台必须遵守以下状态语义：

- `pending/validating/running`：只显示当前状态，不读取旧任务结果；
- `succeeded`：允许读取摘要、明细和工件；
- `failed`：显示 `error_message`，不得回退展示同项目旧结果；
- `cancelled`：停止轮询结果；
- `withheld_infeasible`：滚动任务不得下发新增发车计划。

工件内容应通过鉴权下载接口返回，列表页只查询文件名、媒体类型、大小和 SHA-256，不应批量读取 `bytea content`。

## 7. 健康检查与验收

```powershell
python tools/database_healthcheck.py `
  --database-url $env:SIMULATION_ACCEPTANCE_DATABASE_URL `
  --require-tls `
  --output outputs/database_healthcheck.json

python tools/verify_target_database_access.py `
  --output outputs/target_database_access.json

python tools/run_database_five_run_acceptance.py `
  --project-code shuohuang-energy `
  --version-code planning-2026-09-platform-acceptance `
  --output-dir outputs/database_five_run_acceptance

$env:SIMULATION_TEST_DATABASE_URL='<名称以_test结尾的专用测试库连接串>'
python tools/platform_task_stress_fault.py `
  --output-dir outputs/platform_task_stress_fault_current
```

健康检查验证版本、数据库名、UTF-8、TLS、主库状态、迁移校验和、关键表、对象所有者、四类角色和权限矩阵。账号核验器验证四个登录账号非超级用户、只继承指定角色，并实际探测DDL和只读写入拒绝。分角色五任务执行器固定由平台账号发布版本和创建任务、worker账号执行、只读账号审计，要求每类均存在成功任务、连续状态事件、非空输入/结果SHA-256和对应结构化结果或核心工件。压力工具验证并发创建、幂等突发、领取、心跳、取消、崩溃回收、旧令牌拒绝、最大重试和结果事务回滚；它强制测试库名称以`_test`结尾。

本地PostgreSQL 16已完成四账号权限探测、分角色五类任务闭环，以及120/500/1000任务三档测试；最高档使用32个并发worker，六类故障全部通过。本地实例仅监听回环地址且未启用TLS，这些结果只是部署前基线，目标平台仍必须按实际证书、账号、连接池和负载重跑。

完整人工检查项见 `database_platform_integration_checklist.md`。

## 8. 安全、备份和回退

- 生产连接强制 `sslmode=require` 或更严格模式，凭据不得进入命令历史、日志、Git或压缩包；
- 迁移前执行数据库备份并记录恢复点；当前交付不提供破坏性 down migration；
- 迁移失败时停止平台写入，保留错误和迁移记录，按数据库备份恢复，不手工删除业务表；
- `simulation_dataset_file` 和 `simulation_result_artifact` 可能增长较快，应监控数据库大小、WAL、备份窗口和工件保留策略；
- 正式上线前必须在目标环境完成 TLS、登录账号、备份恢复、并发负载和故障演练，本地验收不能替代这些项目。
