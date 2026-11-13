# 朔黄铁路再生制动能量协同调度算法技术说明

## 1. 项目背景

> 当前实现状态（2026-08-25）：统一入口和默认数据目录已切换为 `python run_project.py` 与 `data/real_shuohuang/`。本文保留早期技术方案和模型演进背景；当前项目状态、数据生命周期、输入输出契约和可信边界以 [`docs/current_project_status_and_io.md`](../current_project_status_and_io.md) 与 [`docs/current_algorithm_validity_boundary.md`](../current_algorithm_validity_boundary.md) 为准。旧文中的 `data/real_partial`、594 km 和长大下坡示例属于历史/虚拟口径，不应覆盖当前运行结果。

本项目面向朔黄铁路重载运输场景，研究基于再生制动能量回收利用的列车调度算法。

目标运行场景如下：

- 重载列车下坡运行时产生再生制动能量。
- 空车在相反方向上坡运行时消耗牵引能量。
- 柔性牵引供电系统可在特定供电区间内实现能量传递和协同利用。
- 储能装置可吸收未被即时利用的再生电能，但储能存在容量上限、效率损失和折旧成本。

调度算法的目标是在保证列车运行安全和运输性能的前提下，提高再生制动能量利用率，降低电网购电和弃电。

项目最初采用虚拟数据构建算法原型。随后从 `列车运行图及技术资料.pdf` 中整理并接入一部分朔黄线真实数据，形成历史混合数据集 `data/real_partial`。当前统一入口默认使用已重建的 `data/real_shuohuang`；两个目录的字段口径和可信边界以 `docs/current_project_status_and_io.md` 为准。由于线路几何、牵引制动、真实闭塞、供电和储能等关键资料仍缺失，当前结果仍不能视为工程级真实调度结论。

## 2. 历史虚拟基线与当前状态

以下数值是早期虚拟数据基线，由 `sandbox_data.py` 生成并保存到 `sandbox_config.json`，仅用于解释模型演进；不代表当前默认运行参数。正式运行时，线路终点、站点和线路分段由所选 `--data-dir`（默认 `data/real_shuohuang/`）中的 `route_metadata.json`、`stations.csv` 和 `segments.csv` 读取。

历史虚拟线路假设：

- 线路长度：594 km
- 最高运行速度：120 km/h
- 车站数量：33 个
- 地形类型：山区、丘陵、平原
- 分段精度：1 km
- 每个线路分段包含：
  - 坡度
  - 曲线半径
  - 地形类型
- 重车长大下坡区间：62 km 至 302 km
- 柔性牵引供电协同区间：
  - 东冶至滴流磴：145.0 km 至 164.0 km
  - 滴流磴至小觉：164.0 km 至 200.7 km

柔性牵引供电区间参考了公开资料中关于“东冶站-滴流磴站-小觉站”三站两区间柔性牵引供电系统的描述。由于公开资料未完整给出精确里程，当前里程为虚拟锚定值，后续应根据甲方正式资料替换。

历史虚拟列车假设：

- 重车：
  - 运行方向：正向
  - 列车长度：2.7 km
  - 纵向采样段数：20
  - 质量：10000 t
- 空车：
  - 运行方向：反向
  - 列车长度：2.7 km
  - 纵向采样段数：20
  - 质量：2000 t

2.7 km 的列车长度参考公开资料中对朔黄铁路两万吨级重载列车长度的描述。当前假设重车与空车采用相同编组长度，区别主要体现在质量和牵引/制动需求上。

### 2.1 历史朔黄线 `real_partial` 数据集（兼容/追溯）

项目曾新增 `data/real_partial`，作为 PDF 真实数据和必要占位数据的混合输入目录。该目录保留用于历史复现和字段追溯；当前默认运行不再从该目录读取。项目范围只包含朔黄线；PDF 中属于黄万线、黄大线的数据只保留为归档，不进入当前算法输入。

已按 PDF 接入或校准的数据包括：

