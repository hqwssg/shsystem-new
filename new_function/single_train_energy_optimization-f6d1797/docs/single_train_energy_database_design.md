# 单列车能量回收与节能策略数据库设计说明

> 版本：2026-11-08。本文只描述 `single_train_energy` 模块在当前数据库导出中的表投影，
> 不覆盖重空协同调度、储能站规划或碳排放模块的其他表。字段注释以
> `database/single_train_energy_module_comments.json` 为机器可读源，MySQL 注释补丁见
> `database/single_train_energy_module_comments.sql`。

## 1. 设计范围

本模块保存单列车再生制动闭环和节能速度曲线策略的版本化输入、运行任务、结果指标和结果工件。
算法仍在内存中完成动力学和控制计算，数据库负责输入冻结、幂等运行、结果留档和前端查询。

本次从 `bb.sql` 识别并补充 13 张表。未修改同库其他表。

| 分组 | 表 | 作用 |
| --- | --- | --- |
| 项目与版本 | `energy_project`、`energy_project_version` | 项目身份和不可变输入版本 |
| 输入留档 | `energy_dataset_file`、`energy_route_segment`、`energy_train_type_parameter`、`energy_scenario` | 源文件、线路区段、列车动力学和运行场景 |
| 运行管理 | `energy_run`、`energy_run_parameter`、`energy_run_input_snapshot`、`energy_run_log`、`energy_run_state_event` | 创建运行、冻结输入、记录日志和状态迁移 |
| 结果留档 | `energy_result_kpi`、`energy_result_artifact` | 前端汇总指标和完整文件产物 |

## 2. 关系与生命周期

```text
energy_project
  └─ energy_project_version
       ├─ energy_dataset_file / energy_route_segment / energy_train_type_parameter / energy_scenario
       └─ energy_run
            ├─ energy_run_parameter
            ├─ energy_run_input_snapshot
            ├─ energy_run_log / energy_run_state_event
            ├─ energy_result_kpi
            └─ energy_result_artifact
```

运行流程固定为以下顺序。

1. 创建或读取项目和已发布版本。
2. 以版本号和 SHA-256 固化参数文件、共享线路数据和场景。
3. 按幂等键创建 `energy_run`，把请求写入 `energy_run_parameter`。
4. 开始运行前写入 `energy_run_input_snapshot`，之后不得修改本次输入。
5. 算法完成后在同一事务写入 KPI、结果工件并将运行状态置为 `succeeded`。
6. 失败时写 `energy_run_log` 和 `energy_run_state_event`，运行状态置为 `failed`。

## 3. 通用口径

| 项目 | 约定 |
| --- | --- |
| 数据库 | MySQL 8.0，当前导出数据库为 `carbon_emissions` |
| 命名 | 表和字段保持现有英文 snake_case，中文只放 COMMENT 和说明层 |
| 时间 | 数据库绝对时间使用服务器时间，算法相对时间字段使用字段后缀 `_s` |
| 单位 | 距离 km，质量 t，力 kN，功率 kW，能量 kWh，速度 km/h，坡度 ‰ |
| 数据状态 | `official`、`real`、`derived`、`assumed`、`placeholder` 等状态必须原样展示 |
| 版本 | 已发布版本不可覆盖，改变输入必须创建新版本 |
| 结果 | `energy_result_kpi` 适合列表和卡片，完整台账、时序 CSV 和报告放 `energy_result_artifact` |

## 4. 表与字段说明

### 4.1 `energy_project`

单列车能量回收与节能策略项目主表

| 字段 | 中文说明 |
| --- | --- |
| `project_id` | 项目主键 |
| `project_code` | 项目业务编码，项目内唯一 |
| `project_name` | 项目名称 |
| `route_name` | 适用线路名称 |
| `timezone` | 项目业务时区 |
| `status` | 项目状态，例如 active 表示启用 |
| `created_at` | 创建时间 |
| `updated_at` | 最后更新时间 |

### 4.2 `energy_project_version`

单列车算法输入与配置版本表

