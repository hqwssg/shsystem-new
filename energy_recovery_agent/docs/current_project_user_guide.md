# 朔黄铁路重空协同与再生制动能量优化项目说明

更新时间：2026-09-03（项目优化与中文注释补足后）

本文面向刚接触项目的开发人员、项目负责人和业务人员，帮助读者理解当前项目的目标、范围、代码结构、数据、运行方式、结果含义和现实限制。本文描述的是当前仓库实际实现，不等同于未来完整的铁路低碳智能管理系统。

## 1. 一句话理解项目

项目通过模拟重载列车和空载列车在朔黄铁路主线上的运行，计算列车牵引、制动和再生能量，再尝试调整重车/空车发车时刻，使再生能量更多地被系统或储能设备利用，同时保证运行图、车流、站场、区间和电气约束不被破坏。

核心问题可以概括为：

```text
列车怎么跑，会产生多少牵引/再生能量？
再生能量有多少能够被接纳、储存和再次利用？
重车和空车怎样安排时刻，才能改善能量利用而不破坏运输组织？
```

## 2. 当前项目边界

### 2.1 项目负责的内容

当前算法只负责两类核心能力：

1. 再生制动能量回收能力分析；
2. 重车/空车列车调度与运行图优化。

具体包括：

- 列车运行轨迹和功率序列计算；
- 牵引能量、制动能量和再生能量计算；
- 按时间片、方向、供电臂进行能量结算；
- 储能容量、功率、效率和 SOC 约束；
- 弃电、电网购电、储能损失和终端 SOC 计算；
- 重车/空车发车时刻和相位优化；
- 运行图候选生成和 Pareto 候选筛选；
- 车流连续性、站场、咽喉、区间、追踪间隔和电气约束检查；
- 结果质量审计、测试、复现和输入输出追踪。

### 2.2 明确不负责的内容

以下内容不应继续塞入当前算法：

- 车载或地面能耗监测硬件；
- 20 Hz 运行状态采集设备；
- 实时列车位置、功率和 SOC 接口；
- 机车底层牵引/制动控制；
- 储能控制器和变流器控制；
- 信号联锁设备和现场安全认证；
- 生产调度指挥系统和控制指令下发；
- 完整碳排放管理平台；
- 通用 LSTM 预测和三维可视化平台；
- 储能设备选型、土建、电气设计和投资决策。

这些系统未来可以向算法提供数据，或使用算法输出，但不属于本项目当前交付物。

详细边界见：[algorithm_scope_and_deliverables.md](algorithm_scope_and_deliverables.md)。

## 3. 项目当前所处阶段

当前项目已经完成了较完整的算法原型和验证体系，但还没有完成正式工程数据接入。

可以将当前状态分成三层：

| 层次 | 当前状态 | 说明 |
| --- | --- | --- |
| 程序和算法 | 基本可运行、可回归 | 能量结算、调度、资源检查和结果审计已形成主流程 |
| 数据和参数 | 混合数据 | 部分线路资料真实，车辆、储能、电气和运行图仍有规划/占位值 |
| 工程结论 | 尚不能发布 | 当前结果只能用于流程验证、敏感性分析和候选比较 |

因此，“测试通过”表示代码逻辑和内部约束通过，不表示真实线路已经节能，也不表示储能容量已经确定。

## 4. 当前默认建模口径

### 4.1 线路范围

- 线路：朔黄铁路主线；
- 里程范围：K0–K583.003；
- 当前主集：约 33 个站点；
- 覆盖范围：线路图 1、2、3；
- 支线、联络线和非主线站点不参与当前主线模拟。

当前公里标主要按数值从小到大处理。若未来扩展到跨线或多线路，需要增加里程体系转换和接轨关系。

### 4.2 能量场景

当前默认场景是：

```text
storage_no_direct
```

含义：

- 上下行供电系统不进行直接互供；
- 同一供电臂、同一时间片的直接利用在默认主场景中关闭；
- 再生能量只能在允许的储能区段内充入储能；
- 无法被利用或吸收的再生能量计为弃电；
- 储能放电可向牵引侧供能；
- 储能效率、容量、功率和 SOC 影响最终结果。

历史文档中还保留了“可直发直用”等研究场景，但它们不是当前默认工程结论。

### 4.3 时间口径

结算步长默认是 10 秒。它只是把功率序列分桶结算的时间粒度，不是整个评价窗口长度。

项目会区分：

- 列车运行时间；
- 运行图评价窗口；
- 能量结算时间片；
- 储能充放电发生的时间顺序。

不能把 `settlement_step_s=10` 理解成“项目只评估 10 秒”。

