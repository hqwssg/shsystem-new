# 核心算法 API 参考

本文补充函数级输入、输出、异常和边界说明。它只覆盖稳定、会影响算法结果的公共/半公共接口；内部绘图和报表辅助函数不逐一列出。

## 1. 能量结算 API

### `EnergySettlementSystem(...)`

```python
EnergySettlementSystem(
    battery: BatteryStorageParameters,
    energy_transfer_ranges_km: list[tuple[float, float]] | None = None,
    settlement_time_step_s: int = 1,
    initial_soc_kwh: float | None = None,
    target_final_soc_kwh: float | None = None,
    final_soc_tolerance_kwh: float = 0.0,
    final_soc_penalty_per_kwh: float = 0.0,
    wasted_energy_penalty_per_kwh: float = 0.0,
    allow_direct_use: bool = False,
    allow_storage: bool = True,
    power_arm_limits: Mapping[str, PowerArmElectricalLimit] | None = None,
    storage_runtime_states: Iterable[StorageDeviceRuntimeState] | None = None,
)
```

输入含义：`battery` 是容量、效率、功率和成本参数；`settlement_time_step_s` 必须是正整数；`initial_soc_kwh` 和可选终端 SOC 必须位于容量范围内；两个布尔开关决定是否允许直供和储能；`power_arm_limits` 提供供电臂能力。`storage_runtime_states` 按设备提供滚动窗口起点SOC、可用状态和临时功率上限，提供后以逐设备状态为准。`energy_transfer_ranges_km` 主要用于兼容旧调用，当前样本中的几何传输比例仍是权威值。

构造阶段会拒绝负数、非有限值、效率大于 1、初始/目标 SOC 超容量和非法时间步长。

### `EnergySettlementSystem.settle(power_series_list)`

输入是多个列车功率序列，每个序列为 `dict[int, PowerSample]`；样本至少包含 `(power_kW, transfer_ratio)`，可追加 `power_arm_id`、`sample_duration_s` 和 `storage_section_id`。正功率代表牵引，负功率代表再生。

返回 `SettlementResult`，包含总发电/用电、直供、充放电、弃电、电网购电、SOC、成本、时间轴功率，以及各设备额定参数、初始/终端SOC、充电量、放电量和弃能量。函数会切分跨桶样本，并按时间、供电臂、储能区段结算。

### `EnergySettlementSystem.with_storage_runtime_states(...)`

复制当前结算器并应用逐设备实时状态。显式状态必须完整覆盖当前预设中的全部储能设备；未知ID、缺失设备、重复ID、SOC超容量或临时功率超过静态额定值都会拒绝。停运设备保留SOC，但有效充放电功率为零。

### `BatteryStorageParameters.storage_devices`

平台数据库快照加载的 `StorageDeviceParameters` 集合。每台设备分别提供容量、额定充放电功率、充电效率、放电效率、初始SOC、SOC上下限和静态投运状态。存在该集合时，结算器不再等分聚合电池参数；结果通过 `storage_parameters_by_id` 暴露实际采用的逐设备规格。

### `RollingWindowState` 与 `RollingCycleObservation`

两者的 `storage_device_states` 接收稳定排序的 `StorageDeviceRuntimeState` 元组。设备状态进入滚动观测指纹、求解请求指纹、候选能量评价和诊断输出。旧 `storage_soc_kwh` 汇总字段仅用于兼容，两者同时提供会抛出 `ValueError`。

异常：序列不是字典、样本字段不足、功率/时间非有限、传输比例不在 `[0,1]`、时间为负或非整数、持续时间非正都会抛 `TypeError` 或 `ValueError`。

### `settle_energy_bucket_group(requests, *, allow_direct_use, allow_storage, storage_state)`

输入是同一时间窗口的 `EnergyBucketRequest` 列表。每个请求包含牵引、再生、不可协同部分、起止秒、储能区段、供电臂能力和显式配置标记。

