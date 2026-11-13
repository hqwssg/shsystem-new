# 算法核心逻辑与代码实现说明

本项目只实现再生制动能量回收能力分析和重空列车调度优化。监测硬件、实时控制、信号联锁、碳排放平台和生产级可视化属于外部系统；统一边界及交付物见 [`algorithm_scope_and_deliverables.md`](algorithm_scope_and_deliverables.md)。

**版本：** v1.0  
**更新时间：** 2026-09-01  
**适用项目：** `D:\\dev\\project\\energy_retry`

本文把项目中的概念模型落实到代码层。它回答三个问题：一次运行从哪里开始、核心数据如何在模块之间传递、每个主要算法步骤具体做什么。本文描述的是当前实现，不是未来实时控制系统的设计。

外围运行准备度门禁见 `tools/operational_readiness_checks.py` 及
`docs/operational_readiness_checks.md`：它验证实时快照契约、严格缺失数据策略、结果来源对账、manifest 版本兼容和轻量性能回退；这些检查不改变下述核心能量计算口径。

## 1. 总体调用链

推荐入口是 `run_project.py`。端到端 `simulate` 的逻辑可以概括为：

```text
命令行参数
  -> 读取 data_dir / timetable / smart_meter
  -> validate-data
  -> meter-samples
  -> audit-timetable
  -> optimize-timetable
  -> dispatch-case
  -> 汇总 simulation_workflow_summary.json
  -> result_quality_audit
  -> run_manifest
```

对应的主要函数是：

| 阶段 | 入口函数/模块 | 主要输入 | 主要输出 |
|---|---|---|---|
| 场景解析 | `run_dispatch_case.energy_scenario_settings` | 场景枚举 | 是否直供、是否储能、场景说明 |
| 数据读取 | `run_dispatch_case.load_case_inputs`、`heavy_empty_network_optimizer.load_infrastructure_profile` | CSV/JSON/XLSX | 结构化数据对象 |
| 列车轨迹 | `train_simulator` 中的仿真函数和 `PowerSeriesCache` | 车辆、线路、出发时刻 | `StepRecord`/功率序列 |
| 单次结算 | `energy_settlement.EnergySettlementSystem.settle` | 多列车功率序列 | `SettlementResult` |
| 调度评估 | `run_dispatch_case.evaluate_dispatch_schedule` | 运行模板、功率序列、资源模型 | `ScheduleEvaluation` |
| 重空网络 | `heavy_empty_network_optimizer._build_candidate` | `HeInputBundle`、`HeScenario`、`HeGenome` | `HeCandidate` |
| 运行图优化 | `timetable_optimizer.optimize_timetable_nsga2` | 基准运行图、基因组和场景 | Pareto 候选 |
| 输出审计 | `result_quality_audit.audit_output_root` | JSON 汇总 | 质量结论和问题列表 |

## 2. 核心数据结构

### 2.1 列车运行数据

- `TrainParameters`：质量、长度、牵引/制动能力、Davis 参数等车辆参数；
- `RouteData`：线路总长、车站、区段和运行条件；
- `Segment`：起止里程、坡度、曲线和限速；
- `StepRecord`：某一离散时刻的位置、速度、牵引功率、再生功率及能量传输比例；
- `PowerSeriesCache`：按出发时刻复用列车轨迹和功率序列。

### 2.2 能量结算数据

- `BatteryStorageParameters`：容量、充放电功率、效率和成本；
- `PowerArmElectricalLimit`：供电臂牵引供电、再生吸收、上网和储能标记；
- `EnergyBucketRequest`：一个供电臂/储能区段/时间窗口的牵引和再生能量请求；
- `StorageSettlementState`：分设备 SOC 及容量/功率预算；
- `EnergyBucketSettlement`：单请求结算结果；
- `SettlementResult`：全时间轴汇总结果。

### 2.3 重空网络数据

- `HeInputBundle`：OD 需求、服务类型、线路基础设施和作业节点；
- `HeScenario`：场景、重空数量、容量目标和搜索设置；
- `HeGenome`：一个候选方案的离散决策编码；
- `HeArc`/`HeNode`：时空网络弧和节点；
- `HeCandidate`：解码后的方案、资源检查和能量结算；
- `EnergySettlementSummary`：重空候选的能量汇总。

## 3. 列车运行与功率序列

### 3.1 多分段等效模型

代码不把整列车简单当成一个点。列车头部位置是主状态，列车长度按采样段分解。每个采样点分别确定：

