# 朔黄铁路重空协同与再生制动能量优化项目完整说明

**文档版本：** v1.1  
**更新时间：** 2026-09-08  
**项目目录：** `D:\dev\project\energy_retry`  
**阅读对象：** 项目负责人、算法开发人员、数据提供方、测试人员和论文作者

本文是项目的恢复/交接文档。即使读者较长时间没有关注项目，也应能通过本文了解项目的研究目标、技术范围、代码结构、数据来源、运行方法、输出含义、测试证据、已修复问题、当前限制和下一步工作。本文以当前代码、文档和已生成报告为准；历史技术方案中已经废弃或仅作背景的口径会明确注明。

---

## 1. 先看结论

项目当前已经不是只有概念的方案，而是一个可以运行的运输组织与能量协同算法原型，配套有统一命令行入口、数据校验、结果审计、正式数据验收、回归测试、性能分析、原型界面和运行追溯机制。

但是，项目还没有达到“使用正式现场数据证明节能效果并可直接上线”的阶段。原因不是当前测试失败，而是若干关键工程数据仍缺失或属于规划/虚拟/启发式值，包括正式运行图、完整车辆动力学、供电臂真实电气能力、储能设备规格、闭塞与站场拓扑、初始车流库存等。因此当前结果的正确表述是：

> 算法程序和内部逻辑在已有合成/混合数据下通过了系统回归测试，可以用于方法验证、候选方案比较和敏感性分析；真实节能率、储能容量和经济收益必须等正式数据接入、校准和实测对比后才能报告。

### 当前成熟度概览

| 方面 | 状态 | 含义 |
|---|---|---|
| 算法程序完整性 | 较高 | 主要运输组织和能量协同模块已经串联运行 |
| 内部逻辑稳定性 | 较高 | 当前有101个 smoke 脚本；正式发布执行96项短测和7项带性能门禁的长测，数据库分角色五类任务另行验收 |
| 数据工程化 | 较高 | 有来源状态、清单、哈希、验收和审计机制 |
| 物理参数真实性 | 不足 | 关键车辆、电气、储能参数仍有占位 |
| 正式节能结论 | 尚不可出 | 尚未完成正式参数校准和现场实测对比 |
| 生产实时系统 | 未实现 | 当前没有接入现场实时位置、功率、SOC 和控制下发 |

---

## 2. 项目背景和要解决的问题

朔黄铁路是重载运输场景。重车和空车通常在相反方向运行：重车在部分下坡区段可能产生再生制动能量，空车或其他列车在不同时间和空间位置需要牵引能量。如果两者不在同一供电边界内、时间上不匹配，或者储能容量/功率不足，再生能量就会被弃用。

项目要解决的不是单列车如何控制牵引手柄，而是运输组织层面的协同问题：

1. 哪些重车和空车运行任务可以同时安排；
2. 如何调整发车时刻、相位、停站和作业时间，使运输任务、运行安全和站场资源同时可行；
3. 再生制动能量在供电臂、时间片和储能边界下能利用多少；
4. 在不牺牲运输能力的条件下，如何减少电网购电和再生能量弃用；
5. 如何把候选方案、输入版本、结果质量和数据可信度记录下来，避免虚拟参数被误当成正式结论。

### 与原技术方案的关系

早期技术方案还讨论了 RHONN、NSMC、EKF/UKF、DC-DC 变换器动态控制等单列车底层控制内容。当前项目没有实现这些控制器，也没有把它们作为运输组织优化的必要前置条件。当前项目对应技术方案中的“重空协同调度、运行图优化、再生能量结算和储能利用”部分。

---

## 3. 实现范围和不实现范围

### 3.1 当前实现范围

- 朔黄主线运输组织侧的重车/空车协同；
- 列车长度感知的多分段运行仿真；
- 坡度、曲线、限速和供电臂边界读取；
- 牵引能耗和再生制动能量估算；
- 按供电臂和时间片进行能量结算；
- 储能容量、功率、效率和 SOC 约束；
- 电网购电、储能充放电、直接利用和弃电统计；
- 站场、区间、咽喉、股道、技术作业和追踪间隔约束原型；
- 重空双层时空网络和候选方案搜索；
- 运行图能量审查和 NSGA-II 候选优化；
- 智能电表样本匹配、聚合和实验校准；
- 正式数据严格验收、结果质量审计和可复现运行清单。