- 朔黄线 34 个站点及里程，建模范围为神池南 K0+00 至黄骅港 K589+196。
- `route_metadata.json` 中的线路终点已更新为 `583.003 km`。
- `segments.csv` 和 `signaling_blocks.csv` 已裁剪到 K589+196。
- 站场 `track_capacity` 来自 PDF 站表股道数量，但该数量包括正线，是否扣除正线仍需确认。
- 重车典型质量采用 PDF 2 万吨 C80 代表列车 `21600 t`。
- 重车长度由 PDF 换长 237.6 按 11 m 换长系数换算为 `2.6136 km`。
- 神池南至 K76+293 的重车/空车 75 km/h 限速已写入运行条件和分段限速。
- 朔黄线 2 万吨列车 15 min 追踪间隔已通过 `headway_constraints.csv` 进入最小发车间隔约束。
- PDF 技术作业时间已整理到 `technical_operation_times.csv`，并通过 `station_operation_assignments.csv` 只作用于明确指定的终到作业场景。
- 空车质量标注为代表性场景占位，可用 `run_dispatch_case.py --empty-mass-tons` 做敏感性分析。
- 储能参数标注为规划/敏感性假设，因为储能设备尚未实施，当前没有实测参数。

仍保留占位或启发式的数据包括：

- 逐段坡度、曲线半径和地形。
- 长大下坡真实边界。
- 真实闭塞分区、咽喉能力、进路锁闭和站场拓扑。
- 区间容量模型，目前使用 `ceil(section_length / section_capacity_spacing_km)` 的启发式近似。
- 牵引力、制动力、Davis 阻力系数和黏着相关参数。
- 柔性供电、供电臂、再生能量传输区间和储能数值参数。

因此，`data/real_partial` 的定位是“朔黄线 PDF 部分真实数据接入后的历史可运行混合数据集”，不作为当前默认结果口径。它比原始虚拟数据更接近真实线路边界和部分运营约束，但仍主要用于流程验证、约束接入验证和数据治理演示。

## 3. 列车运行仿真模型

列车仿真由 `train_simulator.py` 实现。

项目最初采用点质点列车模型。当前已升级为“列车长度感知的多分段等效模型”。

对于每一列车：

- 以车头位置作为运行轨迹主变量。
- 将 2.7 km 列车长度划分为多个纵向采样点。
- 每个采样点分别读取：
  - 当前坡度
  - 曲线半径
  - 是否位于柔性牵引供电区间
  - 是否位于长大下坡区间
- 总坡道阻力和曲线阻力由各采样点累加得到。

该模型解决了点质点模型中的关键问题：车头进入下坡区间时，车尾可能仍处于平坡或上坡区间；车头离开下坡区间时，车尾可能仍在下坡区间。多分段模型能更合理地反映长大列车跨越复杂线路条件时的受力与功率变化。

运行方向处理（以下 594 km 仅为历史虚拟基线；运行时使用数据目录中的线路终点）：

- 重车从 0 km 向 594 km 正向运行。
- 空车从 594 km 向 0 km 反向运行。
- 对反向运行列车，线路坡度从列车运行视角取相反符号。

因此，同一物理线路区间可同时表现为重车方向的下坡再生制动区间，以及空车方向的上坡牵引区间。

## 4. 能量结算模型

能量结算由 `energy_settlement.py` 实现。

模型将列车功率分为：

- 再生制动发电功率
- 牵引用电功率
- 柔性供电区间内直接协同利用电量
- 储能充电电量
- 储能放电电量
- 弃电电量
- 电网购电量

核心原则：

- 不再将全线视为一个统一的能量回收大区间。
- 只有配置中的柔性牵引供电区间允许参与直接能量协同和储能调节。
- 当列车只有部分长度处于柔性供电区间时，仅按列车采样段占比计算可参与协同的功率。
- 柔性供电区间外产生的再生电能计入弃电。
- 柔性供电区间外的牵引用电计入电网购电。

储能模型包含：

- 储能容量
- 最大充电功率
- 最大放电功率
- 往返效率
- 单位电量折旧成本
- 电网购电单价

能量结算支持可配置时间步长 `settlement_time_step_s`：