1. 所在坡度区段；
2. 曲线附加阻力；
3. 静态限速；
4. 供电臂和储能区段；
5. 能量传输比例。

各采样段的坡道阻力和曲线阻力累加形成列车总阻力，再结合质量、速度、牵引/制动曲线得到功率。长列车跨越坡段边界时，车头和车尾可以同时使用不同线路属性。

### 3.2 正反向处理

正向列车按线路里程递增运行；反向列车按里程递减运行，并翻转坡度符号。供电臂查找通过方向归一化，支持 `forward/reverse`，并对 `up/down` 等别名进行转换；未知非空方向会被拒绝。

### 3.3 离散时间和终点

每个离散步长更新速度和位置，并生成 `StepRecord`。终点判定包含数值容差，当前已处理列车在终点前约 2 m 因离散积分降为零速但实际已到站的情况。`length_km=0` 的点质点列车是合法输入，缓存和优化器不会再错误拒绝。

### 3.4 功率序列伪代码

```text
for each train:
    state = (head_position, speed, time)
    while not terminal:
        samples = split_train_along_length(state.head_position, train.length)
        resistance = sum(gradient_resistance + curve_resistance for samples)
        power = traction_or_regen_power(state, resistance, train.curves)
        transfer_ratio = fraction_inside_transfer_zone(samples)
        emit StepRecord(time, position, speed, power, transfer_ratio)
        state = integrate_one_step(state, power, resistance)
```

## 4. 能量结算实现

### 4.1 输入归一化和时间分桶

`EnergySettlementSystem.settle` 接收多个列车功率序列。每个样本至少包含 `(power_kW, transfer_ratio)`，还可以包含供电臂 ID、样本持续时间和储能区段 ID。代码会：

1. 检查功率、时间、传输比例是否有限且在合法范围；
2. 将跨越多个结算步长的样本切分到多个时间桶；
3. 将功率转换为 kWh；
4. 按 `(时间桶、供电臂、储能区段、未知来源)` 分组；
5. 未知供电臂按列车序列隔离，避免不同未知来源错误发生能量交换。

单个样本的能量换算为：

```text
energy_kwh = abs(power_kW) × overlap_duration_s / 3600
```

正功率进入牵引需求，负功率进入再生发电；`transfer_ratio` 把能量拆成可协同和不可协同两部分。

### 4.2 同一时间桶的结算顺序

`settle_energy_bucket_group` 对同一时间窗口执行以下顺序：

```text
1. 校验所有请求时间窗口相同
2. 按供电臂分组并合并电气能力
3. 预留不可协同能量占用的供电臂容量
4. （若允许）在可协同牵引和再生之间做直接匹配
5. 计算供电臂牵引/再生超限
6. 在剩余再生能量中分配储能充电空间
7. 若本桶发生充电，则禁止本桶同时放电
8. 否则按设备 SOC 和功率上限分配放电
9. 将剩余再生记为弃电，将剩余牵引需求记为电网购电
10. 更新每个储能设备 SOC
```

### 4.3 直接利用

直接利用只允许可协同部分配对，不可协同牵引不能消费再生能量。直接匹配量受以下最小值限制：

```text
direct = min(可协同牵引,
             可协同再生,
             牵引供电臂剩余容量,
             再生吸收臂剩余容量)
```

当前朔黄主场景关闭直接利用，因此 `direct_used_kwh` 应为 0；该逻辑仍保留用于研究假设和单元测试。

### 4.4 储能充电

设备的输入侧充电上限为：

```text
capacity_room_input = (capacity - soc_before) / efficiency
power_room = max_charge_power × duration_h
charge = min(可充再生, capacity_room_input, power_room)
soc_after_charge = soc_before + charge × efficiency
```

容量和功率是所有设备的总预算，再按当前设备数分摊。设备 ID 来自供电臂配置和几何储能标签的交集；陈旧标签不能把不可用供电臂变成可用储能。

### 4.5 储能放电

只有在本时间桶没有发生充电、效率大于 0 且设备存在 SOC 时才允许放电：

```text
discharge = min(剩余牵引需求,
                soc_before,
                max_discharge_power × duration_h)
soc_after = soc_before - discharge
```

这样可避免“同桶充入后立即放出”制造虚假节能，也避免效率为 0 的设备利用初始 SOC 产生虚假购电减少。

### 4.6 汇总和有效损失

