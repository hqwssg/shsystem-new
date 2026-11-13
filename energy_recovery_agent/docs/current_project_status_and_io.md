# 当前项目状态、输入输出与运行契约

更新时间：2026-09-11

本文是当前实现的总览，回答三个问题：项目现在能做什么、算法每类流程实际读取什么、运行后会输出什么。字段级约束仍以 [`project/DATA_REQUIREMENTS.md`](project/DATA_REQUIREMENTS.md) 为准；本文以 `run_project.py` 的统一入口和当前默认数据目录为准。

版本、测试数量和交付状态统一以 [`current_documentation_baseline.md`](current_documentation_baseline.md) 为准；下文带“当时版本”的性能数字只保留为专项演进证据。

## 1. 当前结论

当前算法项目范围冻结为“再生制动能量回收能力分析 + 重空列车调度优化”。监测硬件、实时控制、碳排放平台、通用 AI 预测和三维可视化不属于本算法交付物；详细边界、能力回收分层和指标定义见 [`algorithm_scope_and_deliverables.md`](algorithm_scope_and_deliverables.md)。

- 当前 `tests/smoke/` 共101个 `verify_*.py` 验证脚本，其中默认96个短耗时 smoke、5个调度/运行图长耗时脚本；另有2个集成长测纳入独立长测试运行器。长测性能门禁覆盖全部7项，两个主要热点各重复2轮，并检查中位耗时与进程树峰值RSS。生产保障专项覆盖监控阈值、恢复库安全边界、凭据不落盘和本地/生产验收状态分离。异常与极端输入总套件、随机合成差分、实时状态异常、静态输入数据异常和接口契约冻结专项均通过。异常总套件覆盖29项静态异常、49项平台参数、40项实时异常、10项核心极端场景、4800项随机差分和6个深层合同专项。精确资源、偏移质量、结论分类、收益归因与瓶颈解释、原资源修复、小规模最优性差距、多轮滚动状态、数据库设备参数绑定、历史扰动回放、联合参数稳健性、恢复冲突链、局部/精确恢复接入、恢复消融、不可行提交门禁、安全降级状态机、依赖哈希锁审计、论文跨窗统计及异构实验自动汇总专项回归均通过，项目编译通过。
- 重空网络优化器已完成评分态与展示态分离：搜索阶段不再为全部候选保留逐供电臂结算明细，相同基因组复用不可变评价结果，排序后只为最佳候选补建完整明细。完整双场景测试平均由502.149秒降至131.511秒，降低73.81%；峰值私有内存由约19.34 GB降至约1.06 GB，降低约94.54%。固定种子下16个输出工件两轮SHA-256完全一致；当时版本的91项短测和7项长测全部通过。详见 `docs/heavy_empty_network_performance_optimization.md`。
- 历史扰动恢复已完成等价性能优化：相同运行图复用资源检查，未变化列车复用资源区间，一次检查共享区间校验和分组结果，并在发车严格晚于最后工况边界后复用稳定动力学轨迹。标准四轮回放两次实测为223.533秒和227.099秒，平均225.316秒，相对594.796秒基线降低62.12%；评价次数、20层搜索及16个业务工件保持不变。详见 `docs/historical_recovery_performance_optimization.md`。
- 提交门禁后的安全降级状态机已完成：每轮重试次数、时域和搜索预算均有上限；完全相同请求按SHA-256指纹幂等复用；首次失败后等待新观测，连续两轮失败升级人工处置，新观测恢复时有独立状态。真实组件E15测试中，第2轮初始不可行，经一次增强重试自动恢复，最终4/4轮核心稳健可行。逐轮事件可写入 `simulation_rolling_control_event`。
- 数据库运行状态已增加生产级事务与幂等保护：新任务强制项目内幂等键和请求摘要；工作进程使用带心跳的限时租约；崩溃任务可重排且有最大尝试次数；旧租约不能冻结输入、写结果或覆盖失败状态；状态版本、迁移事件和结果明细在同一事务提交。本地PostgreSQL 16测试实例已完成`001-007`迁移、四类独立账号权限探测，以及“平台账号建任务、worker账号执行、只读账号验收”的五类任务闭环；目标平台数据库、真实账号、TLS、备份恢复和负载仍需在部署环境复验。证据见`outputs/target_platform_predeployment/`与`outputs/database_postgres_segregated_e2e_acceptance_v4/`。
- 平台任务压力与故障测试已完成三档真实PostgreSQL多连接实测：120/500/1000任务对应12/24/32并发worker，全部唯一领取、心跳和取消成功，六类崩溃/租约/迟到写回/事务回滚故障均通过。测试发现并修复了相同幂等键并发创建时确定性`run_id`主键竞争未被捕获的问题；1000任务档创建和领取P95分别为17.993/21.925毫秒。结果只代表本机任务队列，不是目标平台SLA。
- 论文实验已形成研究清单驱动的跨评价窗自动化链路：逐窗串联正式数据门禁、基线、无储能消融、规则优化、多种子NSGA-II和质量审计；统计阶段先在窗内汇总随机种子，再以评价窗为独立样本形成成对改善、Bootstrap置信区间、符号翻转检验、Holm校正、排除表和论文图。正式数据尚未到位，因此当前完成的是可执行链路和合成回归验证，不是正式论文实验结论。详见 `docs/paper_experiment_statistics_pipeline.md`。
- 数据库部署与平台联调材料已形成独立交付包：包含环境模板、一键迁移与授权、健康检查、常驻工作进程、五类任务参数、平台只读查询、职责边界、验收清单、测试证据和逐文件SHA-256。交付包需覆盖到同版本完整算法项目中运行，目标平台仍须完成生产TLS、登录账号、备份恢复、并发负载和故障演练。
- 完整算法软件已建立独立正式版本基线：`release/release_baseline.json`冻结运行源码、数据库工作进程、规划运行数据、模板、当前测试、工具、原型合同和运行文档的逐文件大小与SHA-256；`requirements-lock.txt`锁定完整依赖闭包及制品哈希。目录包和ZIP通过`verify_algorithm_delivery_package.py`核验，正式发布必须再由`run_release_acceptance.py`依次通过基线/包、接口冻结、本地CI、96项短测和7项带性能门禁的长测，跳过长测不能形成发布通过结论。文档状态登记已纳入本地CI，新增文档未分类、权威链接失效、版本不一致或重新出现旧口径都会阻断发布。
- 正式数据到件自动触发链路已完成：交付包以最终标记提交，程序核验精确文件集合、大小和逐文件SHA-256后冻结原子快照；相同内容按指纹幂等处理，随后自动执行正式数据验收、完整工程仿真、结果质量审计和正式对比总控。当前无正式交付包时状态为 `waiting`，不会把默认混合数据误当正式数据。详见 `docs/official_data_auto_trigger.md`。
- 生产运行保障预案与本地工具链已形成：统一预检、只读运行快照、告警阈值、事故响应、升级回滚以及PostgreSQL一致性快照备份/隔离恢复演练均可执行；本地报告固定区分`local_ready`与`production_accepted=false`。目标TLS、监控通知、正式备份介质、SLA和平台联调仍保持外部待验收，详见`docs/production_assurance_toolkit_guide.md`。
- 运行图优化与重空调度已自动生成统一收益归因和瓶颈解释：包含采用/保留基线决策、KPI差值、逐候选理由、筛选漏斗、核心/非核心瓶颈和列车/区段/资源/储能/时间窗维度。固定储能对照才允许发布纯调度收益；七个核心工件已通过本地PostgreSQL任务队列写回验收。
- 滚动调度已支持逐储能设备实时状态：每台设备按ID独立传递SOC、在线/停运状态和临时充放电功率上限；停运设备保留SOC但不能充放电，设备状态变化会进入请求指纹。四轮正常与单设备停运基准均通过全部门禁，旧的汇总SOC入口仅作为兼容接口保留。
- 平台模式已将 `simulation_storage_device` 的逐设备额定容量、充放电功率、双向效率、初始SOC、SOC上下限和静态投运状态直接绑定到能量结算、重空调度、滚动调度及运行图评价。数据库设备行进入不可变运行快照；存在逐设备参数时禁止虚拟储能预设和聚合物理参数覆盖。
- 已完成合成状态驱动的四轮滚动重调度端到端测试：名义计划和叠加已观测晚点的实际执行运行图已经分离，实际发车进入下一轮锁定集合，执行片段终点SOC连续传递，预测评价不重复结算历史。第2轮局部修复以名义调整 `H002 +90s`、`E002 +120s` 清除冲突；叠加观测后实际提交为重车3570秒、空车6020秒。四轮最终均核心稳健可行且资源冲突为0，最强联合扰动轮和最终恢复轮均通过。详见 `paper/experiments/E15_synthetic_rolling_rescheduling/`。
- 历史扰动回放接口已接通数据库冻结快照、统一命令行、滚动观测和结果工件。平台以 `disturbance_history_relative_path` 引用版本中的JSON，算法严格校验版本、周期、时间轴、源记录ID、汇总晚点、逐列车晚点和可选设备状态，并输出源文件SHA-256及逐轮回放结果。`1.3` 已直接执行逐列车晚点、取消、加车、资源封锁、供电动态限值、双向及方向专用临时限速和完整设备状态；旧版本保持原阻断语义。详见 `docs/historical_disturbance_replay_interface.md`。
- 已实现参数区间联合稳健性评价：15类车辆动力学、储能和电气参数默认生成39个可追溯物理场景，再与5个运行扰动形成195个联合组合；每个物理场景重新计算列车轨迹和能量结算，并输出最差组合。当前结论严格限定为“已测试离散联合场景”，不等同于连续参数区间证明。详见 `docs/joint_parameter_robustness.md`。
- 扰动恢复第三阶段已把精确资源MILP接入滚动流程：完整合并运行图可无损进入精确模型，历史发车固定、未来发车可调，精确候选必须再过完整稳健评价。修正实际执行状态提交后，当前E15第3、4轮已常规稳健可行，因此精确层无需触发；专项测试仍使用当前线路资源、真实轨迹缓存和HiGHS验证了带锁定历史的 `feasible_verified` 求解路径。
- 扰动恢复第五阶段已完成同输入消融：关闭恢复时只有1/4轮核心稳健可行，全部核心场景累计17个冲突；开启恢复后4/4轮可行且冲突为0。第2轮是210秒局部调整的直接恢复，第3、4轮是避免不可行回退进入锁定历史后的跨轮收益。执行期购电量差为-444.725737 kWh；因控制组后3轮不可行，该差值只用于机制追踪，不属于同等可行方案间的节能比较，也不是正式节能结论。详见 `docs/recovery_ablation_validation.md`。
- 已增加核心稳健不可行提交门禁：生产默认扣留本轮未锁定的新发车，不写入下一轮锁定历史，SOC只结算已发生/已锁定运行图，并输出 `withheld_infeasible` 和人工干预标志。关闭恢复的专项四轮验证中，第2轮0项新增提交，第3、4轮在未污染历史上重新可行，综合门禁和独立核验通过。实验传播必须显式开启 `allow_infeasible_commit_for_experiment`。详见 `docs/rolling_infeasible_commit_gate.md`。
- F16精确层已采用“最小最大单车偏移、再最小总绝对偏移”的词典序质量目标，并直接以相位840秒原运行图为参照：最大偏移最优值为367秒，总绝对偏移最优值为3000秒；质量解通过三个核心场景完整评价，三个核心场景终端SOC偏差均为0。±300秒非核心压力场景仍不可行。
- smoke 通过 `python run_project.py smoke` 运行时，成功输出写入临时目录，失败证据才保留到 `outputs/smoke_failures/`；本轮确认的 12 个可重建历史输出目录已归档到 `outputs/archive/2026-08-project-hygiene/`，移动前逐文件 SHA-256 清单和移动回执保存在该目录。
- 普通 `python run_project.py validate-data` 当前为 `valid=true`、0 个错误、25 个警告；`--require-official-data` 严格门禁会因规划/虚拟数据仍未替换而阻断（当前 10 个错误），这是预期的数据就绪保护，不是算法异常。
- 本轮新增了终点边界、零长度列车缓存和牵引/制动参数校验回归：修复列车在终点前约 2 m 因离散积分降为零速后无法满足到站判定、最终运行至 `max_time_s` 才失败的问题；修复优化器缓存拒绝文档允许的 `length_km=0` 点质点场景；并修复 `validate-data` 放行零牵引力/零制动力、随后运行时才失败的问题。相关正/反向、粗细步长、缓存构建和坏数据拒绝测试均已通过。
- 当前默认运行目录是 `data/real_shuohuang/`，主线范围为朔黄主线 K0–K583.003、33 个站点。
- 运行图、车辆动力学、储能设备、电气限值、闭塞分区和初始车流库存仍有虚拟/规划/启发式数据，因此结果可用于流程验证、候选比较和敏感性分析，不能作为正式节能量、储能容量或投资收益结论。
- 上下行直发直用在当前朔黄口径中关闭；主场景为 `storage_no_direct`，再生能量只能在标记的储能区段内通过储能复用。
- `data/real_shuohuang/energy_calibration_factors.json` 的校准系数是实验系数，`enabled_by_default=false`，默认不会改变优化器物理结果。
- 原型界面可编辑源为 `prototypes/heavy-empty-coordination-ui.fragment.html`，独立预览页为 `prototypes/heavy-empty-coordination-ui.html`；运行页展示版本引用、只读派生时域、运行阶段进度和输入快照，任务结果页展示演示指标，性能分析页仅展示观测口径，不替代后端算法。