### 3.2 当前不实现的内容

- 机车底层实时牵引/制动控制器；
- RHONN、NSMC 等控制策略的现场闭环部署；
- EKF/UKF 车辆状态估计；
- DC-DC 变换器开关级动态控制；
- 现场信号设备、联锁和列控系统控制；
- 实时列车位置、功率、SOC 数据流的生产接口；
- 自动向调度系统下发运行图或控制指令；
- 现场储能保护、故障切除和设备级控制。

这些内容不是“测试没通过”，而是当前项目边界之外的系统工程工作。

---

## 4. 当前默认口径和重要假设

### 4.1 线路范围

当前默认数据目录为 `data/real_shuohuang/`，建模主线范围约为 K0–K583.003，当前主集为 33 个站点。历史文档中的 594 km、K589+196 和长大下坡 62–302 km 等数值属于早期虚拟/历史口径，不应覆盖当前默认数据。

当前公里标按数值从小到大处理，暂不区分裸 `K`、`黄K`、`朔黄K`、`神朔K`、`准池K` 等前缀。该做法适用于当前主线原型；若将来扩展到支线或跨线运行，需要加入里程换算和接轨关系。

### 4.2 能量场景

当前主场景为 `storage_no_direct`：

- 上下行供电相互隔离；
- 不假设上下行再生能量可以直接跨方向互供；
- 再生能量只能在允许的供电臂/储能区段内进入储能；
- 无法利用的再生能量计为 `wasted_kwh`；
- 牵引需求不足以由可用能量覆盖的部分计为 `grid_kwh`。

历史上讨论过的 `direct_no_storage`、`direct_with_storage` 等场景仍可在底层模块中作为研究假设存在，但不作为当前默认工程结果。`auto` 是兼容入口，当前等价于 `storage_no_direct`。

### 4.3 时间口径

- `settlement_step_s`/`settlement_time_step_s` 是能量结算离散步长，默认 10 秒；
- 结算步长不等于整个仿真的评价总时长；
- 运行图评价时长由列车轨迹、作业尾段和场景时域派生；
- 历史曾出现将正式运行图 10 秒结算静默变为 900 秒的问题，已修复并加入回归测试。

### 4.4 校准口径

智能电表校准系数默认 `enabled_by_default=false`。这意味着当前默认仿真不会自动把实验校准系数混入优化器物理结果。校准工具可用于样本分析、误差评估和敏感性比较。

---

## 5. 系统架构和代码地图

### 5.1 推荐入口

`run_project.py` 是统一命令行入口。底层脚本仍保留用于单模块调试和复现，但日常操作优先使用统一入口。

### 5.2 核心算法模块

| 文件 | 作用 | 在流程中的位置 |
|---|---|---|
| `train_simulator.py` | 列车位置、速度、牵引/制动和能耗估算 | 单列车物理层 |
| `energy_settlement.py` | 发电、牵引、储能、弃电和电网结算 | 能量层 |
| `power_arm_lookup.py` | 按里程和方向查找供电臂 | 边界识别 |
| `power_arm_electrical_limits.py` | 供电臂能力、回馈和储能规则 | 电气约束 |
| `time_space_network.py` | 节点和运行/作业弧 | 时空网络基础 |
| `heavy_empty_network_optimizer.py` | 重空双层网络优化 | 重空协同 |
| `resource_constraints.py` | 区间、站场、咽喉和技术作业约束 | 可行性检查 |
| `exact_resource_feasibility.py` | 精确资源可行性证明及运行图偏移词典序优化 | 启发式验证与补解 |
| `tools/small_scale_optimality_gap_benchmark.py` | 2/4/6列车有限域穷举与三档NSGA-II对比 | E12最优性差距基准 |
| `rolling_optimizer.py` | 滚动候选和约束处理 | 候选搜索辅助 |
| `scheduler_nsga2.py` | 多目标排序和 NSGA-II 组件 | 运行图/调度优化 |
| `timetable_input.py` | 运行图模板读取和字段校验 | 运行图输入 |
| `timetable_energy_audit.py` | 运行图能量风险和时间片审查 | 运行图审查 |
| `timetable_optimizer.py` | 运行图候选生成和 Pareto 优化 | 运行图优化 |