返回与请求一一对应的 `EnergyBucketSettlement` 列表。结算顺序固定为：直接匹配 → 供电臂超限 → 储能充电 → 同桶禁止放电 → 储能放电 → 弃电/电网补能。

所有请求必须使用完全相同的时间窗口；供电臂能力不一致、储能标签与显式供电配置不匹配时拒绝结算。

### `storage_no_direct_effective_loss_kwh(...)`

计算评价窗口内未被有效利用的再生能量。它不会把初始 SOC 的放电全部归因于本窗口新充电量，且会计入终端 SOC 短缺。参数均为非负有限数，效率必须在 `[0,1]`。

## 2. 列车功率序列 API

### `build_power_series(records, depart_time_s)`

把按相对时间排列的 `StepRecord` 转为绝对时刻字典。`records` 的时间必须严格递增，`depart_time_s` 必须是非负整数，传输比例必须在 `[0,1]`。重复时间、倒序时间、负发车时刻和非法比例会被拒绝。

### `run_dispatch_case.build_power_series(cache, depart_times_s, sample_step_s=1, storage_hold_s=0, operation_delay_events_by_departure=None)`

从 `PowerSeriesCache` 为多个发车时刻生成功率序列。`sample_step_s` 控制重采样，`storage_hold_s` 表示储能保持窗口，延误事件用于将运行轨迹后的作业延迟传给资源和能量评估。输出是功率序列列表。

## 3. 调度评估 API

### `evaluate_dispatch_schedule(...)`

输入包括标签、`GeneratedSchedule`、线路、重车/空车缓存、结算系统、资源模型、储能区段、目标间隔、最小发车间隔、目标模式、能量场景和目标优先级。

执行顺序：生成/读取轨迹 → 检查资源 → 结算能量 → 计算运输、能量和成本指标 → 生成 `ScheduleEvaluation`。资源或流连续性不满足时保留不可行状态和解释，不会把冲突静默当作可行。

### `settle_schedule(...)`

只执行给定运行计划的功率序列构建和能量结算，返回 `SettlementResult`。若提供 `resource_model`，还会执行资源相关的计划检查。

### `check_schedule_resources(...)`

根据重/空车缓存和资源模型生成资源区间，返回 `ResourceCheckResult`，其中包含冲突数量、冲突类型和可解释明细。

## 4. 重空时空网络 API

### `load_infrastructure_profile(data_dir)`

读取站点、坡度、曲线、供电臂、储能区段和边界信息，返回 `InfrastructureProfile`。文件缺失、格式错误、里程非法或方向无法归一化时抛异常。

### `load_he_input_template(path, real_data_dir)`

读取重空 OD、服务类型、作业节点和线路基础设施，返回 `HeInputBundle`。该函数只加载和校验输入，不运行优化。

### `optimize_heavy_empty_network(bundle, scenario_id)`

输入是已校验的 `HeInputBundle` 和场景 ID，返回 `HeOptimizationResult`，包括候选集、Pareto 集、最佳候选、可行性和搜索诊断。场景中的列车数量、容量和搜索规模由 `HeScenario` 控制。

### `summarize_energy_settlement(candidate, time_slice_s, battery, power_limits)`

对一个重空候选按时间片和供电臂结算，返回 `EnergySettlementSummary` 及逐窗口行。`time_slice_s` 必须是正整数；汇总保留分设备 SOC。

## 5. 运行图优化 API

### `validate_candidate(timetable, headway_min)`

检查候选运行图的站点时序、列车追踪间隔和基本资源约束，返回 `(valid, reasons)`。它是硬约束检查，不负责计算能量。

### `evaluate_candidates(candidates, power_sections, resource_model=None, infrastructure=None, default_storage_efficiency=None)`

批量计算候选的运行图能量场景和资源结果，返回场景行和问题行。候选输入中的时间、站点和列车 ID 必须能映射到基础数据。

### `optimize_timetable_nsga2(...)`

关键参数：基准运行图、输出目录、供电区段、最大时刻偏移、离散步长、最大停站延长、种群规模、代数、交叉率、变异率、随机种子、资源模型和可选可视化严格模式。返回包含候选、Pareto 前沿、代际日志、场景得分和输出文件的字典。