## 2. 数据生命周期和人工职责

系统不会在每次运行时要求人工重复填写全部数据。数据按更新频率分层：

| 数据层 | 典型文件/参数 | 当前来源 | 谁维护、多久变化 | 每次运行是否重新输入 |
|---|---|---|---|---|
| 固定基础资料 | `stations.csv`、`gradients.csv`、`curves.csv`、`route_metadata.json` | 已审查线路/PDF资料及整理结果 | 专业管理员维护；线路资料变更时更新 | 否，程序从 `--data-dir` 自动读取 |
| 由基础资料生成的派生资料 | `segments.csv`、`power_arm_intervals.csv`、`build_summary.json` | 构建脚本自动生成 | 基础资料更新后重建 | 否；仅在 `--rebuild-data` 或显式构建时更新 |
| 低频工程参数 | `trains.csv`、`battery.json`、`energy_transfer_zones.csv`、`resource_config.json` | 当前含虚拟/规划占位 | 设备、车辆、信号或资源资料确认后由管理员替换 | 否；运行时自动读取 |
| 低频业务模板 | `running_diagram_template.xlsx`、`heavy_empty_od_template.xlsx` | 当前为拟真模板 | 运行图/OD/作业规则发生变化时更新 | 否；操作员选择文件或模板版本 |
| 高频运行状态（目标系统需要） | 实时列车位置、功率、SOC、临时限速、实际到发时刻 | 当前项目尚未接入实时生产接口 | 运行控制系统/采集系统持续更新 | 当前原型不接入；由仿真轨迹和场景参数代替 |
| 本次运行控制项 | `--heavy-count`、`--empty-count`、相位、发车间隔、结算步长、目标模式、搜索规模 | 命令行或上层界面 | 操作员按本次实验/方案选择 | 是，但只输入本次场景控制项 |
| 校准派生结果 | `smart_meter_calibration_samples.csv`、`energy_calibration_factors.json` | 电表匹配和误差分析脚本生成 | 新增清洁样本并经审核后更新 | 否；默认只用于对比/敏感性 |