- `1s`：精细结算模式
- `10s` 或 `30s`：用于滚动优化的快速评价模式
- 对最终候选方案可再使用 `1s` 模式进行复核

根据目前已确认的工程前提，朔黄铁路上下行供电相互隔离，当前主流程不再按三套能源场景分别评估，而是采用“上下行不能直发直用、有储能设备”的储能利用方案。

历史上讨论过的可直发直用场景仅作为研究假设保留，不再作为当前实验、汇报和默认工作流的主结果。当前主方案的工程假设、目标优先级和提示词见 `docs/energy_scenario_objective_prompts.md`。

`run_dispatch_case.py` 已支持 `--energy-scenario` 参数：

- `storage_no_direct`：禁用上下行直发直用，允许储能。
- `auto`：兼容入口，当前等价于主方案 `storage_no_direct`。

该参数会同时影响能量结算和优化器能源场景目标，并写入 `summary.json`、`pareto_candidates.csv` 和 `ranked_candidates.csv`。

## 5. 安全与闭塞约束

安全约束由 `scheduler_nsga2.py` 实现。

项目已不再仅使用简单的发车间隔约束，而是支持可配置的信号闭塞系统：

- 固定闭塞
- 移动闭塞
- 固定闭塞与移动闭塞混合模式

当前默认配置如下：

```json
{
  "mode": "hybrid",
  "fixed_block_length_km": 2.0,
  "fixed_block_protection_blocks": 2,
  "moving_block_base_buffer_m": 500.0,
  "moving_block_reaction_time_s": 30.0,
  "moving_block_follower_service_decel_mps2": 0.28,
  "moving_block_lead_emergency_decel_mps2": 0.5,
  "check_step_s": 5
}
```

固定闭塞约束：

- 根据列车头尾位置映射到闭塞分区。
- 要求后续列车与前车尾部之间保留指定数量的保护分区。
- 支持正向和反向列车运行。

移动闭塞约束：

- 计算前车尾部到后车车头之间的净距离。
- 与动态制动安全距离比较。
- 动态安全距离包含：
  - 固定安全余量
  - 反应时间距离
  - 后车常用制动距离与前车紧急制动距离的差值

当前信号模型仍基于虚拟容量假设。若用于工程落地，还需要用真实闭塞分区、站场联锁、道岔进路、咽喉区冲突和进路锁闭数据替换。

### 5.1 站场/区间资源约束与冲突解释

当前原型新增了 `resource_constraints.py`，用于建立站场/区间资源层。
它根据列车运行轨迹和车站里程，推导列车对区间、车站股道和咽喉进路的占用。

已覆盖资源包括：

- 区间按方向占用
- 可选单线/共用区间占用
- 车站到发线容量
- 车站咽喉/进路锁闭容量
- 同向区间容量冲突
- 对向区间冲突
- 车站股道容量冲突
- 咽喉进路冲突
- 同向越行/运行顺序反转检查

每条冲突解释包含：

- 冲突类型
- 资源编号和资源名称
- 涉及列车编号和类型
- 冲突开始、结束和持续时间
- 里程或位置
- 可读的冲突说明
- 推荐的调度调整方向

`rolling_optimizer.evaluate_schedule` 和 `RollingOptimizer` 现在支持可选 `ResourceModel`。
传入资源模型后，存在站场或区间资源冲突的候选方案会被判为不可行。
`tests/legacy/verify_resource_constraints.py` 会将验证结果输出到 `outputs/resource_constraints`。

在历史 `data/real_partial` 中，资源层的真实/占位边界如下（当前默认目录同步保留同类来源标记）：

- 车站位置和股道数来自 PDF。
- 2 万吨追踪间隔来自 PDF，并作为最小发车间隔。
- 技术作业时间来自 PDF，但只在 `station_operation_assignments.csv` 指定的列车任务上应用。
- 咽喉能力、进路锁闭、真实闭塞分区和区间容量仍为启发式或占位数据。
- 技术作业时间当前按站点级可用最大值处理，不是任务级精确值。

## 6. 调度优化框架

项目目前包含两层调度优化能力。

### 6.1 原始 NSGA-II 模块