| 字段 | 中文说明 |
| --- | --- |
| `version_id` | 版本主键 |
| `project_id` | 所属项目 ID |
| `version_code` | 版本业务编码，项目内唯一 |
| `version_name` | 版本名称 |
| `data_status` | 版本数据状态，例如 official、real、derived、assumed、placeholder |
| `lifecycle_status` | 版本生命周期状态，例如 draft、published、retired |
| `effective_from` | 版本生效时间 |
| `effective_to` | 版本失效时间 |
| `source_note` | 版本来源与适用范围说明 |
| `content_sha256` | 版本输入内容 SHA-256 校验值 |
| `published_at` | 发布时间 |
| `created_at` | 创建时间 |
| `updated_at` | 最后更新时间 |

### 4.3 `energy_dataset_file`

单列车算法输入源文件原始字节留档表

| 字段 | 中文说明 |
| --- | --- |
| `dataset_file_id` | 源文件留档主键 |
| `version_id` | 所属输入版本 ID |
| `relative_path` | 版本内逻辑相对路径，不允许路径穿越 |
| `media_type` | 文件媒体类型 |
| `content` | 源文件原始字节内容 |
| `content_size_bytes` | 原始文件字节数 |
| `content_sha256` | 原始文件 SHA-256 校验值 |
| `created_at` | 留档时间 |

### 4.4 `energy_route_segment`

单列车节能策略线路区段参数表

| 字段 | 中文说明 |
| --- | --- |
| `segment_id` | 线路区段主键 |
| `version_id` | 所属输入版本 ID |
| `segment_code` | 线路区段业务编码 |
| `start_km` | 区段起点公里标，单位 km |
| `end_km` | 区段终点公里标，单位 km |
| `gradient_permille` | 区段坡度，单位 ‰，上坡为正 |
| `curve_radius_m` | 区段曲线半径，单位 m，直线可为空 |
| `speed_limit_kmh` | 区段限速，单位 km/h |
| `terrain` | 区段地形或线路环境标签 |
| `direction` | 适用方向，例如 forward、reverse、both |
| `source_note` | 区段数据来源与核对说明 |
| `created_at` | 创建时间 |

### 4.5 `energy_train_type_parameter`

单列车节能与再生制动列车动力学参数表

| 字段 | 中文说明 |
| --- | --- |
| `train_type_id` | 列车类型参数主键 |
| `version_id` | 所属输入版本 ID |
| `train_type_code` | 列车类型业务编码 |
| `train_type` | 列车类型，例如 Heavy 或 Empty |
| `mass_t` | 列车整备总质量，单位 t |
| `mass_min_t` | 质量扰动下限，单位 t |
| `mass_max_t` | 质量扰动上限，单位 t |
| `length_km` | 列车长度，单位 km |
| `rotational_mass_factor` | 回转质量系数 |
| `max_traction_kn` | 最大牵引力，单位 kN |
| `max_brake_kn` | 最大制动力，单位 kN |
| `max_power_kw` | 最大牵引或再生功率，单位 kW |
| `davis_a` | Davis 阻力公式常数项 |
| `davis_b` | Davis 阻力公式速度一次项系数 |
| `davis_c` | Davis 阻力公式速度二次项系数 |
| `traction_curve_json` | 牵引力随速度变化曲线 JSON |
| `brake_curve_json` | 制动力随速度变化曲线 JSON |
| `regen_power_limit_kw` | 再生功率上限，单位 kW |
| `regen_efficiency` | 再生链效率 |
| `direction` | 参数适用方向 |
| `longitudinal_segments` | 纵向动力学区段数量 |
| `extra_parameters_json` | 未单独列化的扩展参数 JSON |
| `data_status` | 参数数据状态 |
| `source_note` | 参数来源与假设说明 |
| `created_at` | 创建时间 |

### 4.6 `energy_scenario`

单列车再生制动与节能策略运行场景表

