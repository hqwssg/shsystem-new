# 上下行再生能量利用三套算法目标模式提示词

> 当前朔黄口径更新：已了解朔黄铁路上下行供电相互隔离，当前算法默认不允许上下行再生能量直发直用。因此本文中历史保留的“可直发直用”模式仅用于兼容旧实验命名，不再代表当前推荐算法方案。当前主方案应采用“不能直发直用 + 储能区段吸收/释放”的模式；储能区段暂按 K145-K164、K164-K200.7 两段规划假设接入，后续按正式设备资料替换。

本文档用于把“上下行线路再生能量是否可以直发直用、是否配置储能设备”转化为算法目标模式说明和可复用提示词。当前项目已有能量结算、储能规划假设、能力富余/紧张目标和 Pareto 候选导出能力；以下三套模式用于后续实验配置、报告说明或继续扩展 CLI 参数。

当前 `run_dispatch_case.py`、`timetable_energy_audit.py` 和重空列网络优化器均按“同一供电臂 + 同一时间片”作为 direct-use 基本结算口径。若样本携带 `power_arm_id`，直接利用只在相同 `power_arm_id`、相同结算时间窗内匹配；若没有供电臂信息，才回退到旧的能量传输比例口径。

## 1. 模式 A：上下行可直发直用，无储能设备

### 工程假设

- 上下行线路之间具备直接能量协同条件。
- 重车再生制动能量可在同一结算时间步内被空车牵引用电直接吸收。
- 不配置储能设备，不能跨时间存储再生能量。
- 未被同步吸收的再生能量计为弃电。

### 算法含义

- 优先通过调度时刻调整提高“发电列车”和“用电列车”的时间重叠。
- 优化重点是让重车下坡再生功率与空车上坡牵引功率尽量同步。
- 储能容量、充放电功率、SOC、储能折旧成本不参与目标函数。

### 主要目标

1. 最大化再生能量直发直用电量。
2. 最小化弃电电量。
3. 最小化电网购电量和运行成本。
4. 保持追踪间隔、站场资源、技术作业、车流连续性可行。

### 重点输出指标

- `direct_used_kwh`
- `direct_use_ratio`
- `wasted_kwh`
- `grid_kwh`
- `total_cost`
- `resource_conflict_count`
- `flow_continuity_violation_count`

### 目标模式提示词

```text
目标模式：上下行可直发直用，无储能设备。

请将本次调度优化视为“无储能、仅依赖上下行同步直供”的再生能量利用场景。算法应优先调整重车与空车发车间隔、相位差和等待时间，使重车再生制动功率尽可能在同一时间步内被空车牵引用电直接吸收。未被同步吸收的再生能量不得进入储能，应计为弃电。

优化目标按优先级考虑：
1. 保证追踪间隔、站场/区间资源、技术作业时间、重空车流连续性可行；
2. 最大化 direct_used_kwh 和 direct_use_ratio；
3. 最小化 wasted_kwh、grid_kwh 和 total_cost；
4. 在多个 Pareto 候选方案中，优先选择直发直用比例高、弃电低、资源冲突为 0、车流连续性违规为 0 的方案。

输出时请重点比较各 Pareto 候选的 direct_used_kwh、direct_use_ratio、wasted_kwh、grid_kwh、total_cost、capacity_margin_s、resource_conflict_count 和 flow_continuity_violation_count。
```

## 2. 模式 B：上下行不能直发直用，有储能设备

### 工程假设

- 上下行线路之间不能直接进行再生能量直供。
- 重车再生制动能量不能在同一时间步直接供给空车。
- 可通过储能设备吸收再生能量，再在后续时段向牵引用电释放。
- 受储能容量、最大充电功率、最大放电功率、效率和折旧成本约束。

### 算法含义

- 直接利用通道关闭，调度不再追求上下行同一时间步功率精确重叠。
- 优化重点转为减少储能充电受限、放电受限和弃电。
- 需要关注 SOC 曲线是否合理，避免日终 SOC 被过度放空或无法恢复。

### 主要目标

1. 最大化储能吸收和后续释放的有效再生能量。
2. 最小化弃电、电网购电和储能折旧后的综合成本。
3. 控制 SOC 在合理范围内。
4. 保持调度安全、资源能力、技术作业、车流连续性可行。

### 重点输出指标

- `battery_charge_kwh`
- `battery_discharge_kwh`
- `battery_charge_limited_kwh`
- `battery_discharge_limited_kwh`
- `final_soc_kwh`
- `wasted_kwh`
- `grid_kwh`
- `battery_cost`
- `total_cost`

### 目标模式提示词