原始 NSGA-II 算法位于 `scheduler_nsga2.py`。

该模块可以优化少量列车的具体发车时刻。但对于朔黄铁路每天上百对列车的真实规模，如果直接将每趟列车发车时刻作为变量，会出现严重的维度爆炸，传统 NSGA-II 难以在有效时间内收敛。

因此，项目进一步引入了低维策略模板和滚动优化框架。

### 6.2 低维 NSGA-II 策略优化

主调度框架位于 `rolling_optimizer.py`。

它不直接优化每一趟列车的绝对发车时刻，而是优化少量可解释的调度策略参数：

- 重车发车间隔
- 空车发车间隔
- 重车与空车之间的相位差
- 柔性供电区间等待时间
- 滚动窗口内重车数量
- 滚动窗口内空车数量

这些策略参数可以展开生成完整的窗口内发车计划。

低维优化器采用轻量级 NSGA-II：

- 非支配排序
- 拥挤距离
- 锦标赛选择
- 交叉
- 变异
- Pareto 候选提取

优化目标包括：

- 平均运营成本
- 发车间隔偏差
- 最坏扰动场景成本
- 能力场景附加目标：`balanced` 保持原始成本/间隔/鲁棒性平衡；`capacity_surplus` 奖励更大的发车能力裕度；`capacity_tight` 奖励更紧凑地使用发车能力。

该方法将搜索空间从几百个列车级变量降维为少量策略变量，既降低计算难度，又便于解释和汇报。

`run_dispatch_case.py` 现在会在输出最终推荐方案的同时，导出当前搜索窗口内的非支配可选方案集：

- `pareto_candidates.csv`：可选 Pareto 候选方案，包含模板参数、目标值、能力裕度、车流连续性、资源冲突和发车时刻。
- `pareto_candidates.json`：与 CSV 对应的机器可读版本，保留发车时刻数组。
- `ranked_candidates.csv`：所有已评估候选方案，按优化器排序值输出，便于诊断搜索空间。

当前 Pareto 集仍来自低维发车模板搜索，不是完整网络流求解器在所有网络弧上的全局 Pareto 前沿。

### 6.2.1 车流连续性约束

当前项目已在 `resource_constraints.py` 中新增重车-空车-重车连续性检查。该约束按时间顺序维护两类车流库存：

- 重车发车：消耗 1 个 `Heavy` 车流单元。
- 重车到达并完成卸车：释放 1 个 `Empty` 车流单元。
- 空车发车：消耗 1 个 `Empty` 车流单元。
- 空车到达并完成装车：释放 1 个 `Heavy` 车流单元。

该约束依赖 `station_operation_assignments.csv` 与 PDF 技术作业时间中的装车/卸车作业类型。当前 `data/real_partial/resource_config.json` 提供 `initial_heavy_flow_count`、`initial_empty_flow_count` 和 `enforce_flow_continuity` 参数。由于当前 PDF 数据没有提供调度窗口开始时的真实车底/车流库存，初始库存仍是场景假设；如果后续拿到真实车流初始状态，可以直接替换这两个参数。

`run_dispatch_case.py` 会导出：

- `flow_continuity_events.csv`：重车发车、卸车形成空车、空车发车、装车形成重车等事件。
- `flow_continuity_violations.csv`：车流库存不足导致的连续性违规。

存在车流连续性违规的候选方案会被判为不可行。

### 6.3 节点-弧段时空网络层

当前项目已新增 `time_space_network.py`，用于把候选调度方案展开为节点-弧段时空网络。

网络节点表示某一列车在某一车站、里程和时刻上的事件状态，例如源点、到达、通过、技术作业后发出和汇点。