| 字段 | 中文说明 |
| --- | --- |
| `scenario_id` | 场景主键 |
| `version_id` | 所属输入版本 ID |
| `scenario_code` | 场景业务编码 |
| `allow_direct_use` | 是否允许再生电能直接利用，1 是 0 否 |
| `allow_storage` | 是否允许储能参与，1 是 0 否 |
| `settlement_step_s` | 能量结算步长，单位 s |
| `parameters_json` | 场景参数 JSON |
| `created_at` | 创建时间 |

### 4.7 `energy_run`

单列车算法运行任务主表

| 字段 | 中文说明 |
| --- | --- |
| `run_id` | 运行任务主键 |
| `project_id` | 所属项目 ID |
| `version_id` | 本次运行使用的输入版本 ID |
| `timetable_id` | 关联运行图 ID，单列车场景可为空 |
| `scenario_id` | 关联运行场景 ID |
| `run_type` | 运行类型，例如 single_train_regen 或 eco_driving |
| `status` | 运行状态，例如 pending、running、succeeded、failed |
| `requested_by` | 提交运行的用户或系统标识 |
| `code_version` | 执行代码版本或 Git 提交标识 |
| `random_seed` | 随机数种子 |
| `input_sha256` | 运行输入快照 SHA-256 校验值 |
| `result_sha256` | 运行结果 SHA-256 校验值 |
| `error_count` | 错误数量 |
| `warning_count` | 警告数量 |
| `error_message` | 失败或异常摘要 |
| `queued_at` | 进入队列时间 |
| `started_at` | 开始执行时间 |
| `finished_at` | 完成时间 |
| `worker_id` | 执行工作进程标识 |
| `created_at` | 创建时间 |
| `updated_at` | 最后更新时间 |
| `idempotency_key` | 幂等键，同一请求只能对应一个运行 |
| `request_sha256` | 运行请求内容 SHA-256 校验值 |
| `attempt_count` | 执行尝试次数 |
| `lease_token` | 运行租约令牌 |
| `lease_expires_at` | 运行租约过期时间 |
| `heartbeat_at` | 工作进程最后心跳时间 |
| `state_version` | 状态版本号，单调递增 |

### 4.8 `energy_run_parameter`

单列车算法运行请求参数表

| 字段 | 中文说明 |
| --- | --- |
| `run_id` | 运行任务 ID，同时作为主键 |
| `parameters_json` | 本次运行请求参数 JSON |
| `parameter_schema_version` | 运行参数结构版本 |
| `created_at` | 创建时间 |
| `updated_at` | 最后更新时间 |

### 4.9 `energy_run_input_snapshot`

单列车算法运行输入冻结快照表

| 字段 | 中文说明 |
| --- | --- |
| `snapshot_id` | 输入快照主键 |
| `run_id` | 运行任务 ID |
| `version_id` | 输入版本 ID |
| `captured_at` | 快照采集时间 |
| `input_sha256` | 冻结输入 SHA-256 校验值 |
| `manifest_json` | 输入文件清单与状态 JSON |
| `frozen` | 是否已冻结，1 是 0 否 |
| `created_at` | 创建时间 |

### 4.10 `energy_run_log`

单列车算法运行日志表

| 字段 | 中文说明 |
| --- | --- |
| `log_id` | 日志主键 |
| `run_id` | 运行任务 ID |
| `level` | 日志级别，例如 info、warning、error |
| `event_code` | 日志事件编码 |
| `message` | 日志消息 |
| `details_json` | 日志附加详情 JSON |
| `occurred_at` | 日志发生时间 |

### 4.11 `energy_run_state_event`

单列车算法运行状态变更审计表

| 字段 | 中文说明 |
| --- | --- |
| `event_id` | 状态事件主键 |
| `run_id` | 运行任务 ID |
| `state_version` | 状态版本号 |
| `from_status` | 变更前状态 |
| `to_status` | 变更后状态 |
| `worker_id` | 执行工作进程标识 |
| `lease_token` | 状态变更时使用的租约令牌 |
| `reason` | 状态变更原因 |
| `details_json` | 状态变更详情 JSON |
| `occurred_at` | 状态变更时间 |