### 5.3 数据和质量模块

| 文件 | 作用 |
|---|---|
| `data_quality_validator.py` | 数据字段、范围、来源和结构校验 |
| `real_data_ingestion_checker.py` | 新交付数据接入检查 |
| `formal_data_acceptance.py` | 严格正式数据门禁 |
| `result_quality_audit.py` | 输出守恒、SOC 和结果结构审计 |
| `run_manifest.py` | 运行参数、哈希、环境和返回码记录 |
| `smart_meter_adapter.py` | 电表字段适配和读取 |
| `smart_meter_time_matcher.py` | 电表和列车时间窗口匹配 |
| `smart_meter_representative_sampler.py` | 代表性样本筛选 |
| `energy_calibration_alignment.py` | 样本与线路弧对齐 |

### 5.4 工具目录

`tools/` 中的主要工具包括：

- `build_real_shuohuang_dataset.py`：从审查后的 `data/source/` 重建运行数据；
- `official_data_readiness_pipeline.py`：正式数据只读验收、隔离仿真和 KPI 对比；
- `synthetic_scenario_matrix.py`：合成场景矩阵；
- `synthetic_regression_baseline.py`：合成回归指纹基线；
- `run_ci_checks.py`：本地 CI 门禁；
- `compile_project.py`：只编译项目源码、工具和测试；
- `performance_analysis.py`：cProfile 性能分析；
- `performance_capacity_analysis.py`：性能/容量基线；
- `project_hygiene.py` 和 `archive_project_candidates.py`：项目卫生盘点和可恢复归档；
- `validate_prototype_contract.py`：原型与后端契约校验；
- `sync_prototype_html.py`：同步原型独立预览页。

---

## 6. 数据目录和数据生命周期

### 6.1 目录用途

| 路径 | 用途 | 是否允许普通流程覆盖 |
|---|---|---|
| `data/source/` | 英文命名的审查后源表 | 否，需人工维护 |
| `data/real_shuohuang/` | 默认运行输入数据 | 否，只有显式重建才更新 |
| `data/real_partial/` | 历史兼容/追溯混合数据 | 不作为默认输入 |
| `data_templates/` | 运行图和正式数据空模板 | 否 |
| `data/official_inbox/` | 正式数据交付暂存区 | 由接入流程读取 |
| `outputs/` | 当前运行输出和报告 | 可生成新子目录 |
| `outputs/archive/` | 历史输出的可恢复归档 | 不删除 |
| `outputs/run_manifests/` | 每次运行追溯记录 | 不覆盖 |
| `tests/` | 回归测试和夹具 | 不修改 |

### 6.2 数据更新频率

| 层级 | 例子 | 谁维护 | 每次运行是否重新输入 |
|---|---|---|---|
| 固定基础资料 | 站点、坡度、曲线、线路元数据 | 专业管理员 | 否，程序自动读取 |
| 自动派生资料 | `segments.csv`、供电臂切分表、构建摘要 | 构建脚本 | 否，显式重建时更新 |
| 低频工程参数 | 车辆、储能、供电能力、资源配置 | 车辆/电气/设备负责人 | 否，按版本引用 |
| 低频业务模板 | 运行图、OD、作业规则 | 运输组织人员 | 选择版本，不逐项重填 |
| 高频状态 | 实时位置、功率、SOC、临时限速 | 生产系统 | 当前尚未接入 |
| 本次控制项 | 重空数量、相位、间隔、搜索规模 | 操作员/实验人员 | 是 |
| 校准派生结果 | 电表样本、校准系数 | 数据分析人员 | 否，审核后引用 |