网络弧段表示列车活动，包括：
- `origin_departure`：从计划源点进入线路的发车弧。
- `running`：车站或区间节点之间的运行弧，弧段能耗来自列车动力学仿真的功率序列积分。
- `waiting`：技术作业总时长中尚不能细分到具体动作的等待或缓冲时间。
- `spotting`：对位、送车等作业弧，来自 PDF 技术作业时间表中的送车/对位时间。
- `loading`、`unloading`、`loading_unloading`：装车、卸车或无法进一步区分的装卸作业弧，来自 PDF 技术作业时间表中的装卸时间。
- `pickup`：取车作业弧，来自 PDF 技术作业时间表中的取车时间。
- `dismantling`：终到后列车拆解占位弧；当前作为零时长衔接弧，用于表达后续车底流转边界。
- `virtual_trainset`：虚拟车底衔接弧；当前作为零时长占位弧，用于后续接入车底循环或空重转换约束。
- `sink`：列车完成本次路径后的汇点弧。

`rolling_optimizer.evaluate_schedule()` 在传入 `ResourceModel` 时会先构建候选方案的时空网络，并在评分中记录 `time_space_node_count` 和 `time_space_arc_count`。`run_dispatch_case.py` 会把优化方案导出为：
- `time_space_nodes.csv`
- `time_space_arcs.csv`
- `time_space_paths.csv`

其中 `time_space_paths.csv` 的 `arrival_time_s` / `run_time_s` 表示到达干线终点的时刻和运行时间；`completion_time_s` / `completion_duration_s` 表示继续完成终点装卸、取送车、解体及虚拟车底衔接后的路径完成时刻和总历时。终点技术作业不会被混入干线到达时间。

这一步已经把当前 Heavy/Empty 发车方案从单纯的发车时刻列表升级为可追踪的节点-弧段网络表达，并把原先粗粒度的技术作业进一步拆成等待、送车/对位、装卸、取车、拆解和虚拟车底等活动弧。但需要注意：当前搜索基因仍是低维的发车间隔、相位和等待时间模板；完整的网络流优化，即直接在运行弧、等待弧、装卸弧、虚拟车底弧上选择路径和流量，是下一阶段的优化器升级方向。

## 7. 扰动场景鲁棒评价

调度方案会在多个扰动场景下进行评价。

当前默认场景包括：

- 正常运行
- 重车晚点
- 空车晚点

后续可扩展场景包括：

- 临时限速
- 雨雪天气导致轮轨黏着力下降
- 牵引能力下降
- 制动能力下降
- 储能装置 SOC 异常
- 区间或车站临时封锁

优化器同时考虑平均成本和最坏场景成本，从而避免只在理想条件下节能、但在扰动条件下表现不稳定的调度方案。

## 8. MPC 滚动优化

项目在 `rolling_optimizer.py` 中实现了 MPC 思路的滚动优化框架。

基本流程：

1. 读取当前时间、已锁定发车、列车晚点和系统状态。
2. 优化未来一段时间窗口，例如未来 2 小时。
3. 只执行近期窗口，例如未来 10 分钟内的发车。
4. 将已执行或已承诺的发车锁定。
5. 时间窗口向前滚动。
6. 根据最新状态重新优化。

这种方式比“一天只计算一次静态时刻表”更接近真实调度场景。

滚动优化适合处理：

- 实时晚点恢复
- 短时重空能量匹配
- 空车发车动态调整
- 储能状态驱动的调度修正
- 未来接入调度指令系统

## 9. 性能优化

当前项目已经加入两类性能优化。

第一，时间桶能量结算：

- 能量结算可按 10s 或 30s 时间桶聚合。
- 减少滚动优化中大量候选方案的评价时间。

第二，功率序列缓存与降采样：

- 每类列车只进行一次基础仿真。
- 功率、位置、速度和供电区间占比均进行缓存。
- 对不同时间步长的降采样序列进行缓存。
- 候选发车方案只需要平移缓存序列。
- 进程级缓存采用有界 LRU（默认最多 64 个轨迹），并提供线程安全访问和淘汰计数；长时间运行的多场景服务不会因路线/天气/储能版本持续增加而无限保留完整轨迹。

当前测试中，10s 结算将一次滚动 NSGA-II 窗口评价从约 14.24s 降低到约 5.45s，示例结果保持一致。

## 9.1 工程化求解增强

当前优化器已经加入面向工程运行的求解控制项，不再只停留在原始虚拟 NSGA-II/MPC 原型。

能量结算增强包括：