### 4.12 `energy_result_kpi`

单列车算法运行结果指标表

| 字段 | 中文说明 |
| --- | --- |
| `result_kpi_id` | 结果指标主键 |
| `run_id` | 运行任务 ID |
| `candidate_id` | 候选方案 ID，单列车主算法可为空 |
| `case_name` | 结果场景或工况名称 |
| `feasible` | 结果是否满足约束，1 是 0 否 |
| `total_gen_kwh` | 场景产生的总能量，单位 kWh |
| `total_con_kwh` | 场景消耗的总能量，单位 kWh |
| `accepted_by_power_arm_kwh` | 供电臂或储能侧接纳的能量，单位 kWh |
| `recovered_energy_kwh` | 算法统计的回收能量，单位 kWh |
| `recovery_rate` | 回收率 |
| `direct_used_kwh` | 直接利用的再生能量，单位 kWh |
| `battery_charge_kwh` | 储能充入能量，单位 kWh |
| `battery_discharge_kwh` | 储能放出能量，单位 kWh |
| `wasted_kwh` | 弃用或未被接纳的能量，单位 kWh |
| `grid_kwh` | 与电网交换的能量，单位 kWh |
| `effective_regen_loss_kwh` | 再生链有效损失能量，单位 kWh |
| `final_soc_kwh` | 运行结束时储能能量或 SOC 对应能量，单位 kWh |
| `constraint_violation` | 约束违反量 |
| `resource_conflict_count` | 资源冲突数量 |
| `total_cost` | 结果总成本或综合目标值 |
| `metrics_json` | 完整指标 JSON，保留未列化指标 |
| `created_at` | 创建时间 |

### 4.13 `energy_result_artifact`

单列车算法结果产物留档表

| 字段 | 中文说明 |
| --- | --- |
| `artifact_id` | 结果产物主键 |
| `run_id` | 运行任务 ID |
| `relative_path` | 产物在运行结果中的逻辑相对路径 |
| `artifact_type` | 产物类型，例如 summary、timeseries、report |
| `media_type` | 产物媒体类型 |
| `content` | 产物原始字节内容 |
| `content_size_bytes` | 产物字节数 |
| `content_sha256` | 产物 SHA-256 校验值 |
| `created_at` | 留档时间 |

## 5. 前端使用约束

- 列表页优先查询 `energy_run`、`energy_result_kpi`，先展示 `status` 和 `feasible`，再展示能量指标。
- 详情页通过 `run_id` 关联 `energy_run_input_snapshot`、`energy_run_log`、`energy_run_state_event` 和 `energy_result_artifact`。
- 下载结果时校验 `content_sha256`，不能只依赖文件名。
- `placeholder`、`assumed` 和 `derived` 参数必须显示数据状态标签，不能在界面上标为现场实测。
- 单列车再生量优先使用算法结果 JSON 中的 `storage_net_of_grid_import_energy_kWh`。`storage_energy_kWh` 和 `captured_energy_kWh` 是端口吸收口径，可能包含电网回吸。
- 运行任务的 `idempotency_key` 与 `request_sha256` 不得由前端静默重写。相同幂等键但请求摘要不同应显示冲突。

## 6. SQL 交付物

| 文件 | 用途 |
| --- | --- |
| `bb.sql` | 当前本地数据库导出的单列车模块表已补充中文注释。该整库导出不纳入 Git |
| `database/single_train_energy_module_comments.sql` | 只修改 13 张模块表的 MySQL 注释补丁，可在目标库执行 |
| `database/single_train_energy_module_comments.json` | 表/字段中文注释机器可读清单 |
| `regenerative_braking/database/migrations/001_core.sql`、`002_runs.sql` | 算法原生 PostgreSQL 迁移，供代码模式部署 |

补丁只包含 `ALTER TABLE ... COMMENT` 和 `MODIFY COLUMN ... COMMENT`，不会插入或更新业务数据。执行前应在目标库完成备份，并由数据库管理员核对表结构版本。