### 6.3 数据状态标签

关键数据需要标记：

- `official`：正式来源；
- `derived_from_official`：由正式资料推导；
- `planning_placeholder`：规划占位；
- `virtual_preset`：虚拟预设；
- `experimental_kwh_calibration`：实验校准结果。

正式数据门禁要求关键运行字段不能仍以占位或虚拟状态参与正式结论。

---

## 7. 输入数据详解

### 7.1 线路元数据 `route_metadata.json`

主要字段包括线路总长、最高限速、信号制式、固定闭塞参数、移动闭塞参数和检查步长。它定义仿真边界和安全规则，不直接提供每一段的详细坡度。

### 7.2 车站 `stations.csv`

至少需要站点名称/ID、标准里程、站型和股道能力。站点用于到发时刻、站场资源、技术作业和结果报表。里程应严格递增且与运行图站点名称可关联。

### 7.3 区段几何 `segments.csv`、`gradients.csv`、`curves.csv`

典型字段为 `start_km`、`end_km`、`gradient_per_mille`、`curve_radius_m`、`terrain` 和 `speed_limit_kmh`。区间应从线路起点连续覆盖到终点，不能有空洞或重叠。坡度正负号必须明确：正向运行视角下的上坡/下坡定义必须和仿真约定一致。

### 7.4 车辆 `trains.csv`

典型字段为列车类型、质量、长度、最大牵引力、最大制动力、旋转质量系数、Davis 阻力参数、黏着参数和功率边界。当前质量部分有代表性资料，但牵引、制动、Davis 和黏着字段仍有虚拟或待确认项。

### 7.5 运行图和运输任务

运行图模板包含列车 ID、方向、站点到发时刻和作业信息。运输任务还需要重/空车标识、OD、车型、编组和任务类型。当前正式运行图尚未到位，模板只能支持算法流程和合成实验。

### 7.6 供电臂 `power_arm_intervals.csv`

需要供电臂起止里程、方向、牵引供电能力、再生吸收能力、上网规则、储能可用标记和储能区段 ID。当前供电臂边界已进入主线流程，但部分能力采用较大的非约束默认值，不能据此判断真实吸收瓶颈。

### 7.7 储能 `battery.json`

需要容量、最大充/放电功率、充放电或往返效率、初始 SOC、SOC 上下限、折旧成本、电价和接入位置。当前 K145–K164、K164–K200.7 两段储能覆盖属于规划假设，容量和效率仍不是现场设备参数。

### 7.8 资源和信号

需要闭塞分区、信号机、进路锁闭、站场股道、咽喉、区间通过能力、技术作业时间和初始重空车库存。当前项目已实现资源约束接口和启发式检查，但主数据中完整闭塞分区和站场拓扑仍缺失。

### 7.9 智能电表

需要原始时间戳、列车或设备标识、牵引电量、回馈电量、供电臂/站点标识、采样周期、时区和计量口径。现有分析表明 `58A+58B`、`151A+151B` 聚合比单表口径更合理，但样本覆盖和误差仍不足以作为最终工程定标。

---

## 8. 算法流程详解

### 8.1 列车运行模型

列车不是简单的单点。当前采用列车长度感知的多分段等效模型：以车头位置为主状态，把列车长度划分为多个纵向采样点，每个采样点分别读取坡度、曲线、限速、供电臂和储能区段属性，再合成列车总阻力、牵引需求和再生功率。这解决了长列车车头和车尾同时处于不同坡段时的明显误差。

反向列车按运行视角翻转坡度符号，因此同一物理线路段可能对正向重车表现为下坡，对反向空车表现为上坡。

### 8.2 能量结算

每个时间片和供电臂内，系统接收再生功率、牵引功率、能量传输比例、时间窗口和储能标签。结算受到供电臂牵引/回馈能力、储能容量、SOC、最大充放电功率和效率约束。

输出至少包括：