`--rebuild-data` 是显式动作；普通 `simulate` 不会自动覆盖当前数据目录。

## 3.4 原型界面输入与正式命令映射

原型中的下拉框用于演示“固定数据引用、低频模板选择和本次运行控制项”的分层，并不表示每个字段当前都能直接传给后端。正式接入时应按下表映射：

| 原型字段 | 当前性质 | 正式实现对应 | 说明 |
|---|---|---|---|
| 基准运行图 | 低频引用 | `--timetable` 或运行图版本 ID | 不应在每次运行手工重填运行图内容 |
| 预测/执行/评价窗口 | 自动派生/只读 | 由运行图、列车轨迹、作业尾段和结算步长计算 | 不是独立人工输入的总时长 |
| 参与列车 | 原型范围选择 | 当前正式流程主要用 `--heavy-count`、`--empty-count` | `all/corridor/selected` 仍属于上层场景筛选概念 |
| 优化目标 | 本次控制项 | `--objective-priority` 或 `--objective-mode` | 原型“综合/节能/能力”需由后端统一枚举映射 |
| 扰动场景 | 原型场景 | 当前 `dispatch-case` 的正式能量场景仅 `storage_no_direct`（`auto` 为兼容别名） | 晚点、天气、设备退出需要后端场景模型确认后才可启用 |
| 求解模式 | 本次控制项 | `--search-profile`（`quick/standard/large`）及种群/代数参数 | 原型“正式优化”不是当前 CLI 的独立枚举 |
| 低频配置模板 | 低频引用 | `resource_config.json`、`battery.json` 等版本 | 运行人员选择版本，不能逐项改物理参数 |
| 初始状态来源 / SOC | 高频快照或离线测试项 | 当前项目尚未接入实时接口；离线 SOC 仅适合测试 | 正式运行应从状态快照读取并记录版本 |
| 储能参与 | 本次开关 | `--enable/disable-storage-preset-search` 等储能开关 | 设备额定容量、功率和效率仍来自版本化数据 |

