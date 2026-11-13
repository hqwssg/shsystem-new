# 文档索引

更新时间：2026-09-13  
当前文档基线：`2026.09.13.2`

安全审计提示：当前候选已完成Python 3.11/3.12隔离重建、依赖哈希锁和Python 3.12 OSV零命中复审；旧正式v5仍保留Python 3.9/Pillow风险记录。新生产发布仍待完整发布和目标环境验收。详见`dependency_security_and_sbom.md`与`clean_environment_and_portability.md`。

日常维护、发布就绪检查、原子构建和一键验收见`maintenance_and_release_automation.md`。

## 当前状态入口

项目文档以 [`current_documentation_baseline.md`](current_documentation_baseline.md) 为唯一当前状态入口。新接手人员只需依次阅读：

1. `current_documentation_baseline.md`：当前版本、完成状态和结论边界；
2. `algorithm_scope_and_deliverables.md`：算法做什么、不做什么；
3. `current_project_status_and_io.md`：输入、输出和运行契约；
4. `current_algorithm_validity_boundary.md`：结果能否对外使用；
5. `current_data_gaps_and_next_actions.md`：正式数据缺口。

其余文档属于使用说明、专题证据、旧摘要、论文资料、参考原件或历史归档。完整逐文件状态见 [`document_status_registry.json`](document_status_registry.json)，由 `python tools/verify_documentation_status.py` 检查覆盖和唯一分类。任何旧阶段性能数字或失败记录都不得覆盖当前文档状态基线。

## 完整专题清单（按需查阅）

## 首先阅读