- `total_gen_kwh`：再生发电量；
- `total_con_kwh`：牵引用电量；
- `direct_used_kwh`：直接协同利用量；
- `battery_charge_kwh`：储能充电量；
- `battery_discharge_kwh`：储能放电量；
- `wasted_kwh`：弃电量；
- `grid_kwh`：电网购电量；
- `final_soc_kwh`：终端储能总 SOC；
- `final_soc_by_storage_kwh`：分设备终端 SOC。
- `initial_soc_by_storage_kwh`：分设备窗口初始 SOC；
- `battery_charge_by_storage_kwh` / `battery_discharge_by_storage_kwh`：分设备充放电量；
- `wasted_by_storage_kwh`：分设备储能区段内未吸收再生能量。
- `storage_parameters_by_id`：本次计算实际采用的逐设备容量、功率、双向效率、初始SOC、SOC上下限和静态投运状态。

结果质量审计会检查：

```text
total_gen = direct_used + battery_charge + wasted
total_con = direct_used + battery_discharge + grid
final_soc = sum(final_soc_by_storage)
```

对滚动调度结果，审计器还会检查每轮设备集合一致、逐设备额定参数有效、逐设备数值有限且非负、总SOC与逐设备SOC汇总一致、SOC位于数据库上下限内、跨轮SOC连续，以及静态或实时停运设备充放电量必须为零。正常运行和单设备停运的E15基准均已通过该审计。

上述关系是结果结构的基本守恒关系，不代表所有输入字段都已经具有现场真实性。

### 8.3 重空时空网络

网络节点由站点、时间和列车状态组成，弧包括出发、运行、停车、装卸、解编、取送、虚拟编组和终止。重车层和空车层通过库存、OD、作业和资源约束关联，候选路径必须满足运输任务和车流连续性。

### 8.4 运行图候选和多目标优化

以基准运行图为初值，对发车时刻、相位、停车/作业时长等允许变量施加扰动，先做硬约束检查，再计算能量、运输能力、延误、冲突和储能成本等目标。NSGA-II 组件生成候选和 Pareto 集；目标权重只影响候选排序，不应改变物理能量守恒。

### 8.5 电表校准

电表流程包括字段适配、时间窗口匹配、重叠区间排除、A/B 表聚合、站点和线路弧对齐、误差分析和分组系数生成。当前发布样本和实验系数属于实验性材料，默认不写入物理主流程。

---

## 9. 统一命令和典型操作

### 9.1 普通仿真

```powershell
python run_project.py simulate --data-dir data/real_shuohuang --output-root outputs
```

该命令不自动重建或覆盖输入数据。若确实要重建，必须显式添加 `--rebuild-data`，并确认目标目录。

### 9.2 单独模块

```powershell
python run_project.py dispatch-case
python run_project.py audit-timetable
python run_project.py optimize-timetable
python run_project.py experiment-suite
python run_project.py validate-data
python run_project.py check-ingestion
python run_project.py check-results --output-root outputs
```

### 9.3 正式数据验收

```powershell
python run_project.py accept-official-data \
  --data-dir <候选运行目录> \
  --source-dir <候选源目录> \
  --timetable <候选运行图> \
  --output-dir outputs/formal_data_acceptance
```

PowerShell 中也可以使用反引号换行。验收失败是阻断，不是降级通过。

### 9.4 正式数据就绪流水线

```powershell
python run_project.py official-data-readiness \
  --data-dir <候选运行目录> \
  --source-dir <候选源目录> \
  --timetable <正式运行图> \
  --output-dir outputs/official_readiness
```

默认只生成清单和验收报告。只有显式追加 `--run-simulation`，才会在输出目录下的隔离 `simulation/` 运行仿真；可用 `--baseline-output` 比较已有结果。该工具不提供隐式覆盖或发布操作。

### 9.5 质量和回归

```powershell
python tools/compile_project.py
python tools/run_ci_checks.py --output-dir outputs/ci_checks
python tools/synthetic_scenario_matrix.py --output-dir outputs/synthetic_scenario_matrix
python tools/synthetic_regression_baseline.py --output-dir outputs/synthetic_regression_baseline
python run_project.py smoke
```