- 储能初始 SOC
- 日终目标 SOC
- 日终 SOC 容许偏差
- SOC 偏差惩罚
- 弃电惩罚

这些约束可以避免优化器选择“看起来成本低、但日终电池被放空”或“因为储能折旧而倾向弃电”的方案。默认不启用这些惩罚时，模型仍与原有实验保持兼容。

搜索与评估增强包括：

- `TemplateSearchConfig.parallel_workers` 支持候选模板批量评估 worker 数配置。
- `batch_evaluate_templates` 按确定顺序评估候选模板，并验证并行评估不会改变目标函数结果。
- `run_engineering_solver_experiments.py` 运行 SOC/弃电惩罚优化、大窗口 MPC 压力测试和候选批量评估基准。

工程化实验输出位于 `outputs/engineering_solver`：

- `engineering_solver_comparison.csv`
- `large_window_mpc_stress.csv`
- `batch_evaluation_benchmark.csv`
- `ENGINEERING_SOLVER_REPORT.md`
- `engineering_cost_comparison.png`
- `batch_evaluation_benchmark.png`

## 10. 当前验证状态

以下脚本已成功运行：

- `python sandbox_data.py`
- `python train_simulator.py`
- `python energy_settlement.py`
- `python rolling_optimizer.py`
- `python tests/legacy/verify_data_ingestion.py`
- `python tests/smoke/verify_time_space_network.py`
- `python run_dispatch_case.py --input sandbox_config.json --output-dir outputs\\dispatch_case`
- `python tests/legacy/verify_dispatch_pipeline.py`
- `python data_ingestion.py validate data_templates\\shuohuang_virtual`
- `python data_ingestion.py export-json data_templates\\shuohuang_virtual --output ...`
- `python -m py_compile ...`

已验证能力包括：

- 虚拟线路生成
- 重车正向运行仿真
- 空车反向运行仿真
- 柔性供电区间受限能量结算
- 储能充放电核算
- 弃电和电网购电核算
- 混合闭塞安全检查
- 低维 NSGA-II 策略优化
- MPC 滚动调度
- 扰动场景鲁棒评价
- 降采样快速结算
- 储能初始 SOC 与日终 SOC 惩罚结算
- 弃电惩罚结算
- 工程化 MPC 大窗口压力测试
- 确定性的候选模板批量评估
- 站场/区间资源冲突检测
- 冲突解释 CSV/JSON/时间图输出
- 带资源模型的 MPC 可行性验证
- 真实数据 CSV/JSON 接入模板
- 结构化数据校验报告
- 从真实数据目录导出兼容原仿真的配置文件
- 一键式调度案例运行管线
- 基准方案与优化方案 KPI 对比报告
- 列车运行图、能量流、SOC、成本和资源冲突图表
- 历史朔黄线 `data/real_partial` 数据目录校验：`errors=0`，`warnings=0`（不代表当前正式数据已齐备）
- 朔黄线 2+2 调度烟测：调度可行，资源冲突数为 0
- 报告生成可输出数据来源、储能规划假设、空车质量占位和资源启发式说明

## 10.1 运行条件物理约束

当前原型已经加入低黏着、天气和临时限速的物理约束，不再只用“成本倍率”或“发车间隔拉伸”代理低黏着影响。

已实现能力如下：

- `operating_conditions.py` 定义天气规则、显式低黏着区和临时限速规则，均支持里程区间和时间窗口。
- `train_simulator.py` 在逐秒仿真中读取运行条件。
- 天气可降低轮轨黏着系数，并提高滚动阻力和气动阻力。
- 临时限速会替代全线最高速度，列车按车长采样点中的最严格限速运行。
- 黏着系数会限制可用牵引力和可用制动力。
- 仿真器加入前方限速预瞄，列车会在进入更低限速区前提前制动。
- `scheduler_nsga2.py` 的移动闭塞安全距离会读取黏着受限后的可用制动减速度。
- 时间相关的天气和临时限速按实际发车时刻生效，因此不同发车时刻的列车可能遇到不同运行条件。
- `tests/legacy/verify_operating_constraints.py` 会对比晴天基准和低黏着/雨天/临时限速场景，并输出到 `outputs/operating_constraints`。