```text
目标模式：上下行不能直发直用，有储能设备。

请将本次调度优化视为“上下行不能直接能量互供、只能通过储能设备间接利用再生能量”的场景。算法不应把同一时间步内的重车再生功率和空车牵引功率计为 direct_used_kwh；再生能量必须先受储能最大充电功率、容量和效率约束进入储能，再由储能在后续牵引用电时段释放。

优化目标按优先级考虑：
1. 保证追踪间隔、站场/区间资源、技术作业时间、重空车流连续性可行；
2. 最大化 battery_charge_kwh 与 battery_discharge_kwh 的有效利用；
3. 最小化 battery_charge_limited_kwh、battery_discharge_limited_kwh、wasted_kwh、grid_kwh 和 total_cost；
4. 控制 final_soc_kwh，避免通过透支储能获得虚假低成本；
5. 在多个 Pareto 候选方案中，优先选择弃电低、电网购电低、SOC 合理、资源冲突为 0、车流连续性违规为 0 的方案。

输出时请重点比较各 Pareto 候选的 battery_charge_kwh、battery_discharge_kwh、battery_charge_limited_kwh、battery_discharge_limited_kwh、final_soc_kwh、wasted_kwh、grid_kwh、battery_cost、total_cost、capacity_margin_s、resource_conflict_count 和 flow_continuity_violation_count。
```

## 3. 模式 C：上下行可直发直用，有储能设备

### 工程假设

- 上下行线路之间可以直接能量协同。
- 储能设备也可参与再生能量吸收和释放。
- 同一时间步内优先直发直用；直供后仍有剩余再生能量时，再进入储能。
- 储能受容量、功率、效率和成本约束。

### 算法含义

- 这是能量利用条件最完整的方案。
- 优化器应同时寻找上下行功率同步和储能削峰填谷之间的平衡。
- 直发直用通常应优先于储能，因为它避免了储能往返效率损失和折旧成本。

### 主要目标

1. 优先最大化直发直用电量。
2. 在直发直用之后，最大化储能对剩余再生能量的有效吸收。
3. 最小化弃电、电网购电和综合成本。
4. 控制 SOC，避免不合理的储能透支。
5. 保持安全、资源、技术作业、车流连续性可行。

### 重点输出指标

- `direct_used_kwh`
- `direct_use_ratio`
- `battery_charge_kwh`
- `battery_discharge_kwh`
- `recovered_or_stored_ratio`
- `wasted_kwh`
- `grid_kwh`
- `final_soc_kwh`
- `total_cost`

### 目标模式提示词

```text
目标模式：上下行可直发直用，有储能设备。

请将本次调度优化视为“上下行可直接能量互供，并配置储能设备”的综合利用场景。算法应优先通过发车间隔、相位差和等待时间调整，提高重车再生制动功率与空车牵引用电功率的同步程度；同一时间步内可被牵引用电直接吸收的再生能量应优先计为 direct_used_kwh。直发直用后仍有剩余的再生能量，再受储能容量、最大充电功率和效率约束进入储能，并在后续牵引用电时段释放。

优化目标按优先级考虑：
1. 保证追踪间隔、站场/区间资源、技术作业时间、重空车流连续性可行；
2. 优先最大化 direct_used_kwh 和 direct_use_ratio；
3. 在直发直用之后，最大化 battery_charge_kwh、battery_discharge_kwh 和 recovered_or_stored_ratio；
4. 最小化 wasted_kwh、grid_kwh、battery_cost 和 total_cost；
5. 控制 final_soc_kwh，避免通过透支储能获得虚假低成本；
6. 在多个 Pareto 候选方案中，优先选择直发直用高、总回收利用率高、弃电低、电网购电低、SOC 合理、资源冲突为 0、车流连续性违规为 0 的方案。

输出时请重点比较各 Pareto 候选的 direct_used_kwh、direct_use_ratio、battery_charge_kwh、battery_discharge_kwh、recovered_or_stored_ratio、wasted_kwh、grid_kwh、final_soc_kwh、total_cost、capacity_margin_s、resource_conflict_count 和 flow_continuity_violation_count。
```

## 4. 当前主方案口径

根据目前已确认的工程前提，朔黄铁路上下行供电相互隔离，当前算法主流程只采用：

| 模式 | 直发直用 | 储能 | 调度核心 | 主要风险 |
| --- | --- | --- | --- | --- |
| 当前主方案：不可直发直用，有储能 | 否 | 是 | 通过储能跨时间转移再生制动能量 | 储能容量/功率不足时弃电高，成本受储能折旧影响 |

可直发直用相关方案仅保留为历史研究假设或代码兼容口径，不再作为当前实验、汇报和默认工作流的主结果。

## 5. 后续算法配置建议

当前 `run_dispatch_case.py` 的主流程参数为：

- `--energy-scenario storage_no_direct`

`auto` 仅作为兼容入口保留，当前也会落到 `storage_no_direct` 这一主方案。所有输出都会在 `summary.json`、`pareto_candidates.csv` 和 `ranked_candidates.csv` 中记录能源场景，避免实验报告混淆。