完整 smoke 较耗时，最近一次实际耗时约 818.78 秒，即 13.6 分钟，不是几秒钟。

---

## 10. 输出目录和如何解读结果

| 输出 | 内容 | 注意事项 |
|---|---|---|
| `outputs/SIMULATION_TEST_REPORT.md` | 端到端流程摘要 | `valid=true` 只表示流程完成和结构有效 |
| `outputs/simulation_workflow_summary.json` | 各步骤机器可读摘要 | 用于自动汇总 |
| `outputs/dispatch_*/` | 基线、优化和候选调度结果 | 需结合数据状态解释 |
| `outputs/timetable_energy_audit/` | 运行图能量审查 | 当前运行图可能是模板 |
| `outputs/timetable_optimizer_nsga2/` | Pareto 候选和优化摘要 | 不是现场可执行证明 |
| `outputs/simulation_experiment_suite/` | 多场景和敏感性结果 | 合成/假设结果需标注 |
| `outputs/formal_data_acceptance/` | 正式数据门禁报告 | `accepted=false` 应阻断发布 |
| `outputs/result_quality_audit_full/` | 结果质量审计 | 只检查一致性，不验证物理参数来源 |
| `outputs/run_manifests/` | 运行命令、参数、哈希和环境 | 用于复现和审计 |
| `outputs/archive/` | 历史输出和开发痕迹归档 | 归档保留，不作为当前结果 |

看到一个结果时，必须同时查看：输入目录版本、`data_status`、运行清单、结果质量审计、是否有警告，以及结果是否来自合成/虚拟数据。不能只看一个节能率数字。

---

## 11. 测试证据和当前质量状态

### 11.1 全量 smoke

最近一次完整验证：

- 101个`tests/smoke/verify_*.py`脚本；
- 默认短耗时集合为94项，5个长耗时smoke与2个集成长测共同组成7项独立长测发布集合；
- 正式软件版本`2026.09.11.4`的93项短测和7项长测已全部通过；
- 最终文档状态收敛发布目标为`2026.09.11.5`，算法和平台接口语义不变；正式状态只以对应发布验收目录中的`release_acceptance_summary.json`为准。

覆盖列车仿真、能量结算、SOC、供电臂、重空网络、运行图优化、资源约束、电表匹配、输入防护、数据验收、结果审计、性能、原型契约和项目卫生。

### 11.2 独立门禁

- 项目编译：通过；
- 本地 CI：当前统一门禁通过，具体检查数量以最新 `ci_summary.json` 为准；
- 合成场景矩阵：9/9 通过；
- 合成回归基线：通过；
- 当前输出质量审计：0 错误、0 警告；
- 正式数据就绪流水线定向测试：通过。
- 运行准备度检查：实时输入契约、严格缺失数据阻断、能量来源追踪、manifest/schema 兼容和性能门禁全部通过。

### 11.3 性能

基础轻量性能基线约 2.1–2.8 秒，但默认命令没有真正改变算法规模，不能解释为规模扩展曲线。运行图优化 profile 约 32.5 秒，主要热点是候选评估、NSGA-II 和时间片能量审计。重空网络 smoke 是完整测试中最耗时的部分。

### 11.4 代码说明与当前优化收口

当前有效源码已补充中文模块、类和函数功能说明，并将关键算法分支统一为中文注释。项目编译和本地 CI 均已通过。现阶段不再依据虚拟参数继续调整车辆动力学、储能容量或供电能力；这些内容应在正式数据到位后统一替换、标定和复跑。

---

## 12. 已修复的真实问题

以下是已经确认会影响结果或流程可靠性的缺陷：