## 5. 能量回收是怎么计算的

### 5.1 从列车运行到功率序列

列车仿真根据以下信息生成运行和功率数据：

- 列车质量；
- 列车长度和分段信息；
- 最大牵引力；
- 最大制动力；
- Davis 阻力参数；
- 坡度和曲线；
- 限速；
- 黏着系数；
- 运行方向；
- 运行图发车时间。

功率约定通常为：

- 正功率：牵引耗电；
- 负功率：制动产生再生能量。

### 5.2 能量结算顺序

每个时间片内，系统大致按以下顺序处理：

1. 汇总各列车在该时间片的牵引能量和再生能量；
2. 按供电臂、方向和储能区段隔离能量；
3. 判断是否允许直接利用；
4. 判断储能是否可充电；
5. 对储能容量和充电功率进行限制；
6. 对牵引需求使用已有储能放电；
7. 对未能利用的再生能量计为弃电；
8. 对剩余牵引需求计为电网供能；
9. 更新储能 SOC；
10. 检查能量守恒、SOC 边界和电气约束。

同一时间片内，刚刚产生的再生能量不能先充电、再在同一个时间片立即放电服务牵引，避免人为制造同桶循环利用。

### 5.3 能力回收的四个层次

项目把“能力回收”拆成四个层次：

| 层次 | 含义 |
| --- | --- |
| 理论再生能力 | 列车制动时理论上能够产生的再生能量/功率 |
| 供电可接纳能力 | 受供电臂、方向、时间和电气限值约束后能够被接纳的能量 |
| 储能可吸收能力 | 受容量、功率、效率和 SOC 约束后能够进入储能的能量 |
| 调度可实现回收能力 | 通过调整列车时刻后，实际增加的有效回收量 |

### 5.4 主要指标

- `total_gen_kwh`：理论再生能量总量；
- `direct_used_kwh`：直接利用能量，当前主场景为 0；
- `battery_charge_kwh`：储能输入侧充电量；
- `battery_discharge_kwh`：储能输出侧放电量；
- `wasted_kwh`：未被利用或吸收的再生能量；
- `grid_kwh`：仍需由电网提供的牵引能量；
- `accepted_by_power_arm_kwh`：经供电臂和时间匹配后被直接利用或送入储能的能量；
- `recovered_energy_kwh`：直接利用量加储能充电量乘储能效率；
- `recovery_rate`：有效回收量除以理论再生量；
- `effective_regen_loss_kwh`：弃电、储能损失和终端 SOC 影响折算后的综合损失；
- `energy_term`：当前优化使用的综合能量目标。

发电侧基本守恒关系为：

```text
total_gen_kwh = direct_used_kwh + battery_charge_kwh + wasted_kwh
```

用电侧基本守恒关系为：

```text
total_con_kwh = direct_used_kwh + battery_discharge_kwh + grid_kwh
```

“回收率”“弃电减少率”和“电网购电减少率”是三个不同指标，不能混用。

## 6. 列车调度算法是怎么工作的

### 6.1 输入

调度算法读取：

- 重车和空车类型；
- 列车数量；
- 发车间隔；
- 重空车相位；
- 运行图和站点到发时间；
- 运输任务和 OD；
- 站场与区间资源；
- 车流连续性和初始库存；
- 供电臂和储能配置；
- 列车功率缓存。

### 6.2 候选生成

候选方案可以通过以下方式产生：

- 整列车时间平移；
- 停站时间调整；
- 事件引导的局部重排；
- 重车/空车相位变化；
- 运行图局部调整；
- NSGA-II 的交叉、变异和筛选。

### 6.3 候选检查

每个候选会依次接受以下检查：

- 站点顺序和公里标方向；
- 到达时间不晚于出发时间；
- 同方向最小发车间隔；
- 信号和追踪间隔；
- 站场股道容量；
- 咽喉并发能力；
- 区间占用；
- 单线反向冲突；
- 同方向追越和运行顺序反转；
- 重车—空车—重车车流连续性；
- 供电臂和储能电气约束；
- 能量守恒和 SOC 边界。

不可行候选不会因为能耗目标好看而进入最终 Pareto 集。

### 6.4 多目标评价

当前候选通常同时考虑：

- 电网购电；
- 有效再生能量损失；
- 弃电；
- 运输任务完成情况；
- 延误和时刻调整量；
- 资源冲突；
- 车流连续性；
- 储能成本。

NSGA-II 输出的是一组互不支配候选，而不是天然唯一的“绝对最优方案”。项目还会输出候选解释文件，说明每个候选是 Pareto 方案、可行但被支配方案，还是不可行诊断方案。

## 7. 代码结构

