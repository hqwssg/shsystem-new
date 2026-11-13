# 模拟程序数据库表结构

## 1. 适用范围

本文是平台开发使用的数据字典，物理实现以 `database/migrations/001_core.sql` 至 `004_outputs.sql` 为准。数据库名固定为 `carbon_emissions`，Schema 为 `energy_recovery`，所有业务表均使用 `simulation_` 前缀。

平台通过数据库保存版本化输入、创建算法任务并展示结果。算法工作进程从数据库读取不可变文件快照，在内存中计算，再将结构化结果和原始结果工件写回数据库。

## 2. 公共口径

| 项目 | 约定 |
| --- | --- |
| 业务实体主键 | PostgreSQL `uuid` |
| 大批量明细主键 | `bigint GENERATED ALWAYS AS IDENTITY` |
| 绝对时间 | `timestamp with time zone`，数据库按 UTC 保存 |
| 算法相对时间 | 非负整数秒，字段后缀 `_s` |
| 距离/质量/力/功率/能量 | km、t、kN、kW、kWh |
| 数据状态 | `official`、`derived_from_official`、`planning_placeholder`、`synthetic` |

当前 `data/real_shuohuang` 仍包含工程占位参数，导入时整体状态必须是 `planning_placeholder`，不能标为正式现场数据。

## 3. 版本与原始输入

| 表 | 关键字段 | 用途 |
| --- | --- | --- |
| `simulation_project` | `project_id uuid PK`、`project_code`、`project_name`、`route_name`、`status`、创建/更新时间 | 项目主表，项目编码唯一 |
| `simulation_project_version` | `version_id uuid PK`、`project_id FK`、`version_code`、`version_name`、`data_status`、`lifecycle_status`、有效期、`source_note`、`content_sha256`、`published_at` | 一次不可变数据发布，同项目版本编码唯一 |
| `simulation_dataset_file` | `dataset_file_id`、`version_id`、`relative_path`、`media_type`、`content bytea`、字节数、SHA-256、创建时间 | 无损保存算法实际读取的全部源文件 |

`simulation_dataset_file` 是算法输入快照的完整事实来源；关系表是界面检索和校验用投影。文件路径禁止绝对路径与 `..` 路径穿越。

## 4. 结构化输入表

### 4.1 线路、车站与资源

| 表 | 主键和关键字段 | 用途 |
| --- | --- | --- |
| `simulation_station` | `station_id`、`version_id`、站点编码/名称、`position_km`、类型、股道/咽喉容量、终点标志、来源备注 | 车站和线路控制点 |
| `simulation_route_segment` | `segment_id`、`version_id`、区段编码、起终公里、坡度、曲线半径、限速、地形、方向、来源备注 | 坡度、曲线与限速区段 |
| `simulation_signaling_block` | `signaling_block_id`、`version_id`、闭塞编码、起终公里、方向、容量、`release_margin_s`、数据状态 | 闭塞分区；正式数据未到时可为空 |
| `simulation_station_resource` | `station_resource_id`、`version_id`、`station_id`、股道/咽喉容量、站内/咽喉占用秒、`extra_rules_json` | 站场与技术作业规则 |

方向使用 `forward`、`reverse` 或 `both`。区段满足 `end_km > start_km >= 0`。

### 4.2 `simulation_train_type_parameter`

车辆和编组动力学参数。字段分为：标识 `train_type_id`、`version_id`、`train_type_code`、`train_type`；基础参数 `mass_t`、质量区间、`length_km`、`rotational_mass_factor`；能力参数 `max_traction_kn`、`max_brake_kn`、`max_power_kw`；阻力参数 `davis_a/b/c`；以及 `direction`、`longitudinal_segments`、`extra_parameters_json`、`data_status`、`source_note`。

尚未独立列化的曲线、效率等扩展字段保存在 `extra_parameters_json`，原始文件仍完整保留。

### 4.3 `simulation_storage_device`

关键字段：`storage_id`、`version_id`、`storage_code`、`label`、`capacity_kwh`、最大充放电功率、充放电效率、初始/最小/最大 SOC、起终公里、方向、可用标志、数据状态、来源备注。

SOC 满足 `0 <= min_soc_kwh <= initial_soc_kwh <= max_soc_kwh <= capacity_kwh`。

该表是平台算法运行时的储能静态参数权威来源。工作进程按 `version_id` 读取设备行，生成 `storage_devices.json` 并纳入不可变输入快照；重空调度、滚动调度和运行图评价均使用这些逐设备值。任务参数中的同名 `storage_devices` 数组只保存实时SOC、运行状态和临时功率上限，不保存或覆盖本表额定参数。

### 4.4 `simulation_power_arm`

关键字段：`power_arm_id`、`version_id`、`power_arm_code`、起终公里、方向、最大牵引供电/再生吸收/电网上网功率、`direct_use_allowed`、`needs_manual_review`、数据状态和来源备注。