1. 正式运行图 10 秒结算被静默改成 900 秒；已恢复正确步长并回归验证。
2. 重空网络优化器重复计算下坡节能；已消除重复计入。
3. 同一时间桶内储能同时充放电处理不一致；已禁止新充入能量在同桶立即供牵引。
4. 多储能设备终端 SOC 汇总少算；已改为分设备汇总并审计总和。
5. 终点前约 2 m 的离散积分误差导致列车降为零速却无法判定到站；已加入 3 m 数值终点容差。
6. 合法 `length_km=0` 点质点列车在优化器缓存阶段被拒绝；已允许非负长度。
7. 零牵引力/零制动力曾在数据校验阶段放行，运行时才失败；已在输入校验阶段阻断。
8. 覆盖 `--baseline-phase-s` 时默认 dispatch 输出目录可能互相覆盖；已按相位生成隔离目录。
9. 项目卫生检查误把 `tools/__init__.py` 分类为临时工具；已修正分类。
10. 分批归档可能覆盖旧 manifest；已改为不覆盖并保留审计记录。
11. 独立原型 iframe `srcdoc` 引号错误；已修复并通过契约检查。
12. CI 的 `compileall .` 扫描 `.venv` 第三方包，导致 Python 3.9 误报；已改为只编译项目源码、工具和测试。

测试中出现的“注入图表失败”“未知 storage preset”等信息属于专门测试异常处理或预期警告，不是未修复的算法缺陷。

---

## 13. 当前已知限制和风险

### 13.1 数据真实性风险

车辆动力学、供电能力、储能设备和正式运行图尚未齐全，会影响绝对能耗和节能率。合成回归通过不能证明正式现场数据下的数值准确。

### 13.2 资源模型风险

完整闭塞分区、进路锁闭、咽喉能力和站场拓扑尚未全部接入，当前区间容量和部分资源检查仍为启发式原型。

### 13.3 电表校准风险

当前样本主要来自有限车组/电表组合，虽已完成 A/B 聚合和非零样本筛选，但实验拟合误差仍较高，校准系数默认关闭，不能作为最终定标。

### 13.4 优化器解释风险

多目标权重、搜索规模和随机种子会影响候选排序。Pareto 候选是算法输出，不代表唯一正确方案，也不代表已经获得业务审批。

### 13.5 实时性风险

当前工具是离线仿真/方案分析流程，不是经过现场接口和时限认证的实时调度系统。性能基线不应直接解释成生产系统响应时间。

---

## 14. 原型界面现状

原型文件：

- `prototypes/heavy-empty-coordination-ui.fragment.html`：可编辑源；
- `prototypes/heavy-empty-coordination-ui.html`：独立预览页。

原型已经体现以下数据分层：

- 固定基础数据引用；
- 低频工程配置模板；
- 本次运行控制项；
- 自动派生、只读的预测/执行/评价时域；
- 输入快照、版本和运行进度；
- 结果质量和数据可信状态。

当前页面是演示原型，不是生产界面。运行按钮只有在接入真实后端 API 后才会根据选项触发真实计算；当前不能把页面展示指标当作算法实际运行结果。

---

## 15. 论文和对外表述边界

### 当前可以支持

- 重空协同和能量结算模型设计；
- 时空网络和多目标优化方法；
- 合成数据下的正确性、边界和鲁棒性；
- 软件工程、数据验收和可复现性设计；
- 候选方案相对比较和敏感性趋势。

### 当前不能支持

- 正式线路实际节能率；
- 真实再生能量规模和弃能量；
- 储能最佳容量、功率和投资收益；
- 现场信号资源下的最终可执行性；
- 生产系统实时性能；
- 将虚拟/规划参数描述为现场实测值。

推荐论文定位是“面向重空协同与再生制动能量利用的调度优化方法及原型验证”，而不是“已完成现场节能效果评估”。

---

## 16. 正式数据到位后的标准流程

1. 将原始资料放入独立 `data/official_inbox/`，保留原始文件、来源、责任人、采集时间和版本。
2. 完成字段映射表，确认单位、时区、编码、里程基准和计量口径。
3. 文件复制和转换全部完成后，用 `create-official-data-marker` 生成文件数量、大小和 SHA-256 清单及最终到件标记。
4. 用 `official-data-auto-trigger` 单次检查或常驻监控；程序会先冻结输入快照，再执行严格验收。
5. 验收失败时修数据，不覆盖当前默认运行目录。
6. 验收通过后，自动触发器在隔离输出目录运行完整仿真。
7. 自动执行结果质量审计，检查能量守恒、SOC、资源冲突和汇总一致性；通过后再进入正式对比总控。
8. 与合成基线、历史基线和现行调度方案比较，解释所有关键差异。
9. 固定代码、输入、参数、随机种子、硬件和依赖，至少重复运行 3 次。
10. 由业务负责人和数据负责人审核后，才能形成正式节能、容量或收益结论。