### 7.1 推荐入口

`run_project.py` 是日常使用的统一入口。不要优先直接拼接多个底层脚本，除非是在调试某个模块。

### 7.2 核心模块

| 文件 | 作用 |
| --- | --- |
| `train_simulator.py` | 列车运行、动力学和功率序列基础逻辑 |
| `energy_settlement.py` | 多列车能量结算、储能和 SOC |
| `power_arm_lookup.py` | 根据公里标查询供电臂 |
| `power_arm_electrical_limits.py` | 供电臂电气能力和储能区段规则 |
| `time_space_network.py` | 节点—弧段时空网络结构 |
| `heavy_empty_network_optimizer.py` | 重空列双层时空网络和候选优化 |
| `rolling_optimizer.py` | 滚动优化、候选模板和场景评价 |
| `scheduler_nsga2.py` | 调度优化组件、功率缓存和信号约束 |
| `resource_constraints.py` | 站场、区间、咽喉、车流和作业资源检查 |
| `timetable_input.py` | 运行图模板读取和字段校验 |
| `timetable_energy_audit.py` | 运行图能量审查和时间片结算 |
| `timetable_optimizer.py` | 运行图候选生成、NSGA-II 和 Pareto 输出 |
| `run_dispatch_case.py` | 重空调度案例主流程和报告生成 |
| `data_ingestion.py` | 数据读取、状态标记和质量校验 |
| `data_quality_validator.py` | 项目级数据质量检查 |
| `real_data_ingestion_checker.py` | 新正式数据替换前的接入门禁 |
| `result_quality_audit.py` | 结果能量、SOC 和汇总一致性审计 |

### 7.3 工具目录

| 文件 | 作用 |
| --- | --- |
| `tools/run_ci_checks.py` | 本地 CI 式质量门禁 |
| `tools/run_all_smokes.py` | 运行当前 smoke 集合 |
| `tools/run_long_dispatch_tests.py` | 独立运行长耗时调度测试 |
| `tools/algorithm_consistency_checks.py` | 跨模块一致性检查 |
| `tools/algorithm_robustness_checks.py` | 极端、分辨率和复现检查 |
| `tools/algorithm_property_checks.py` | 属性和边界检查 |
| `tools/algorithm_extended_checks.py` | 扩展回归检查 |
| `tools/algorithm_validation_suite.py` | 综合算法验证 |
| `tools_energy_sensitivity_scan.py` | 参数敏感性和参数区间扫描 |
| `tools/official_data_readiness_pipeline.py` | 正式数据隔离验收和复跑 |
| `tools/project_hygiene.py` | 文件盘点和归档候选检查，只读 |

## 8. 数据目录

### 8.1 当前运行数据

`data/real_shuohuang/` 是默认运行数据目录。它不是纯正式数据，而是混合数据集，包括：

- 已审查线路资料；
- 自动生成的派生表；
- 规划参数；
- 虚拟预设；
- 尚未确认的工程假设。

### 8.2 来源数据

`data/source/` 保存算法使用的已整理来源表，通常按以下类别组织：

- `geometry/`：线路几何和坡度曲线；
- `power_arm/`：供电臂资料；
- `smart_meter/`：智能电表资料。

### 8.3 模板数据

`data_templates/` 保存运行图、重空运输任务和正式数据接入模板。

### 8.4 正式数据暂存区

`data/official_inbox/` 用于接收甲方正式数据，不能直接覆盖当前运行数据。正式数据应先经过文件、来源、字段、物理范围和 SHA-256 检查，再重建运行目录。

## 9. 一次完整运行怎么做

### 9.1 最常用的一键仿真

在项目根目录运行：

```powershell
python run_project.py simulate
```

主要流程：

1. 校验输入数据；
2. 抽取智能电表代表样本；
3. 对齐样本和线路运行弧；
4. 审查运行图能量问题；
5. 优化运行图候选；
6. 运行重空列调度仿真；
7. 输出基线、优化结果、能量账本和报告；
8. 写入运行 manifest。

### 9.2 单独运行模块

```powershell
python run_project.py validate-data
python run_project.py audit-timetable
python run_project.py optimize-timetable
python run_project.py dispatch-case
python run_project.py experiment-suite
python run_project.py check-ingestion
python run_project.py check-results --output-root outputs
```

### 9.3 运行测试

快速编译和 CI：

```powershell
python tools/compile_project.py
python tools/run_ci_checks.py
```

完整 smoke：

```powershell
python run_project.py smoke
```

长耗时调度测试：

```powershell
python tools/run_long_dispatch_tests.py
```

单独运行某个长测试：