| 文档 | 用途 |
| --- | --- |
| `../README.md` | 项目现状、统一运行命令和可信边界 |
| `../PROJECT_STRUCTURE.md` | 代码、数据、测试和输出目录结构 |
| `current_algorithm_validity_boundary.md` | 当前算法能说明什么、不能说明什么 |
| `current_data_gaps_and_next_actions.md` | 当前数据缺口、校准现状与后续动作 |
| `current_project_status_and_io.md` | 当前项目状态、输入生命周期、输入输出契约和 KPI 定义 |
| `database_integration_phase1_conventions.md` | `carbon_emissions`数据库、`simulation_`表前缀、时间、主键、权限和事务约定 |
| `interface_contract_freeze.md` | 平台数据库逻辑接口冻结版本、任务、状态、结果语义及兼容变更规则 |
| `simulation_program_database_schema.md` | 平台模拟程序所需输入、任务和结果表的数据字典 |
| `database_integration_guide.md` | 数据库部署、导入、任务执行、平台展示、幂等和安全操作手册 |
| `database_delivery_package_guide.md` | 数据库部署与联调交付包总入口、部署命令、五类任务和验收方式 |
| `release_baseline_and_delivery.md` | 正式软件版本基线、完整算法交付包、逐文件校验和统一发布验收门禁 |
| `long_test_performance_gate.md` | 7项长测的重复计时、进程树峰值内存、回归阈值和正式/诊断范围判定 |
| `production_assurance_toolkit_guide.md` | 生产保障工具包入口、完整本地演练、内容边界和甲方接手路径 |
| `production_operations_runbook.md` | 启停、日常运行、任务恢复、升级回滚和证据归档 |
| `production_monitoring_and_incident_response.md` | 运行指标、告警阈值、事故分级和标准处置流程 |
| `production_backup_restore_drill.md` | PostgreSQL安全备份、隔离恢复和正式演练要求 |
| `production_assurance_acceptance_checklist.md` | 本地准备与甲方目标环境验收的分层清单 |
| `database_platform_integration_handoff.md` | 数据库管理员、平台后端、算法部署和业务验收之间的职责与调用链 |
| `database_platform_integration_checklist.md` | 目标环境部署、权限、五类任务、页面展示和运维签字清单 |
| `database_runtime_transaction_idempotency.md` | 任务幂等键、租约心跳、过期回收、状态版本、事务写回和并发验收 |
| `solver_resource_budget_and_degradation.md` | 五类任务墙钟预算、搜索降级链、超时语义和平台展示规则 |
| `../outputs/database_postgres_segregated_e2e_acceptance_v4/DATABASE_FIVE_RUN_E2E_REPORT.md` | PostgreSQL 16分角色五类数据库任务端到端验收结果 |
| `current_project_user_guide.md` | 面向新成员的项目详细说明、运行方式、结果解读和当前限制 |
| `algorithm_scope_and_deliverables.md` | 算法边界、能力回收定义、统一指标和交付物 |
| `official_data_intake_checklist.md` | 正式运行图/车辆/供电臂/储能/闭塞/库存接入清单 |
| `minimal_official_data_package.md` | 分阶段最小正式数据包、字段、元数据和验收标准 |
| `reproducible_experiments.md` | 端到端实验和多 case 实验复现清单 |
| `project_hygiene.md` | 生成物分类、归档边界和安全清理流程 |
| `performance_analysis.md` | cProfile 性能分析工具、基准和解读边界 |
| `synthetic_regression.md` | 合成数据回归基线与场景覆盖矩阵 |
| `synthetic_data_anomaly_matrix.md` | 静态输入数据包的文件、拓扑、车辆、储能及跨表异常注入矩阵 |
| `abnormal_extreme_input_testing.md` | 静态、平台、实时、核心极端、随机差分及深层合同的统一异常输入验收 |
| `performance_capacity.md` | 多规模性能容量分析 |
| `prototype_backend_contract.md` | 原型字段与后端接口契约 |
| `local_ci_checks.md` | 本地持续集成式质量门禁 |
| `official_data_readiness_pipeline.md` | 正式数据只读验收、隔离仿真与结果对比流程 |
| `official_data_auto_trigger.md` | 正式数据到件标记、哈希快照、幂等触发、状态账本与工程主链自动执行 |
| `formal_experiment_controller.md` | 正式数据验收后的基线、储能消融、规则/NSGA-II 优化和质量审计总控 |
| `paper_experiment_statistics_pipeline.md` | 多评价窗清单执行、窗内种子汇总、成对统计、置信区间、显著性检验和论文表图自动生成 |
| `../paper/experiments/实验结果汇总.md` | 当前异构论文实验的自动总览、关键指标和正式证据缺口 |
| `model_meter_calibration_and_error_analysis.md` | 模型结果—电表匹配、独立留出验证、误差指标、发布门禁和正式实验衔接 |
| `algorithm_scale_and_stability_benchmark.md` | 运行图与重空调度的规模、跨种子稳定性、同种子复现和资源基准 |
| `small_scale_optimality_gap_benchmark.md` | E12有限域穷举最优、三档NSGA-II差距、可行命中率和复现命令 |
| `synthetic_rolling_rescheduling_benchmark.md` | E15合成晚点、SOC连续、执行锁定和多轮滚动回退测试 |
| `recovery_conflict_chain_extraction.md` | 扰动恢复第一阶段的冲突链、锁定边界、可调整列车集合和优先级 |
| `recovery_local_repair.md` | 扰动恢复第二阶段的局部修复目标、结果状态、采用规则和E15验证 |
| `recovery_exact_resource_integration.md` | 扰动恢复第三阶段的精确MILP接入、锁定边界、触发规则和验证 |
| `recovery_multicycle_validation.md` | 扰动恢复第四阶段的计划/实际状态修复、强扰动恢复门禁和E15结果 |
| `recovery_ablation_validation.md` | 扰动恢复第五阶段的关闭/开启消融、公平性门禁、跨轮收益和能量影响 |
| `rolling_infeasible_commit_gate.md` | 核心稳健不可行候选的生产扣留、SOC结算、实验覆盖及数据库映射 |
| `rolling_safety_degradation_state_machine.md` | 提交门禁后的有界重试、等待新观测、人工升级、幂等复用和数据库事件 |
| `rolling_storage_device_runtime_state.md` | 分设备SOC、在线/停运、功率降额、跨轮连续性和平台输入契约 |
| `historical_disturbance_replay_interface.md` | 历史扰动回放JSON合同、数据库快照调用、结果追溯和当前事件语义边界 |
| `historical_recovery_performance_optimization.md` | 历史扰动局部恢复的瓶颈、等价缓存、稳定工况轨迹复用和性能复验 |
| `joint_parameter_robustness.md` | 车辆、储能、电气参数区间与运行扰动的联合稳健性评价、结论边界和数据库调用 |
| `database_storage_device_algorithm_binding.md` | 数据库逐设备容量、功率、双向效率、SOC边界到算法的权威绑定链路 |
| `dispatch_performance_optimization.md` | 重空协同调度瓶颈定位、等价优化和2/4列车性能验收结果 |
| `dispatch_feasibility_repair.md` | 6/8列车不可行原因、窄可行窗口、条件修复机制和第三阶段验收边界 |
| `dispatch_12train_targeted_feasibility_repair.md` | 12列车均匀模板瓶颈、冲突驱动局部错峰、F12/E12修复结果和边界 |
| `dispatch_targeted_repair_performance.md` | E12定向修复重复资源检查剖析、等价缓存、前后性能和语义一致性验收 |
| `dispatch_16train_quick_boundary.md` | E16/F16快速档性能、服务完整性、稳健可行域、修复诊断和当前边界 |
| `dispatch_e16_feasibility_diagnosis.md` | E16最后阻塞链、局部修复参数对照、资源可行种子和完整稳健验证 |
| `dispatch_f16_density_boundary_diagnosis.md` | F16高密度咽喉冲突定位、时域扩展对照和可行性边界 |
| `exact_resource_feasibility.md` | 精确资源可行性模型、结论语义、F16复核结果和复现方法 |
| `../paper/experiments/dispatch_exact_resource_f16_end_to_end/F16_EXACT_END_TO_END_VERIFICATION.md` | F16精确种子的能量、电气、信号、SOC、服务和资源端到端验收 |
| `../paper/experiments/dispatch_exact_resource_f16_quality/F16_EXACT_QUALITY_REPORT.md` | F16最小偏移证明、完整评价问题处置和质量优化验收 |
| `dispatch_single_candidate_performance.md` | 单候选隔离剖析、等价缓存优化、前后语义与耗时对比及停止条件 |
| `dispatch_extended_scale_test_design.md` | 10/12列车实测，以及16列车固定时域和扩展时域两套测试口径 |
| `../paper/experiments/dispatch_capacity_quality_phase3/DISPATCH_CAPACITY_QUALITY_REPORT.md` | 当前重空协同调度2/4/6/8列车容量与核心稳健可行性结果 |
| `research/paper_data_requirements.md` | 论文写作所需数据、字段、来源和验收清单 |
| `project_complete_guide.md` | 从项目目标、架构、数据、算法、测试到后续计划的完整总览 |
| `algorithm_core_implementation.md` | 算法调用链、核心数据结构、伪代码与代码实现细节 |
| `algorithm_api_reference.md` | 核心函数参数、返回值、异常和边界行为 |
| `algorithm_consistency_checks.md` | 模块交叉验证、基线/消融和参数单调性检查 |
| `algorithm_robustness_checks.md` | 极端场景、结算分辨率和确定性复现检查 |
| `algorithm_property_checks.md` | 随机化、时间边界、方向、终端 SOC 和资源属性测试 |
| `random_synthetic_differential.md` | 随机合成能量、资源和 Pareto 案例的独立参考实现差分测试 |
| `realtime_state_anomaly_matrix.md` | 实时字段、乱序、重复、断流、时钟漂移、设备状态和滚动恢复异常注入矩阵 |
| `platform_task_stress_fault.md` | PostgreSQL任务并发创建/领取/心跳/取消压力及崩溃、旧令牌和事务回滚故障测试 |
| `algorithm_extended_checks.md` | 缓存、优化器、序列化、缺失数据、资源、性能和静态检查 |
| `algorithm_validation_suite.md` | 快速/精细误差、基线消融、优化稳定性、储能策略和性能验证 |
| `operational_readiness_checks.md` | 实时输入契约、异常降级、结果追踪、schema 兼容和性能门禁 |
| `research/paper_draft_v0.md` | 不依赖正式数据的论文初稿（方法、原型和合成实验框架） |