结算结果同时提供三层回收能力指标：`accepted_by_power_arm_kwh` 表示供电臂/时间匹配后被直接利用或送入储能的再生侧能量；`recovered_energy_kwh` 将储能充电量按储能效率折算为仍可利用的输出侧能量；`recovery_rate` 为有效回收能量与理论再生能量之比。该组指标用于解释结果，不替换当前优化目标 `energy_term`。

全局结果满足：

```text
total_gen = direct_used + battery_charge + wasted
total_con = direct_used + battery_discharge + grid
final_soc = sum(final_soc_by_storage)
```

`storage_no_direct_effective_loss_kwh` 不把初始 SOC 放电错误归因于本评价窗口的新再生能量，并单独计入终端 SOC 短缺。该指标用于场景比较，不能替代电表实测损耗。

## 5. 重空时空网络实现

### 5.1 建图

`load_he_input_template` 读取模板和线路数据，`_build_candidate` 根据 `HeGenome` 生成候选。节点通常表示站点、时间和作业状态；弧表示：

- 起点出发；
- 区间运行；
- 停车/等待；
- 装车、卸车；
- 解编、取送和编组；
- 虚拟编组；
- 终止。

### 5.2 重车和空车

重车、空车是两类服务层。候选方案必须满足 OD 需求、服务数量、站场作业和初始库存。`resource_constraints.py` 通过区间、车站、股道、咽喉、技术作业和追踪间隔检查可行性。

### 5.3 候选评估

每个候选大致经过：

```text
genome
  -> 解码成重/空车服务和发车时刻
  -> 生成列车轨迹和运行弧
  -> 生成资源占用区间
  -> 检查资源冲突和车流连续性
  -> 生成供电臂/时间片能量
  -> 执行 storage_no_direct 结算
  -> 计算能量、吞吐、冲突、延误和成本目标
```

`summarize_energy_settlement` 汇总候选各时间片结果，并保留分储能设备 SOC，避免只保存一个可能少算的总值。

## 6. 运行图优化实现

### 6.1 基线评估与是否优化的正式门控

运行图优化先把输入运行图作为 `baseline`，在 `storage_no_direct` 场景下完成可行性和能量评估，再对候选方案进行同口径比较。只有候选满足硬约束，且有效再生损失或电网购电量至少一项超过既定数值容差改善、另一项没有明显恶化时，结果中的 `optimization_decision.action` 才为 `optimize`；否则为 `keep_baseline`，保留原运行图。无改善时原因记录为 `no_material_energy_improvement`。该门控同时适用于规则候选和 NSGA-II。

### 6.2 候选表示

`TimetableGenome` 由列车偏移和可调整停站/作业时长组成。`decode_genome_to_timetable` 把基因组还原成运行图；`shift_train` 和 `extend_dwell_from_stop` 是两个基础变换。

### 6.3 可行性和目标

`validate_candidate` 检查追踪间隔、站点时序和资源限制，`candidate_constraint_violation` 计算违反程度。候选目标由 `_candidate_objectives` 生成，通常包含：

- 电网购电或能量成本；
- 再生能量弃用；
- 运输能力/吞吐；
- 延误或时刻调整幅度；
- 资源冲突惩罚。

### 6.3 NSGA-II

`optimize_timetable_nsga2` 的核心步骤是：

```text
初始化基准基因组和随机基因组
for generation in generations:
    解码基因组并评估候选
    non_dominated_fronts 分层
    assign_crowding_distance 计算拥挤距离
    tournament_select 选择父代
    crossover_genomes 交叉
    mutate_genome 变异
    select_next_generation 保留下一代
输出非支配候选和 Pareto 前沿
```

优化只改变候选排序和运行图决策，不应破坏能量结算守恒。固定随机种子时，回归基线会比较规范化输出指纹。

## 7. 资源约束实现

`resource_constraints.py` 将列车轨迹转换为资源占用区间：

1. 根据出发时刻和轨迹计算到达/离开站点时间；
2. 计算区间占用和车尾清空时间；
3. 添加站场股道、咽喉和技术作业区间；
4. 按资源 ID 检查重叠和容量；
5. 识别单线对向冲突、追踪间隔冲突、站场容量冲突和咽喉冲突；
6. 生成可解释的冲突类型和建议。

当前真实闭塞分区和完整站场拓扑不完整，所以资源模型虽可运行，仍属于部分启发式工程模型。

## 8. 结果审计实现

`result_quality_audit.audit_output_root` 扫描工作流、dispatch 和优化结果：