当前主场景 `storage_no_direct` 下直用关闭；牵引负荷不会被同时刻再生能量直接抵扣，但可以由已有储能 SOC 放电供能。

### 4.5 运行图

| 表 | 关键字段 | 用途 |
| --- | --- | --- |
| `simulation_timetable` | `timetable_id`、`version_id`、运行图编码/名称、服务日期、时区、数据状态、来源备注 | 运行图头信息 |
| `simulation_timetable_train` | `timetable_train_id`、`timetable_id`、`train_type_id`、车次、方向、起终站、服务类型、是否评价 | 运行图内列车 |
| `simulation_timetable_stop` | `stop_id`、`timetable_train_id`、`seq`、`station_id`、到发相对秒、停站类型、股道、作业类型 | 列车逐站时刻 |

到发时间使用相对秒，跨日由数值自然表达；出发秒不得早于到达秒。

### 4.6 场景、运输任务与 OD

| 表 | 关键字段 | 用途 |
| --- | --- | --- |
| `simulation_energy_scenario` | `scenario_id`、`version_id`、场景编码/名称、直用/储能开关、结算步长、参数 JSON | 能量结算假设 |
| `simulation_transport_task` | `task_id`、`version_id`、任务编码/类型、起终站、需求列数、时间窗、优先级 | 重车/空车运输任务 |
| `simulation_od_demand` | `od_id`、`version_id`、起终站、列车类型、需求数、有效期、来源备注 | 起讫点运输需求 |

## 5. 任务与状态表

### 5.1 `simulation_run`

算法任务主表。关键字段：`run_id`、`project_id`、`version_id`、`timetable_id`、`scenario_id`、`run_type`、`status`、请求人/工作进程、代码版本、随机种子、输入/结果 SHA-256、`idempotency_key`、请求SHA-256、尝试次数、租约令牌/到期时间、心跳时间、状态版本、错误/警告数及排队/开始/结束时间。

`run_type` 为 `dispatch`、`timetable_audit`、`timetable_optimization` 或 `rolling_rescheduling`。状态为 `pending`、`validating`、`running`、`succeeded`、`failed` 或 `cancelled`。活跃状态必须具有租约；非活跃状态不得保留租约。

### 5.2 任务辅助表

| 表 | 关键字段 | 用途 |
| --- | --- | --- |
| `simulation_run_parameter` | `run_id PK/FK`、`parameters_json`、创建时间 | 界面提交的白名单参数；滚动任务的 `storage_devices` 保存逐设备SOC、可用状态和临时功率上限 |
| `simulation_run_input_snapshot` | `snapshot_id`、`run_id`、`version_id`、输入 SHA-256、`manifest_json`、创建时间 | 固化本次运行实际输入 |
| `simulation_run_log` | `log_id`、`run_id`、级别、事件编码、消息、详情 JSON、发生时间 | 运行诊断与审计 |
| `simulation_run_state_event` | `event_id`、`run_id`、状态版本、前后状态、工作进程、租约令牌、原因、详情JSON、发生时间 | 不可变状态迁移审计；运行内状态版本唯一 |

## 6. 结构化输出表

### 6.1 审查、运行弧与能量结算

| 表 | 关键字段 | 主要用途 |
| --- | --- | --- |
| `simulation_timetable_audit_summary` | `run_id`、`valid`、列车/运行弧/时间片/窗口/事件/问题/建议数量、基线再生/弃能/购电、摘要 JSON | 结果总览和审查摘要 |
| `simulation_timetable_running_arc` | 明细 ID、运行/候选 ID、源弧、列车、类型、方向、起终站/秒/公里、牵引/再生能量、供电臂、储能、详情 JSON | 绘制运行图并定位列车区段能量 |
| `simulation_energy_time_slice` | 明细 ID、运行/候选 ID、case、起止秒、供电臂、储能、牵引/再生/接纳/直用/充放电/弃能/购电、SOC、违反量、详情 JSON | 绘制能量时间线、核验守恒和 SOC |
| `simulation_power_arm_settlement` | 明细 ID、运行/候选 ID、供电臂、窗口起止秒、牵引/再生/接纳/充放电/弃能/购电、功率上限、违反量 | 按供电臂和窗口识别电气瓶颈 |

能量时间片是算法时间粒度的能量流明细；供电臂结算是按供电臂聚合后的电气结算。二者目的不同，不能只保留其中一张。

### 6.2 问题、建议与冲突

| 表 | 关键字段 | 说明 |
| --- | --- | --- |
| `simulation_audit_issue` | 问题/运行/候选 ID、类型、严重度、供电臂、起止秒、影响能量、原因、详情 JSON | 审查发现的问题 |
| `simulation_optimization_suggestion` | 建议/运行/源问题 ID、类型、目标列车、偏移秒、原因、状态 | 尚待候选验证的调整建议 |
| `simulation_resource_conflict` | 明细/运行/候选 ID、case/场景、冲突类型、严重度、资源、两列车、重叠时间、位置、消息、建议 | 股道、咽喉、闭塞等冲突 |