统一入口生成的运行清单位于 `outputs/run_manifests/`；其字段和复核方法见 `current_project_status_and_io.md` 的“运行可追溯清单”章节。

## 当前功能

| 文档 | 用途 |
| --- | --- |
| `heavy_empty_network_optimizer.md` | 重空列双层时空网络优化原型 |
| `timetable_input_template.md` | 运行图输入模板及字段 |
| `timetable_optimizer.md` | 运行图评估与 NSGA-II 优化 |
| `optimization_attribution_and_bottleneck_report.md` | 运行图与重空调度的收益归因、候选筛选、瓶颈解释和可信边界 |
| `energy_scenario_objective_prompts.md` | 历史能量场景目标模式说明，仅作需求演进参考；当前主流程使用 `storage_no_direct` |

## 项目技术资料

| 文档 | 用途 |
| --- | --- |
| `project/TECHNICAL_OVERVIEW_CN.md` | 中文技术总览 |
| `project/TECHNICAL_OVERVIEW.md` | 英文技术总览 |
| `project/DATA_REQUIREMENTS.md` | 算法数据需求和字段说明 |
| `reference/251216-技术方案-铁路运输绿色低碳节能技术智能管理系统研究（基础版）(1).docx` | 技术方案原始参考文档，不直接修改 |

文档与代码不一致时，以 `run_project.py` 当前入口、`data/real_shuohuang/` 当前数据和最新自动生成报告为准。

## 历史与归档

| 目录 | 内容 |
| --- | --- |
| `archive/reports/` | 按日期保存的历史周报，不作为当前状态依据 |
| `reference/` | 甲方/技术方案原始参考文件，不直接修改 |