因此，原型说明应明确分为“当前可映射控制项”“自动派生只读项”和“未来接口占位项”；后端接入前不能把原型所有字段直接当作算法输入。

## 3. 主流程输入

### 3.1 统一入口

```powershell
python run_project.py simulate --data-dir data/real_shuohuang --output-root outputs
```

`simulate` 依次调用数据校验、电表样本、运行图审查、运行图优化和重空调度。它读取：

1. `--data-dir` 下的线路、车辆、储能、供电臂和资源文件；
2. `--timetable` 指定的运行图（默认 `data_templates/running_diagram_template.xlsx`）；
3. `--smart-meter-dir` 指定的电表源数据（默认 `data/source/smart_meter`）；
4. 本次场景控制项，如列车数量、基准相位、发车间隔、`settlement_step_s`、搜索规模和能量可观测性开关。

总评价时长不是要求人工填写的独立“总时长”字段，而是由运行图/列车轨迹、作业时间和场景预测窗口共同决定。`settlement_step_s` 只表示能量结算离散步长，不是评价总时长；当前默认调度结算步长为 10 秒。

### 3.2 各命令的输入

| 命令 | 固定/低频输入 | 本次控制项 | 说明 |
|---|---|---|---|
| `validate-data` | `data-dir`、`source-dir`、运行图 | 输出目录 | 只校验，不改变算法输入 |
| `meter-samples` | 电表源、站点表、校准系数 | 样本上限、校准模式 | 重叠站区间会被排除，不会伪造连续区间 |
| `audit-timetable` | 运行图、供电臂、车辆、储能 | 输出目录、可选严格可视化 | 评估当前运行图的能量和资源风险 |
| `optimize-timetable` | 运行图、资源配置、供电臂、储能 | 移动/停站范围、种群、代数、随机种子 | 输出候选运行图和 Pareto 集 |
| `dispatch-case` | OD/服务/作业/资源模板、线路、车辆、储能 | 重空数量、相位、headway、结算步长、目标模式、搜索规模 | 运行重空双层时空网络和能量结算 |
| `experiment-suite` | 默认数据和拟真模板 | 输出根目录 | 批量运行预设 case 与敏感性分析 |
| `check-ingestion` | 新交付文件、站点表、路线元数据 | `--kind` | 替换正式数据前的闸门检查 |
| `accept-official-data` | 正式数据目录、来源目录、运行图 | `formal_data_acceptance/` | 严格要求运行文件齐全且无虚拟/未确认来源；只读，不修改输入 |
| `check-results` | `simulate`/`dispatch` 输出目录 | `result_quality_audit/` 或指定目录 | 检查能量守恒、SOC 边界、汇总一致性和 `valid=false` 结果 |
| `create-official-data-marker` | 已复制并转换完成的正式交付包 | 交付号、评价窗和实验参数 | 最后生成精确文件清单与SHA-256到件标记 |
| `official-data-auto-trigger` | 带最终标记的正式交付包 | 单次检查或常驻轮询 | 冻结快照并幂等串联验收、完整仿真、质量审计和正式对比总控 |