```powershell
python tools/run_long_dispatch_tests.py --test heavy_empty_network
python tools/run_long_dispatch_tests.py --test rolling_optimizer
```

参数区间测试：

```powershell
python tools_energy_sensitivity_scan.py --only-interval --output-dir outputs/parameter_interval_scan
```

## 10. 输出文件怎么读

### 10.1 当前端到端报告

[outputs/SIMULATION_TEST_REPORT.md](../outputs/SIMULATION_TEST_REPORT.md)

用于快速了解最近一次端到端仿真的总体结果，包括数据校验、样本对齐、运行图问题、Pareto 数量和调度可行性。

### 10.2 数据质量

目录：[outputs/data_quality_validation](../outputs/data_quality_validation)

重点查看：

- `data_quality_summary.json`；
- `DATA_QUALITY_REPORT.md`；
- `data_quality_issues.csv`。

`valid=true` 且 `error_count=0` 只表示输入能够通过当前质量门禁；警告仍可能限制工程解释。

### 10.3 调度输出

目录：[outputs/dispatch_storage_no_direct_phase2600](../outputs/dispatch_storage_no_direct_phase2600)

重点文件：

- `summary.json`：完整输入、场景、基线和优化摘要；
- `kpi_summary.csv`：基线和优化 KPI；
- `kpi_comparison.csv`：差异和百分比；
- `energy_timeline.csv`：时间桶级能量和 SOC；
- `ranked_candidates.csv`：候选排序；
- `pareto_candidates.csv`：非支配候选；
- `selected_plan_scenario_diagnostics.csv`：选定方案的场景诊断；
- `resource_conflicts.csv`：资源冲突；
- `flow_continuity_violations.csv`：车流连续性问题。

### 10.4 运行图输出

目录：[outputs/timetable_energy_audit](../outputs/timetable_energy_audit) 和 [outputs/timetable_optimizer_nsga2](../outputs/timetable_optimizer_nsga2)。

重点查看：

- `audit_summary.json`；
- `audit_issues.csv`；
- `candidate_summary.csv`；
- `candidate_scenario_scores.csv`；
- `candidate_explanations.csv`；
- `pareto_candidates.csv`；
- `TIMETABLE_OPTIMIZATION_REPORT.md`。

### 10.5 运行清单

目录：[outputs/run_manifests](../outputs/run_manifests)。

每次统一入口运行都会记录：

- 原始命令和参数；
- 输入文件清单和 SHA-256；
- Python 和依赖版本；
- 代码快照摘要；
- 数据质量状态；
- 输出文件清单；
- 返回码和最终状态。

复核结果时，应先检查 manifest 是否 `status=success` 且 `return_code=0`，再查看 KPI。

## 11. 当前数据缺口和影响

| 数据 | 当前状态 | 影响 |
| --- | --- | --- |
| 正式运行图 | 尚未提供，使用模板/拟真运行图 | 不能代表真实运输组织方案 |
| 车辆牵引/制动/Davis 参数 | 部分为工程占位 | 不能发布正式能耗或节能率 |
| 供电臂真实电气能力 | 部分为大默认值 | 不能确认真实吸收瓶颈 |
| 储能参数和位置 | 规划值/敏感性参数 | 不能做正式容量和收益结论 |
| 闭塞分区和信号能力 | 主集不完整 | 资源可行性仍部分启发式 |
| 初始车流库存 | 场景假设 | 车流连续性不能作为现场证明 |
| 电表校准数据 | 有实验样本，但拟合误差较高 | 不能视为正式车辆能耗标定 |

历史实验校准资料为 532 个样本、178 个鲁棒拟合核心样本，校准默认关闭。2026-09-04 按新增独立留出质量门禁重跑后未通过：代表样本仅形成 13 条拟合和 3 条验证记录，且校准后留出误差没有改善，因此没有发布新系数。

## 12. 参数区间测试现状

为避免等待单点正式参数，项目已支持对规划值做区间角点评估，当前默认覆盖：

- 储能容量 ±20%；
- 充电功率 ±20%；
- 放电功率 ±20%；
- 往返效率 ±0.05。

当前区间扫描发现，5 个角点都受到同一个拟真运行图资源冲突影响，因此报告结论为：

```text
blocked_by_baseline_resource_infeasibility
```

这不能解释为储能参数本身不鲁棒。应先确认运行图模板的资源冲突，再分析参数区间下的调度和能量稳定性。

## 13. 测试和质量现状

当前已经有多层测试：