建议不等于可执行优化方案；只有可行候选经决策表选中后才可标为采用。

### 6.3 候选、场景与决策

| 表 | 关键字段 | 主要用途 |
| --- | --- | --- |
| `simulation_optimization_candidate` | 候选/运行 ID、源编码、候选集合、排名、可行/Pareto 标志、场景、三个目标、违反度、成本、购电、弃能、回收能量、终端 SOC、冲突数、参数/指标 JSON | 候选列表、Pareto 图和方案比较 |
| `simulation_candidate_train_adjustment` | 明细/候选 ID、列车、类型、序号、基线/优化发车秒、调整秒 | 候选逐车调整 |
| `simulation_scenario_result` | 明细/运行/候选 ID、场景、核心/可行/阻塞标志、违反度、冲突数、成本、购电、弃能、充放电、终端 SOC 偏差、摘要、详情 JSON | 跨场景稳健性 |
| `simulation_optimization_decision` | `run_id`、`action`、选中候选、原因、基线与改善指标、决策 JSON | 是否优化及采用方案 |
| `simulation_rolling_control_event` | 事件/运行ID、轮次、当前时刻、提交状态、安全状态/动作、稳健可行性、人工干预、尝试次数、请求指纹、事件JSON | 展示滚动重调度的提交、扣留、恢复和人工升级时间线 |

`action=keep_baseline` 时继续使用原运行图；`action=optimize` 时使用选中候选；`action=no_feasible_solution` 时不得自动替换运行图。

滚动优化的 `commit_status=withheld_infeasible` 必须投影为 `action=no_feasible_solution`，并在决策JSON中保存 `core_robust_feasible=false`、`operational_intervention_required=true` 和门禁原因。被扣留候选可作为结果工件保存和展示，但不能进入执行清单或后续锁定状态。

运行图优化和重空调度的决策 JSON 同时保存 `optimization_attribution` 摘要。平台仅在 `action=optimize` 时展示“建议采用”；`keep_baseline` 应同时展示 `reason`。其中 `storage_preset_changed_requires_fixed_storage_recheck` 表示储能配置发生变化，只能解释为联合规划结果，必须固定储能重算后才能发布纯调度收益。七个详细归因工件存入 `simulation_result_artifact`，文件清单和字段见 `optimization_attribution_and_bottleneck_report.md`。

滚动状态机的每轮迁移写入 `simulation_rolling_control_event`。`request_fingerprint` 用于识别重复请求，`UNIQUE(run_id, cycle_index)` 防止同一运行的同一轮被重复写入。平台在 `waiting_for_observation` 时展示等待状态，在 `manual_intervention_required` 时必须关闭自动下发并提示调度员。

### 6.4 `simulation_result_kpi`

界面汇总指标表，包含运行/候选/case、可行性、理论再生与牵引、供电臂接纳、实际回收、回收率、直用、充放电、弃能、购电、有效再生损失、终端 SOC、违反度、冲突数、成本和指标 JSON。适合总览卡片和基线/优化对比，不能替代明细表。

### 6.5 `simulation_result_artifact`

完整结果工件表，包含工件/运行 ID、相对路径、类型、媒体类型、二进制内容、字节数、SHA-256 和创建时间。保存报告、CSV、JSON、图片及工作进程日志原件，用于下载、审计和复现。

## 7. 关系与读取顺序

```text
simulation_project
  -> simulation_project_version
       -> simulation_dataset_file + 结构化输入表
       -> simulation_run -> simulation_run_parameter
            -> simulation_run_input_snapshot
            -> 审查/能量/候选/场景/KPI/决策/滚动控制事件表
            -> simulation_result_artifact
```

平台先读取 `simulation_run.status`。只有 `succeeded` 才读取结果；总览读取审查摘要、KPI 和决策，图表读取运行弧、时间片和供电臂结算，下载与复核读取结果工件。

## 8. 一致性规则

1. 同一次运行只能引用一个已发布版本，不得混用不同版本数据。
2. `storage_no_direct` 中 `direct_used_kwh=0`；储能可用已有 SOC 支持牵引，但同一时间片新充能量不能立即放出。
3. 约束违反度超过容差的候选不能标记为可行或自动采用。
4. 结果明细、工件和 `succeeded` 状态必须在同一事务提交。
5. 成功结果只允许按相同 SHA-256 幂等重试，不允许不同结果覆盖。
6. 相同 `idempotency_key` 只允许对应完全相同的请求 SHA-256；不同内容必须拒绝。
7. 输入冻结、心跳、完成和失败必须匹配当前未过期租约；旧工作进程不得覆盖重新领取或取消后的状态。
8. 状态变化与 `simulation_run_state_event` 必须在同一事务提交，状态版本单调递增。
9. 占位、规划或合成数据必须保留可信状态，界面不得标成正式结论。

部署与调用见 `database_integration_guide.md`；机器映射见 `database/io_mapping.json`；平台操作契约见 `database/platform_api_contract.json`。