- JSON 是否存在且格式正确；
- 核心能量指标是否存在且非负有限；
- 发电侧和牵引侧是否守恒；
- `final_soc_kwh` 是否等于分设备 SOC 之和；
- SOC 是否位于 `[0, capacity]`；
- 流程汇总是否标记 `valid=false`；
- 输出目录是否存在可识别结果。

审计通过表示结果结构和基本物理账本一致，不表示输入参数已经是正式现场参数。

## 9. 一次最小算例的追踪

假设一个 10 秒时间桶中有：

- 100 kWh 可协同再生；
- 60 kWh 牵引需求；
- 储能初始 SOC 为 0；
- 储能容量 50 kWh，效率 0.9；
- 允许储能，不允许直接利用。

执行过程：

1. 直接利用为 0；
2. 充电输入最多为 `min(100, 50/0.9)`，即 55.56 kWh，但还受功率上限限制；
3. 若功率足够，充入 55.56 kWh，SOC 增加 50 kWh；
4. 剩余 44.44 kWh 记为弃电；
5. 同桶 60 kWh 牵引不能使用刚充入的能量，全部记为电网需求；
6. 汇总满足发电侧 `100 = 0 + 55.56 + 44.44`，牵引侧 `60 = 0 + 0 + 60`。

这个例子说明：储能充入量是输入侧能量，SOC 增量还要乘效率；同桶禁止充放电是当前明确口径。

## 10. 代码阅读建议

建议按以下顺序阅读源码：

1. `run_project.py`：命令分发和端到端流程；
2. `run_dispatch_case.py`：场景、候选评估和报告；
3. `energy_settlement.py`：能量结算核心；
4. `train_simulator.py`：列车运动和功率生成；
5. `power_arm_electrical_limits.py` / `power_arm_lookup.py`：供电边界；
6. `resource_constraints.py`：资源区间和冲突；
7. `heavy_empty_network_optimizer.py`：重空网络；
8. `timetable_optimizer.py`：运行图 NSGA-II；
9. `result_quality_audit.py`：输出审计；
10. `tests/smoke/`：每个边界和历史缺陷的可执行证据。

## 11. 当前实现与正式工程之间的差异

逐函数参数、返回对象和异常约定见 `docs/algorithm_api_reference.md`。

代码逻辑已经可以完成离线模拟，但以下内容仍需正式数据或生产接口：

- 车辆牵引/制动曲线和 Davis 参数；
- 供电臂真实牵引/回馈能力；
- 储能设备容量、功率、效率、SOC 和接入位置；
- 正式运行图和实时任务；
- 完整信号、闭塞和站场拓扑；
- 电表计量口径和大样本校准；
- 现场实时状态和控制下发接口。

因此，不应只根据代码逻辑完整就宣称节能率已经工程验证。正式数据到位后的入口是 `official-data-readiness`，并且必须通过正式数据验收和结果质量审计。

## 12. 已完成的低风险性能优化

线路区段、曲线和供电臂记录在加载时已按里程排序。`_arc_infrastructure_attributes` 现在在扫描过程中遇到起点已达到当前弧终点的记录时提前结束，避免对后续不可能相交的记录重复计算。该优化不改变任何能量、SOC 或约束逻辑；合成回归基线和重空网络回归均通过。单次运行图优化 profile 由约 32.5 s 降至约 25.8 s，具体收益仍需在正式数据和固定硬件下重复测量。

## 12. 模块交叉、消融与单调性检查

`tools/algorithm_consistency_checks.py` 提供不依赖正式数据的三类自动检查：

1. **模块间交叉验证**：用同一合成时间片分别调用 `EnergySettlementSystem` 和 `evaluate_scenario_time_slices`，逐项比较发电量、牵引量、充放电量、弃电量、电网购电量和终端 SOC。当前差异全部为 0。
2. **基线/消融验证**：比较启用储能与禁用储能的同一功率序列，要求储能不会增加电网购电或弃电，并确认 `storage_no_direct` 不产生直供量。
3. **参数单调性验证**：逐步增加储能容量、充放电功率和效率，检查电网购电量、弃电量不应反向增加。

运行：

```powershell
python tools/algorithm_consistency_checks.py --output-dir outputs/algorithm_consistency_checks
```

机器可读结果在 `algorithm_consistency_summary.json`，人工摘要在 `ALGORITHM_CONSISTENCY_CHECKS.md`。该检查已纳入本地 CI，并有 `tests/smoke/verify_algorithm_consistency_checks.py` 回归入口。它验证的是模块关系和基本物理趋势，不替代正式数据校准。
