# 运行图优化器

`timetable_optimizer.py` 是当前运行图优化入口。它读取标准化运行图模板，在配置的能量场景下评价运行图调整候选，并导出可选择的 Pareto 候选方案。

## 运行模式

| 模式 | 含义 | 当前用途 |
| --- | --- | --- |
| `rule` | 基于规则生成候选并进行筛选。 | 快速基线模式，可生成整列车时间偏移、停站延长和事件引导的重新定时候选。 |
| `nsga2` | 多目标遗传优化原型。 | 推荐的 Pareto 方案生成模式，在运行图基因种群中搜索并保留非支配方案。 |

## NSGA-II 原型

当前决策变量包括：

- 整列车发车时间偏移，单位为分钟；
- 候选车站的停站时间延长，单位为分钟。

当前优化目标包括：

- 最小化预计弃用再生能量；
- 最小化问题数量；
- 最小化预计电网购电量；
- 最小化运行图总调整量；
- 最小化延误；
- 最小化约束警告数量；
- 将供电臂牵引供电超限和再生吸收超限作为硬约束违反处理。

原型会保留以下运行图有效性检查：停站顺序、里程方向、时间单调性、到发时刻一致性和同方向发车追踪间隔。目前它还不是完整的车站咽喉、会让线、进路锁闭或会让越行顺序优化器。

## 运行命令

规则模式：

```powershell
.\.venv\Scripts\python.exe timetable_optimizer.py data_templates\running_diagram_template.xlsx --mode rule --max-candidates 120
```

NSGA-II 原型模式：

```powershell
.\.venv\Scripts\python.exe run_project.py optimize-timetable --population-size 60 --generations 30
```

小规模验证：

```powershell
.\.venv\Scripts\python.exe tests\smoke\verify_timetable_optimizer_nsga2.py
```

## 输出结果

默认输出目录为：`outputs/timetable_optimizer_nsga2/`。

旧的 `outputs/timetable_optimizer/` 结果目录已视为历史输出，并移动至 `outputs/archive/2026-07-structure-convergence/timetable_optimizer/`。

重要文件如下：

| 文件 | 含义 |
| --- | --- |
| `candidate_summary.csv` | 候选运行图调整汇总，每行对应一个候选。 |
| `candidate_scenario_scores.csv` | 候选在各能量场景下的评分。 |
| `candidate_energy_issues.csv` | 候选能量问题明细，包括场景、供电臂、时间窗口、弃能量和问题原因。 |
| `pareto_candidates.csv` | 按场景归类的非支配可选候选。 |
| `candidate_explanations.csv` | 候选决策角色、主导约束、最差场景问题数量，以及进入或未进入 Pareto 集的原因。 |
| `candidate_timetables/` | 导出的 Pareto 候选运行图 CSV 文件。 |
| `TIMETABLE_OPTIMIZATION_REPORT.md` | 面向人员阅读的运行图优化报告。 |
| `OPTIMIZATION_ATTRIBUTION_REPORT.md` | 是否采用、KPI 改善、候选筛选漏斗、主要瓶颈和维度变化的综合解释。 |
| `optimization_attribution_summary.json` | 供平台读取的归因摘要、决策、范围、限制及工件路径。 |
| `optimization_kpi_attribution.csv` | 基线与选中候选的指标差值和统一正向改善口径。 |
| `optimization_candidate_decisions.csv` | 每个候选入选、淘汰或保留为 Pareto 替代方案的原因。 |
| `optimization_candidate_funnel.csv` | 同一候选集合在可行性、实质改善、Pareto 和选中层面的独立计数。 |
| `optimization_bottlenecks.csv` | 按约束、问题类型和供电臂聚合的瓶颈证据。 |
| `optimization_dimension_attribution.csv` | 列车时刻、供电臂问题等可识别维度的优化前后变化。 |
| `figures/pareto_front.png` | Pareto 前沿散点图。 |
| `figures/candidate_adjustments.png` | 候选调整量对比图。 |
| `figures/scenario_score_comparison.png` | 各场景能量评分对比图。 |
| `generation_log.csv` | NSGA-II 每代指标；仅在 `nsga2` 模式下生成。 |
| `final_population.csv` | NSGA-II 最终种群，包括排序、拥挤距离、基因和目标值；仅在 `nsga2` 模式下生成。 |
| `figures/evolution_progress.png` | NSGA-II 演化过程图；仅在 `nsga2` 模式下生成。 |

## 结果解读

如果基线运行图已经满足零弃能、零检测问题且无需调整，它可能支配搜索结果。此时 Pareto 输出合理地只包含原始运行图作为最佳方案。若要观察更明显的优化行为，应使用包含真实冲突、再生制动与牵引需求重叠效率较低，或包含已确认车站/区间约束的运行图。

供电臂电气超限会输出为 `electrical_constraint_violation_kwh`。该值非零的候选不可行，不能进入 `pareto_candidates.csv`，即使其能量或调整目标更优也一样。

优化器不会静默替用户选择单一业务偏好。`candidate_explanations.csv` 会区分 Pareto 替代方案、可行但被支配的候选和不可行诊断候选。解释来自与候选导出相同的可行性和 Pareto 逻辑，只是解释层，不会改变优化结果。

收益归因报告同样是求解后的只读解释层。其 `improvement` 正值统一表示改善；详细字段、固定储能对照要求和共享资源归因边界见 `optimization_attribution_and_bottleneck_report.md`。

## 后续扩展点

- 向运行图基因中增加会让越行顺序变量；
- 增加车站股道和区间容量修复算子；
- 用经过标定的牵引/制动曲线替换原型能量估计；
- 通过适配器接入正式运行图格式，不修改标准化运行图优化核心。