当前虚拟压力场景包括山岭区雨天、柔性供电区湿轨低黏着，以及滴流磴至小觉方向的 80 km/h 临时限速。最新验证中，重车在该场景下最小黏着系数降至 `0.08`，最小限速降至 `80 km/h`，运行时间增加，移动闭塞最小安全发车间隔由 `3 min` 增至 `4 min`。这说明低黏着已经进入列车动力学和安全距离计算，而不是只影响经济成本。

## 11. 已知局限

当前模型已经接入一部分 PDF 真实数据，但仍是混合数据原型。

缺少的真实数据包括：

- 真实线路坡度和曲线数据
- 更完整的区间里程、道岔里程和站内限速映射
- 真实闭塞分区边界
- 真实站场咽喉和道岔约束
- 正式运行图
- 每日实际开行列车数量和车流结构
- 真实牵引/制动曲线
- 再生制动效率
- 柔性牵引供电设备参数
- 储能装置容量、功率上限和控制策略
- 实际晚点、限速和天气扰动统计

当前简化假设包括：

- 列车模型为多分段等效模型，不是完整纵向动力学模型。
- 未模拟车钩力、纵向冲动和制动波传播。
- 已建立虚拟站场/区间资源约束和冲突解释，但真实联锁、道岔拓扑、进路锁闭和站场能力仍需正式数据替换。
- 柔性供电能力以区间占用比例近似表示。
- 储能模型已加入最大充放电功率约束，但当前数值是规划/敏感性假设，不是已投运设备实测值。
- 信号与资源模型仍为简化容量模型，尚未接入真实闭塞、联锁、进路锁闭和站场拓扑数据。
- 空车质量不是固定真实常数，当前默认值只代表一种返程场景，应通过敏感性分析覆盖空车、轻载或混编情况。

## 12. 真实数据接入计划

后续获得更多正式数据后，建议按以下顺序替换和校准。

第一，补齐线路数据：

- 区间坡度
- 曲线半径
- 完整区段限速
- 道岔号至里程映射
- 长大下坡真实边界

第二，替换信号和资源数据：

- 闭塞分区边界
- 保护区段规则
- 站场联锁约束
- 咽喉能力
- 进路锁闭和到发线占用规则

第三，补齐列车数据：

- 编组类型
- 列车质量
- 列车长度
- 牵引曲线
- 制动曲线
- 再生制动效率
- 空车、轻载和混编返程质量范围

第四，替换供电与储能数据：

- 柔性牵引供电区间
- 变电所/供电臂边界
- 能量传输能力
- 储能容量和功率限制；若储能仍未实施，应继续作为规划情景处理

第五，替换运营数据：

- 每日开行列车数量
- 计划运行图
- 实际晚点记录
- 临时限速记录
- 列车任务、作业线、车型辆数与技术作业时间的对应关系

第六，重新校准目标函数权重和扰动场景参数。

### 12.1 真实数据输入接口

项目现在新增了 `data_ingestion.py`，用于把真实工程资料整理成当前仿真和优化器可直接使用的数据对象。

输入文件包括：

- `route_metadata.json`：线路总长、最高速度、长大下坡范围和信号默认参数
- `stations.csv`：车站名称和里程
- `segments.csv`：按里程划分的线路几何数据，包括坡度、曲线半径、地形和可选静态限速
- `energy_transfer_zones.csv`：柔性牵引供电/再生制动能量传输区间
- `signaling_blocks.csv`：真实或虚拟闭塞分区边界、方向、闭塞类型和单线标记
- `station_resources.csv`：车站股道容量和咽喉容量
- `trains.csv`：重车和空车参数
- `battery.json`：储能容量、功率上限、效率、折旧成本和购电价格
- `operating_conditions.json`：天气、低黏着区和临时限速
- `resource_config.json`：站场/区间资源模型默认参数
- `headway_constraints.csv`：PDF 追踪间隔和站间隔候选，当前朔黄线 2 万吨 15 min 已用于最小发车间隔
- `technical_operation_times.csv`：PDF 技术作业时间候选
- `station_operation_assignments.csv`：技术作业时间应用规则，避免将装卸作业时间套到所有通过列车