种群规模和代数必须为正整数，概率在 `[0,1]`；固定 `seed` 才能进行严格回归。`strict_visualizations=True` 时图表生成失败会使流程失败，默认模式只记录诊断。

## 6. 资源约束 API

### `check_flow_continuity(schedule, model, heavy_cache, empty_cache)`

检查重空车流在站点和任务之间是否连续，返回 `(valid, event_rows, violation_rows)`。它使用库存、装卸/解编作业和列车任务映射，不能替代正式业务台账。

### `check_schedule_resources(schedule, model, heavy_cache, empty_cache)`

将列车轨迹转换为资源占用区间，检查单线对向、追踪间隔、站场股道、咽喉和技术作业冲突。

## 7. 结果审计 API

### `audit_output_root(output_root)`

扫描工作流、dispatch 和优化输出，检查 JSON 可解析性、核心指标非负有限、发电/用电守恒、分设备 SOC 汇总、SOC 容量边界和 `valid=false` 标记。返回包含 `accepted`、错误/警告计数和问题列表的字典。

注意：审计通过只表示输出账本和结构一致，不代表输入参数来自正式现场资料。

## 8. 历史扰动回放 API

### `load_historical_disturbance_replay(path)`

读取UTF-8 JSON，执行严格字段、版本、时间轴、来源记录ID、事件和设备状态校验，返回 `HistoricalDisturbanceReplay`。返回对象携带原文件SHA-256，可通过 `manifest()` 生成结果追溯清单；`observations` 属性可转换为滚动优化器消费的 `RollingCycleObservation` 序列。`blocking_events` 列出合同合法但因正式业务规则缺失而不能安全执行的事件。

周期必须从0连续编号，`current_time_s` 必须与固定 `execute_window_s` 对齐，`observed_at` 必须是带时区且严格递增的ISO 8601时间戳，源记录ID不得重复。未知字段、非法晚点、乱序时间或不完整设备状态都会在启动求解前抛出 `ValueError`。

`train_delay`事件按 `H001/E001` 稳定编号直接作用于未来未锁定列车；同方向汇总晚点与逐车晚点互斥，改写锁定历史、引用窗口外列车或造成越序时拒绝。`1.2` 合同直接执行取消、加车、资源封锁、供电动态限值、双向临时限速和完整设备状态；`1.3` 进一步执行方向专用临时限速，并按列车 `forward/reverse` 方向重建对应轨迹。`1.0/1.1` 的动态事件和 `1.2` 的方向专用限速保持原版本阻断语义，不会因程序升级而静默改变历史结果。

`preflight()` 返回 `execution_allowed`、输入清单和逐事件 `accepted/blocked` 状态，供平台在创建求解任务前展示阻断原因。

### `run_benchmark(..., disturbance_replay=None)`

提供 `HistoricalDisturbanceReplay` 时，外部历史周期替代内置合成晚点序列；每周期提供的设备状态是该时刻的权威观测，未提供时沿用上一执行窗口的结算终态。历史回放不能与独立的初始设备运行状态同时传入。

## 9. 错误处理约定

`SettlementResult` 提供只读派生属性 `accepted_by_power_arm_kwh`、`recovered_energy_kwh` 和 `recovery_rate`，分别对应供电臂接纳量、效率折算后的有效回收量和有效回收率。它们不改变既有结算字段和优化排序。

| 错误类型 | 含义 | 推荐处理 |
|---|---|---|
| `TypeError` | 对象类型不符合契约 | 修正调用方数据结构 |
| `ValueError` | 数值、时间、方向、窗口或枚举非法 | 修正输入并重新验收 |
| `accepted=false` | 门禁或结果审计发现阻断问题 | 不发布结果，查看 issues |
| `valid=false` | 某流程完成但候选/数据不可接受 | 保留报告，不能当作正式结果 |

算法不会把负能量、非有限值、未知复合供电臂或不一致时间窗口静默转换成可行值。