### 3.3 关键输入字段语义

| 输入 | 单位/格式 | 作用 | 当前状态 |
|---|---|---|---|
| `route_metadata.json.route.total_length_km` | km | 仿真线路边界 | 朔黄主线整理值 |
| `route_metadata.json.route.long_downhill_range_km` | `[start,end]` km | 长大下坡控制提示 | 当前为最小禁用占位；实际能量使用逐段坡度表 |
| `trains.csv.mass_tons` | t | 质量和动力学计算 | 质量部分有资料，牵引/制动/Davis/功率仍为虚拟预设 |
| `trains.csv.rotational_mass_factor` | 无量纲，≥1 | 等效质量修正 | 已校验，不会把 1.0 误当成 2 倍质量 |
| `battery.json.capacity_kwh` | kWh | 储能容量上限 | 规划虚拟值 |
| `battery.json.max_charge_power_kW` / `max_discharge_power_kW` | kW | 充放电功率上限 | 规划虚拟值；为 0 时表示不可用，不表示无限大 |
| `battery.json.round_trip_efficiency` | `[0,1]` | 储能转换损失 | 规划虚拟值，默认 0.9 |
| `power_arm_intervals.csv` | CSV，公里标/方向/储能标签/限额 | 供电臂归属、电气约束、储能区段切分 | 区间部分已整理，若干行需人工复核，能力限额仍是大默认值 |
| `energy_transfer_zones.csv` | CSV，起止公里标 | 柔性传输/储能覆盖范围 | K145–K164、K164–K200.7 规划假设 |
| `resource_config.json` | JSON | 站场、区间、咽喉和初始车流资源 | 含启发式/场景库存，非正式信号模型 |
| `settlement_step_s` | 正整数秒 | 同时性能量结算时间桶 | 默认 10；不改变仿真总时长 |
| `objective_priority` | `energy_first`/`cost_first`/`balanced` | 可行候选排序偏好 | 只改变候选排序，不伪造物理能量 |

## 4. 输出契约

### 4.0 运行可追溯清单

所有 `run_project.py` 统一入口命令都会自动在 `outputs/run_manifests/`（或命令选择的 `--output-root` 对应目录）写出一个 JSON 清单。清单在算法执行前先写入 `status=running`，命令结束后更新为 `success` 或 `failed`，因此异常运行也能留下可定位记录。清单不是算法输入，不需要人工填写。

文件名格式为 `run_<UTC时间>_<PID>_<随机ID>.json`，主要字段如下：

| 字段 | 说明 |
|---|---|
| `command`、`argv`、`arguments` | 原始命令和解析后的参数，区分本次场景控制项与默认值 |
| `code_version` | Git 提交/工作区状态；非 Git 目录使用项目 Python 文件 SHA-256 快照 |
| `input_inventory` | 输入路径、文件大小、修改时间和逐文件 SHA-256；目录输入在执行前递归采集 |
| `data_status`、`data_status_after` | 数据集状态、线路长度、显式假设和待确认项数量 |
| `validation_status` | 执行结束时可发现的数据校验/流程汇总 |
| `output_paths` | 本次命令声明的输出路径 |
| `status`、`return_code`、`exception`、`duration_s` | 最终成功/失败、返回码、异常摘要和耗时 |

复核某次结果时，应先打开对应清单，确认 `status=success`、`return_code=0`，再根据 `input_inventory` 和 `code_version` 判断结果是否可复现。清单只记录输入和结果定位信息，不会改变算法计算。

### 4.1 数据校验输出

目录：`outputs/data_quality_validation/`

- `data_quality_summary.json`：`valid`、`error_count`、`warning_count`、按来源/代码统计、`blocking_flows`。
- `data_quality_issues.csv`：逐条问题，字段为 `severity, code, source, row, field, message, suggestion`。
- `DATA_QUALITY_REPORT.md`：面向人工复核的报告。

当前默认数据校验为 `valid=true`、`error_count=0`，但存在警告：缺少正式闭塞分区、若干供电臂需复核、曲线长度解释需确认、电表站区间重叠和未知方向码。警告不等于算法 bug，但会限制工程结论。