`train_simulator.load_config()` 现在既可以读取原来的 `sandbox_config.json`，也可以直接读取真实数据目录。
`load_real_data_bundle()` 会额外返回 `ResourceModel`，因此站场和区间能力数据可以直接接入滚动优化器。

当前生成的虚拟模板位于 `data_templates/shuohuang_virtual`。
它仍使用虚拟参数，但文件格式已经对齐未来真实数据接入方式。

历史基于 PDF 的朔黄线混合数据目录位于 `data/real_partial`；当前默认目录为 `data/real_shuohuang`。配套说明文件包括：

- `data/real_partial/REAL_PARTIAL_REPORT.md`
- `data/real_partial/FIELD_MAPPING.md`
- `data/real_partial/PDF_STATION_REORGANIZATION.md`
- `data/real_partial/STATION_OPERATION_ASSIGNMENTS.md`
- `data/real_data_summary.md`

### 12.2 数据校验层

`validate_real_data_bundle()` 会在数据进入仿真前进行结构化校验。

当前覆盖内容包括：

- 必需文件和必需字段
- 线路长度、速度和长大下坡范围
- 车站名称唯一性、里程顺序和线路范围
- 区间分段连续性、重叠、缺口和全线覆盖
- 坡度异常值提示
- 曲线半径和区间静态限速合理性
- 柔性供电区间范围
- 闭塞分区方向和重叠检查
- 站场资源引用和容量正值检查
- 列车名称、方向、质量、长度、Davis 阻力系数和黏着权重
- 储能容量、功率、效率和成本字段
- 运行条件的里程范围和速度合理性

`tests/legacy/verify_data_ingestion.py` 会导出模板、验证模板、构造故意错误的数据样例，并将 CSV/JSON 报告输出到 `outputs/data_ingestion`。

### 12.3 一键式调度案例管线

`run_dispatch_case.py` 提供端到端调度案例评估管线。
它既可以读取 `sandbox_config.json`，也可以读取真实数据输入目录。

管线流程如下：

1. 读取并校验输入数据。
2. 构建重车和空车功率缓存。
3. 生成保守的基准调度方案。
4. 运行滚动 NSGA-II 模板优化。
5. 对基准方案和优化方案分别进行信号、资源和能量约束评价。
6. 输出对比表、时间序列、图表和中文 Markdown 报告。

默认运行命令：

```bash
python run_dispatch_case.py --input sandbox_config.json --output-dir outputs\dispatch_case
```

主要输出包括：

- `summary.json`
- `DISPATCH_CASE_REPORT.md`
- `kpi_summary.csv`
- `kpi_comparison.csv`
- `baseline_schedule.csv`
- `optimized_schedule.csv`
- `energy_timeline.csv`
- `resource_conflicts.csv`
- `timetable.png`
- `energy_flow_baseline.png`
- `energy_flow_optimized.png`
- `soc_curve.png`
- `cost_comparison.png`
- `resource_conflict_timeline.png`

`tests/legacy/verify_dispatch_pipeline.py` 会分别使用 JSON 配置和真实数据目录模板运行完整管线。
该历史验证输出已归档到 `outputs/archive/2026-07-structure-convergence/dispatch_pipeline`。

## 13. 当前结论

当前项目已经形成较完整的算法原型，并完成了一轮 PDF 朔黄线真实数据的部分接入。

它可以支撑：

- 技术路线展示
- 算法可行性说明
- 虚拟场景和 PDF 部分真实数据混合场景实验
- Pareto 策略对比
- 滚动调度流程演示
- 后续真实工程数据替换
- 数据来源、占位参数和规划假设的可追溯说明

但它还不能被视为工程级真实调度系统。当前可用 PDF 数据已经覆盖站点、终点边界、部分速度、典型重车质量、追踪间隔和技术作业时间；仍需要在获得正式线路几何、列车动力学、信号闭塞、站场进路、供电、储能和运行图数据后，进行参数校准和真实场景验证。