---

## 17. 目前最适合继续做的算法工作

在正式数据到位前，不建议为了虚拟结果继续修改默认物理逻辑。可以继续做的高价值工作是：

- 模块间输入输出字段的一致性审查；
- 快速评价和精细评价的误差对比；
- 基线和消融实验，确认每个算法组件确实影响结果；
- 更多极端场景：无再生、零储能、满 SOC、功率降额、供电臂外运行、同时制动/牵引；
- 优化器随机种子复现、目标权重单调性和空候选处理；
- 大规模列车数量、时间片和候选规模的容量分析；
- 结果图表和异常样例的自动化生成；
- 正式数据字段映射和数据字典；
- 继续保持 CI、回归和结果质量审计通过。
- 在正式数据到位前，持续运行 `operational_readiness_checks`，确保实时契约和结果解释能力不回退。

---

## 18. 相关文档和阅读顺序

如果需要深入了解，建议按以下顺序阅读：

1. 本文；
2. `docs/current_project_status_and_io.md`：详细输入输出契约；
3. `docs/project/DATA_REQUIREMENTS.md`：字段级数据需求；
4. `docs/current_algorithm_validity_boundary.md`：可信边界；
5. `docs/official_data_intake_checklist.md`：正式数据门禁；
6. `docs/official_data_readiness_pipeline.md`：正式数据自动验收和隔离仿真；
7. `docs/official_data_auto_trigger.md`：正式数据到件标记、快照、幂等执行和状态账本；
8. `docs/synthetic_regression.md`：合成回归和场景矩阵；
9. `docs/performance_capacity.md`：性能/容量分析；
10. `docs/prototype_backend_contract.md`：原型和后端契约；
11. `docs/research/paper_data_requirements.md`、`docs/research/paper_draft_v0.md`：论文数据和初稿。
12. `docs/operational_readiness_checks.md`：实时接入前的契约、降级和性能门禁。

如需逐函数理解算法实现，先阅读 `docs/algorithm_core_implementation.md`，再按其中的源码阅读顺序查看核心模块。
如需核对具体函数参数、返回值和异常，再阅读 `docs/algorithm_api_reference.md`。
随机化属性、时间边界、方向对称、终端 SOC 和资源性质测试见 `docs/algorithm_property_checks.md`。
快速/精细误差、基线消融、优化稳定性、储能策略和性能验证见 `docs/algorithm_validation_suite.md`。

---

## 19. 一页式恢复清单

如果项目中断很久后重新接手，按下面顺序即可恢复：

```powershell
# 1. 查看项目和命令
Get-Content docs/project_complete_guide.md
python run_project.py --help

# 2. 验证源码和工程门禁
python tools/compile_project.py
python tools/run_ci_checks.py --output-dir outputs/ci_checks

# 3. 查看当前数据是否只是混合/占位数据
python run_project.py validate-data
python run_project.py accept-official-data

# 4. 查看合成基线
python tools/synthetic_scenario_matrix.py --output-dir outputs/synthetic_scenario_matrix
python tools/synthetic_regression_baseline.py --output-dir outputs/synthetic_regression_baseline

# 5. 需要完整确认时运行全量 smoke（约十几分钟）
python run_project.py smoke

# 6. 进行当前默认仿真
python run_project.py simulate --data-dir data/real_shuohuang --output-root outputs

# 7. 审计输出
python run_project.py check-results --output-root outputs
```

如果第 3 步严格正式数据验收失败，不要把它当作算法 bug；先检查数据来源状态和缺失的正式资料。只有正式数据门禁通过后，才进入工程节能效果验证。