### 4.2 电表样本和校准输出

目录：`outputs/energy_calibration_alignment/`（样本文件在输出根目录）。

- `smart_meter_representative_interval_samples.csv`：清理重叠后选出的代表区间。
- `arc_energy_vs_meter_samples.csv`：样本与运行弧的站点/公里标/时间对齐结果。
- `arc_energy_vs_meter_summary.json`：`sample_count`、`alignment_status_counts`、`calibration_applied_count`、估算状态和校准模式。

校准系数文件中的 `sample_count=532` 和 `robust_fit_sample_count=178` 属于历史实验集；`enabled_by_default=false`。2026-09-04 按新增独立留出门禁重跑后，代表样本仅形成 13 条拟合和 3 条验证记录，校准后验证集中位 APE 为 68.37%，门禁未通过，也未发布新系数。不能把历史文件当作已完成工程标定。完整结论见 `docs/model_meter_calibration_and_error_analysis.md`。

### 4.3 运行图审查输出

目录：`outputs/timetable_energy_audit/`

#### 主要用途和目的

运行图审查是“先看现状”的诊断流程。它不改变原运行图，也不负责选择最终优化方案，而是把现有运行图转换为可计算的运行弧和能量时间片，检查当前时刻安排是否造成再生能量无法吸收、储能受限、供电臂超限或运行数据不一致。其主要目的有三个：确认输入运行图能否被算法正确理解；量化当前运行图的能量回收基线；为后续优化提供明确的问题位置和候选调整方向。

审查输出回答的是：“现有运行图目前是什么情况、问题发生在哪里、是否存在可尝试的节能空间？”如果审查没有发现实质问题，后续优化门控可以直接保留原运行图；审查发现问题也不代表一定能优化成功，还必须经过候选生成、资源约束和能量复算。

#### 输出结果详细说明

- `audit_summary.json`：审查总账和流程状态。重点看 `valid`、列车数、运行弧数、时间片数、结算窗口数、能量事件数、问题数和建议数。`valid=false` 表示当前输入或计算结果不能作为合格审查结果，不应继续据此做优化结论。
- `timetable_running_arcs.csv`：运行弧级明细。一条记录对应一段列车运行或停站/作业区间，包含列车、站点/公里标、到发时间、牵引/再生能量、供电臂、方向和储能区段标签。它用于定位“哪一列车、哪一段线路、哪个时间窗口”产生了能量或约束影响。
- `timetable_energy_time_slices.csv`：时间片级能量明细。将运行弧按结算步长切分，记录牵引需求、再生能量、可接纳量、储能充电/放电、弃能、电网供能及约束状态。它用于检查能量随时间的变化和验证能量守恒，不能把其中的再生能量直接理解为可立即抵扣的牵引电量。
- `timetable_power_arm_settlement.csv`：供电臂—时间窗结算结果。按供电臂和时间窗口汇总牵引负荷、再生输入、储能行为、电网购电和电气限值，用于识别供电臂能力是否成为回收瓶颈。
- `audit_issues.csv`：审查发现的问题清单，通常包含问题类型、严重性、位置、时间范围、影响量和原因。它是排查数据问题、物理瓶颈和约束冲突的主要入口。
- `optimization_suggestions.csv`：根据审查结果生成的调整建议，例如时序错开、储能区段匹配或减少冲突。建议只是优化搜索的方向，不等于已经验证可执行的运行图。
- `scenario_summary.csv`：不同能量场景的汇总对比，用于区分直接利用、储能利用、弃能和电网供能等口径；当前主场景为 `storage_no_direct`。
- `figures/`：运行图、能量时间线和场景比较图，用于人工快速识别时空重叠及能量瓶颈。`visualization_diagnostics.json` 记录图表生成状态；图表失败不应掩盖表格和 JSON 中的审查结果。

### 4.4 运行图优化输出

目录：`outputs/timetable_optimizer_nsga2/`

#### 主要用途和目的

运行图优化是在运行图审查基础上的“提出并筛选改进方案”流程。它以现有运行图为基线，尝试调整列车发车/到达时刻、列车相位和必要的停站时间，在不破坏运输、追踪、站场、区间、供电臂和储能约束的前提下，寻找更好的能量利用方案。

优化不是无条件替换原运行图。算法会先评估基线，再评估候选；只有候选可行并且有效再生损失或电网购电量至少一项超过数值容差改善、另一项没有明显恶化时，`optimizer_summary.json` 的 `optimization_decision.action` 才为 `optimize`。否则输出 `keep_baseline`，表示没有足够证据证明调整值得采用，应继续使用原运行图。

#### 输出结果详细说明