- 单元/专项 smoke；
- 能量守恒和 SOC 不变量；
- 多储能设备；
- 供电臂和方向边界；
- 重空网络；
- 运行图资源冲突；
- 算法一致性；
- 算法鲁棒性；
- 随机属性；
- 扩展回归；
- 性能容量；
- 正式数据接入门禁；
- 结果质量审计。

当前统一 CI 和项目编译检查通过，具体检查数量与逐项结果以最新 `ci_summary.json` 为准。当前有效源码的模块、类和函数已补充中文功能说明；长耗时测试已经拆分，可独立查看，不应因为某一个测试耗时长就把全部测试判断为失败。

## 14. 如何判断一个结果能不能用于汇报

建议按以下顺序判断：

1. 查看运行 manifest，确认命令、输入和代码快照；
2. 查看数据质量报告，区分 error 和 warning；
3. 查看是否使用了 `official`、`derived_from_official` 还是占位数据；
4. 查看基线和优化是否使用相同储能、车辆和评价窗口；
5. 查看 `feasible`、资源冲突、车流连续性和电气约束；
6. 查看能量守恒和 SOC 审计；
7. 查看回收率的统计口径和侧别；
8. 检查结果是否被正式数据门禁接受。

当前默认结果最多适合表述为：

> 在当前混合数据和明确规划假设下，算法流程能够运行，候选方案满足当前模型约束，并可比较能量和调度指标。

不应表述为：

> 朔黄铁路已经实现某个确定节能率、储能容量或投资收益。

## 14.1 当前优化收口状态

在正式车辆、供电、储能、运行图和闭塞数据到位前，当前项目中不依赖真实单点参数的优化已经基本收口，包括数据门禁、能量结算、SOC 约束、运行图资源检查、候选可解释性、鲁棒性测试、结果审计和中文代码说明。继续调整车辆或储能数值会变成无依据的参数拟合，因此暂不进行。

## 15. 正式数据到位后的工作流程

### 第一步：接收和登记

将数据放入 `data/official_inbox/`，保留原始文件，并登记：

- 来源单位；
- 文件版本；
- 生效日期；
- 字段说明；
- 单位和方向编码；
- 责任人；
- SHA-256。

### 第二步：阶段 A 最小正式包

优先接收：

1. 正式运行图；
2. Heavy/Empty 车辆动力学参数；
3. 供电臂边界和电气能力；
4. 储能参数和接入区段。

阶段 A 即可开展正式线路、车辆和能量回收的第一轮验证。

### 第三步：接入门禁

执行：

```powershell
python run_project.py accept-official-data --data-dir <正式数据目录> --source-dir <正式来源目录> --timetable <正式运行图>
```

### 第四步：重建和复跑

通过门禁后：

```powershell
python run_project.py validate-data --data-dir <正式数据目录>
python run_project.py simulate --data-dir <正式数据目录>
python run_project.py check-results --output-root <输出目录>
```

### 第五步：工程结果复核

至少检查：

- 正式运行图能否复现；
- 车辆参数来源和适用范围；
- 供电臂能力是否真实；
- 储能 SOC 和功率是否合理；
- 资源和信号约束是否完整；
- 能量账本是否守恒；
- 多次固定种子运行是否稳定；
- 基线和优化方案是否可公平比较。

## 16. 当前建议的使用方式

如果你是第一次接触项目，建议按以下顺序阅读：

1. 本文；
2. [algorithm_scope_and_deliverables.md](algorithm_scope_and_deliverables.md)；
3. [current_project_status_and_io.md](current_project_status_and_io.md)；
4. [algorithm_core_implementation.md](algorithm_core_implementation.md)；
5. [heavy_empty_network_optimizer.md](heavy_empty_network_optimizer.md)；
6. [timetable_optimizer.md](timetable_optimizer.md)；
7. [minimal_official_data_package.md](minimal_official_data_package.md)；
8. [current_algorithm_validity_boundary.md](current_algorithm_validity_boundary.md)。

如果只想运行一次完整流程：

```powershell
python run_project.py simulate
```

如果只想理解能量结算：先看 `energy_settlement.py` 和 `tests/smoke/verify_energy_settlement_correctness.py`。

如果只想理解调度：先看 `rolling_optimizer.py`、`heavy_empty_network_optimizer.py`、`resource_constraints.py` 和 `timetable_optimizer.py`。

## 17. 当前最重要的结论

项目现在不是“没有算法、等待数据才能开始”，也不是“已经可以发布真实节能结论”。准确定位是：

> 算法和验证体系已经基本成型，当前数据和工程约束仍不足以支撑正式结论；下一阶段应优先接入最小正式数据包，并用现有的门禁、仿真、审计和回归体系完成验证。

相关总览入口：[project_complete_guide.md](project_complete_guide.md)。
