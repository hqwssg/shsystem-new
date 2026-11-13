# 优化收益归因与瓶颈解释报告

## 1. 目的

本功能用于回答优化结果中最重要的四个问题：是否应替换基线方案、改善了多少、改善来自哪些可识别维度、哪些约束仍在限制方案。它同时服务于运行图优化和重空协同调度，属于求解后的解释层，不改变候选生成、评分、可行性检查或 Pareto 排序。

正式数据未到位时，报告可验证解释链路和对比口径，但其中带有 `planning_placeholder` 的数值不能作为正式节能量、设备容量或投资收益结论。

## 2. 自动生成与历史补生成

以下流程成功完成时会自动生成报告：

```powershell
python run_project.py optimize-timetable ...
python run_project.py dispatch-case ...
```

既有结果目录可补生成，不需要重新求解：

```powershell
python run_project.py explain-optimization --result-dir <结果目录>
```

`--workflow` 可显式指定 `timetable_optimization` 或 `dispatch`，默认 `auto` 根据目录中的摘要文件识别。

完整的七个归因工件已经存在时，命令默认直接复用，避免历史目录缺少运行弧等中间数据时覆盖并降低原报告的信息量。只有确认要按当前仍可读取的历史文件重建时才使用 `--force`。

## 3. 决策结论

| `action` | 含义 | 平台动作 |
| --- | --- | --- |
| `optimize` | 候选通过核心可行性门禁，并产生达到容差的能量改善且没有明显反向恶化 | 展示为建议采用，仍须保留人工审批和正式数据门禁 |
| `keep_baseline` | 没有实质能量改善，或储能预设发生变化而不能把联合变化归为纯调度收益 | 默认保留基线，展示 `reason` |
| `no_feasible_solution` | 没有候选通过核心稳健可行门禁 | 禁止进入执行清单，展示冲突和干预要求 |

重空调度中，若基线与选中方案使用不同储能预设，结论固定为 `keep_baseline/storage_preset_changed_requires_fixed_storage_recheck`。这不否认联合规划方案可能更好，而是要求固定储能配置重算后，才能发布“仅由调度带来的收益”。

## 4. 输出文件

| 文件 | 主要用途 | 关键内容 |
| --- | --- | --- |
| `OPTIMIZATION_ATTRIBUTION_REPORT.md` | 人员快速阅读 | 决策、KPI 差值、筛选漏斗、主要瓶颈、维度变化和可信边界 |
| `optimization_attribution_summary.json` | 平台摘要和接口读取 | `decision`、归因范围、各明细行数、主要瓶颈、限制和工件路径 |
| `optimization_kpi_attribution.csv` | 比较基线与选中方案 | 指标方向、基线、优化后、差值、改善量、改善比例、解释 |
| `optimization_candidate_decisions.csv` | 解释每个候选为何入选或淘汰 | 可行性、活动场景、Pareto 成员、实质改善、主导约束、储能上下文 |
| `optimization_candidate_funnel.csv` | 展示搜索结果的分层筛选情况 | 总候选、可行候选、活动场景可行候选、实质改善候选、Pareto 候选和选中候选 |
| `optimization_bottlenecks.csv` | 定位限制优化的主要因素 | 作用域、瓶颈类型和位置、出现次数、影响量、是否阻断、证据 |
| `optimization_dimension_attribution.csv` | 观察变化发生在哪里 | 列车时刻、15 分钟时间窗、区段、供电资源、储能设备和问题供电臂等维度 |

漏斗各阶段均以同一批总候选独立统计，不应把相邻两行误读为严格顺序淘汰过程。

## 5. KPI 口径

`improvement` 始终遵循“正值表示改善”：对于越低越好的指标等于“基线减优化后”，对于越高越好的指标等于“优化后减基线”。`optimized_minus_baseline` 始终只是算术差值。

`battery_charge_kwh`、`battery_discharge_kwh` 和 `final_soc_kwh` 属于能量账本状态，其变化不单独称为收益。主要节能判断应查看 `effective_regen_loss_kwh`、`grid_kwh`、`wasted_kwh`、`recovered_energy_kwh` 和相关约束违反量。

## 6. 瓶颈和稳健性口径

运行图优化的瓶颈来自候选能量问题、供电臂、资源冲突和汇总约束。重空调度的瓶颈来自选中方案的稳健场景诊断和基线/选中方案约束指标。

核心场景失败标记为 `selected_candidate_core` 且 `blocking=true`，会阻止方案进入生产采用。非核心压力场景失败标记为 `selected_candidate_non_core_stress` 且 `blocking=false`，用于提示风险，不冒充核心不可行。

## 7. 维度归因边界

报告可直接给出每列车首发、终到和累计停站变化；每 15 分钟牵引、再生、购电、弃能和储能充放电变化；每区段、供电资源、储能区段和列车的物理运行弧能量变化；每台储能设备评价窗末 SOC 变化；以及每个供电臂的能量问题变化。

运行弧 `energy_kwh` 是列车物理能量：正值作为牵引，负值绝对值作为再生。它不是供电结算购电量，也不是单车收益。

供电臂和储能是共享资源，系统级购电或弃能改善不能按比例直接分摊到单列车。若论文或平台必须给出单车边际贡献，应增加“移除一列车或冻结其调整后重新结算”的反事实实验；当前报告明确标记为不可识别，不生成伪精确分摊。

## 8. 当前验证样例

运行图规则样例位于 `paper/experiments/optimization_attribution_current/timetable_rule/`，包含 8 个候选、7 个硬约束可行候选和 1 个 Pareto 候选；当前结论为 `keep_baseline/no_material_energy_improvement`。

固定储能重空调度样例位于 `paper/experiments/optimization_attribution_current/dispatch_fixed_storage/`，包含 8 个核心稳健可行候选；当前结论同样为 `keep_baseline/no_material_energy_improvement`。报告含列车、区段、供电资源、储能设备和时间窗明细，并把非核心压力场景失败保留为非阻断风险。