- `candidate_summary.csv`：候选方案总表。每行代表一个候选，记录候选 ID、调整类型、调整分钟数、延误、资源冲突、电气违反度、总约束违反度和 `feasible`。先筛选 `feasible=true`，再比较能量指标。
- `candidate_scenario_scores.csv`：候选—场景明细。记录每个候选在每个能量场景中的 `effective_regen_loss_kwh_est`、`grid_kwh_est`、弃能、储能和约束结果，是判断候选相对基线是否改善的核心数据。
- `candidate_energy_issues.csv`：候选能量问题明细。用于说明候选为什么出现供电臂超限、储能无法吸收、时间窗口不匹配或其他能量缺陷。
- `pareto_candidates.csv`：可行且非支配的候选集合。它表示不同“节能效果—运行图调整代价”之间的有效权衡，不代表每个候选都必须采用，也不自动等同于最终推荐方案。
- `candidate_explanations.csv`：候选解释表，说明候选的决策角色、主要瓶颈、与基线的调整关系及进入/未进入 Pareto 集的原因。
- `candidate_timetables/`：Pareto 候选对应的可读运行图文件，用于人工审查具体到发时刻和停站变化。它们是方案文件，不是现场控制指令。
- `optimizer_summary.json`：优化运行总结果。除候选数、Pareto 数、模式、种群、代数和可视化状态外，重点查看 `optimization_decision`：`action=optimize` 表示发现满足门槛的改进候选；`action=keep_baseline` 表示保留原运行图，`reason` 记录原因。
- `generation_log.csv`、`final_population.csv`：仅 NSGA-II 模式生成，分别描述代际收敛过程和最终种群，用于复现和分析求解过程，不是业务人员首先需要查看的结果。
- `figures/`、`visualization_diagnostics.json`：优化前沿、候选调整和迭代过程图，以及图表生成状态；图表只用于辅助解释，最终判断以 CSV/JSON 数值和约束状态为准。
- `OPTIMIZATION_ATTRIBUTION_REPORT.md`、`optimization_attribution_summary.json`：集中回答是否采用、改善多少、主要瓶颈和解释边界；平台优先读取 JSON，人员优先阅读 Markdown。
- `optimization_kpi_attribution.csv`：统一以正值表示改善，区分收益指标与充放电量、末端 SOC 等中性账本指标。
- `optimization_candidate_decisions.csv`、`optimization_candidate_funnel.csv`：分别解释每个候选的决策角色，以及总候选在可行、实质改善、Pareto 和选中条件下的独立计数。
- `optimization_bottlenecks.csv`、`optimization_dimension_attribution.csv`：分别给出约束/问题聚合和列车时刻、供电臂等维度变化；共享储能系统收益不会无依据分摊到单车。

#### 两类输出的关系

运行图审查输出描述“现状和问题”，运行图优化输出描述“候选改进和是否采用”。通常应先查看 `audit_summary.json` 与 `audit_issues.csv`，再查看优化目录中的 `candidate_summary.csv`、`candidate_scenario_scores.csv` 和 `optimizer_summary.json`。前者发现的问题必须在后者中经过候选复算和约束检查，不能直接把审查建议当成节能结果。

### 4.5 重空调度输出

目录：`outputs/dispatch_storage_no_direct_phase2600/`

默认相位为 2600 秒时使用上述目录；如果覆盖 `--baseline-phase-s` 且未显式指定 `--output-dir`，目录后缀会自动变为对应相位，避免不同场景互相覆盖。

核心文件：

- `summary.json`：输入快照、数据状态、场景参数、baseline/optimized KPI、比较范围、Pareto 基础和搜索诊断。
- `kpi_summary.csv`：baseline 与 optimized 的物理和成本指标。
- `kpi_comparison.csv`：差值和百分比；只有固定储能上下文下的调度变化才可归因于调度。
- `energy_timeline.csv`：时间桶级 `direct/charge/discharge/wasted/grid`。
- `ranked_candidates.csv`、`pareto_candidates.csv`、`pareto_candidates.json`：候选排序和非支配集。
- `resource_conflicts.csv`、`flow_continuity_events.csv`、`flow_continuity_violations.csv`：资源与车流连续性约束诊断。
- `time_space_nodes.csv`、`time_space_arcs.csv`、`time_space_paths.csv`：节点—弧段网络展开结果。
- `OPTIMIZATION_ATTRIBUTION_REPORT.md`、`optimization_attribution_summary.json`：综合说明是否采用调度候选、收益范围和主要瓶颈。若储能预设发生变化，结论要求固定储能复核，不能把联合规划差值表述为纯调度收益。
- `optimization_kpi_attribution.csv`、`optimization_candidate_decisions.csv`、`optimization_candidate_funnel.csv`：提供 KPI 差值、逐候选理由和筛选统计。
- `optimization_bottlenecks.csv`、`optimization_dimension_attribution.csv`：提供核心/非核心场景瓶颈，以及列车、区段、供电资源、储能设备和时间窗的变化明细。

主要 KPI 定义：

| 字段 | 含义 |
|---|---|
| `total_gen_kwh` / `total_con_kwh` | 原始再生侧/牵引侧电量；不是电网购电 |
| `direct_used_kwh` | 同供电臂同时间窗直接利用；朔黄主场景固定为 0 |
| `battery_charge_kwh` / `battery_discharge_kwh` | 储能输入侧充电量/放电量 |
| `battery_*_limited_kwh` | 受容量、功率或 SOC 限制而未完成的请求 |
| `wasted_kwh` | 未被直接利用或储能吸收的再生电量 |
| `accepted_by_power_arm_kwh` | 经供电臂和时间匹配后，被直接利用或送入储能的再生侧能量 |
| `recovered_energy_kwh` | 直接利用量加储能充电量按效率折算后的有效回收能量（输出侧口径） |
| `recovery_rate` | `recovered_energy_kwh / total_gen_kwh`；无再生能量时为 0 |
| `grid_kwh` | 结算后仍需电网供给的牵引电量 |
| `effective_regen_loss_kwh` | 把弃电、储能转换损失和终端 SOC 影响统一折算后的再生损失 |
| `energy_term` / `energy_objective_kwh` | 优化用能量目标，当前主口径为 `grid_kwh + effective_regen_loss_kwh` |
| `final_soc_kwh`、`final_soc_by_storage_kwh` | 总 SOC 和按储能设备拆分的终端 SOC |
| `initial_soc_by_storage_kwh`、`battery_charge_by_storage_kwh`、`battery_discharge_by_storage_kwh`、`wasted_by_storage_kwh` | 各储能设备的窗口初始SOC、充电量、放电量和区段弃能，用于核验停运、降额和设备级能量归属 |
| `constraint_violation`、`electrical_constraint_violation_kwh` | 资源/电气约束违反度；非零时候选不可行 |
| `feasible` | 候选是否满足当前启发式资源、电气和连续性约束 |

`time_space_arcs.csv` 中 running 弧的 `energy_kwh` 允许为负，表示该弧的净再生能量；它不是 `grid_kwh`，不能单独据此判断“电网负耗电”。

## 5. 当前已修复的算法风险与剩余风险

已覆盖并回归的关键修复包括：10 秒结算步长保持独立、下坡收益不重复计算、同桶充放电禁止、多个储能设备 SOC 独立汇总、复合供电臂 ID 顺序规范化/缺失成员拒绝、长列车组件拆分保持能量转移比例、终端停放能量不被错误当作当期节能、终点前零速状态在数值容差内正确收敛到站、优化器缓存与 `length_km=0` 点质点输入契约一致、数据校验拒绝零牵引/制动力、资源区间拒绝倒置/零时长/非有限值、功率缓存采用线程安全有界 LRU，以及覆盖 `--baseline-phase-s` 时自动隔离默认输出目录等。

本轮又修复了两个相关的确定性输入缺陷：直接构造 `StorageSectionInterval` 时，`down/up/下行/上行` 方向别名此前不会归一化，可能使储能区段在运行方向查询时被静默忽略；储能位置/边界查询对未知非空方向也曾静默按通配方向处理，可能把储能能力应用到错误方向。现在数据类构造、CSV 加载和查询统一归一化为 `forward/reverse`，未知非空方向均拒绝，空方向仍表示通配。当前没有未修复的确定性 bug。剩余风险属于输入或模型适用性：正式运行图、车辆牵引/制动曲线、供电臂真实能力、储能设备参数、闭塞分区、初始车流库存和电表方向码/站区间质量尚未完全确认。拿到这些数据后，应先运行 `check-ingestion`，再重建数据、校验并复跑同一流程。
扩展回归测试还发现并修复了 `cmd_real_data_workflow` 成功路径缺少 `return 0` 的 CLI 契约缺陷；之前直接调用工作流会得到 `None`，被调用方可能误判为失败。现成功完成后明确返回 0，并已通过数据集隔离回归。
本轮继续复核结果审计：修复了直接传入 `dispatch_*/` 结果目录时被误判为无结果，以及 dispatch 汇总缺少关键能量指标时被默认成 0、从而可能漏检不完整输出的问题。现在支持直接审计单个 dispatch 目录，并对必需指标缺失明确报错。

## 正式数据和结果自动验收

正式数据替换前运行：

```powershell
python run_project.py accept-official-data --data-dir <正式数据目录> --source-dir <来源目录> --timetable <正式运行图>
```

该命令同时执行严格数据质量校验和接入契约校验；返回码为 0 才允许发布该数据目录。算法运行完成后运行：

```powershell
python run_project.py check-results --output-root <本次输出目录>
```

结果审计会检查发电侧/用电侧能量守恒、终端 SOC 与分设备汇总、SOC 容量边界、非负能量指标及审计/优化流程的 `valid` 标志。报告写入 `result_quality_audit_summary.json`、`result_quality_audit_issues.csv` 和 `RESULT_QUALITY_AUDIT_REPORT.md`。

新增回归覆盖还验证了非默认 dispatch 输出目录自动发现、局部 dispatch 输出审计、供电能力超限与能量守恒的区分，以及优化储能预设容量和基线容量分别校验，避免把有效结果误报为 SOC 超限。
