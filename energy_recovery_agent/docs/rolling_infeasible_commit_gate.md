# 滚动优化不可行结果提交门禁

更新时间：2026-09-08

## 1. 目的

滚动优化器可能在常规搜索、局部恢复和精确恢复均未得到核心稳健可行解时返回最小违反的诊断候选。该候选用于解释冲突和支持人工决策，但生产系统不能把它当作可执行运行图，也不能让其中的新增发车进入下一轮锁定历史。

本门禁不依赖正式车辆或线路参数。它约束的是软件提交行为，正式数据到位后仍保持有效。

## 2. 判定依据

提交判定不使用 `result.score.feasible`。标称回退可能在正常场景可行，但在其他核心场景失败；因此权威条件是 `selected_scenario_diagnostics` 中所有 `core_for_feasibility=true` 的场景均为 `feasible=true`。缺少核心场景诊断时按不可行处理，采用保守失败原则。

`RollingOptimizationResult` 现在区分：

| 字段 | 含义 |
| --- | --- |
| `schedule` | 名义计划候选 |
| `execution_schedule` | 叠加当前观测晚点后的候选执行运行图；不可行时仅供诊断 |
| `committed_execution_schedule` | 经过门禁后真正生效的运行图，SOC结算只能使用它 |
| `core_robust_feasible` | 所有核心场景是否共同可行 |
| `commit_status` | 提交、扣留或实验覆盖状态 |
| `operational_intervention_required` | 是否需要调度员处置 |

## 3. 状态与行为

| `commit_status` | 生产含义 | 新增发车 | SOC结算 |
| --- | --- | --- | --- |
| `committed_robust_feasible` | 核心稳健可行 | 提交执行窗口内决策 | 结算完整已提交运行图 |
| `withheld_infeasible` | 核心场景不可行或诊断不足 | 全部扣留；已发生/显式锁定列车不撤销 | 只结算已发生/锁定列车 |
| `committed_infeasible_experiment_only` | 研究用显式覆盖 | 允许提交以观察冲突传播 | 结算覆盖后的实验运行图 |

生产默认参数 `allow_infeasible_commit_for_experiment=false`。实验覆盖必须由调用方显式设置为 `true`，状态中会持续保留 `operational_intervention_required=true`，不能被解释为可上线方案。

## 4. 多轮状态规则

当状态为 `withheld_infeasible` 时：

1. `executable_*_departures_s` 只允许保留已经显式锁定且落入当前执行窗口的发车；
2. 未锁定的新发车不进入下一轮 `locked_*_departures_s`；
3. 已发生或已锁定的历史运行轨迹保持不变；
4. 滚动时钟继续推进，下一轮根据新观测重新求解；
5. 执行时间片能量和终点SOC使用 `committed_execution_schedule`，不结算被扣留候选。

门禁之后的有限重试、等待新观测、连续失败人工升级和幂等复用由 `rolling_safety_degradation_state_machine.md` 定义。

## 5. 当前端到端验证

固定四轮扰动下关闭恢复级联，并保持生产默认门禁，结果保存在 `paper/experiments/E15_infeasible_commit_gate/`：

| 轮次 | 核心稳健可行 | 提交状态 | 新增重/空发车 | 下一轮影响 |
| ---: | :---: | --- | ---: | --- |
| 1 | 是 | `committed_robust_feasible` | 1/1 | 正常锁定 |
| 2 | 否 | `withheld_infeasible` | 0/0 | 候选H002/E002未进入锁定历史 |
| 3 | 是 | `committed_robust_feasible` | 1/1 | 在未污染历史上重新得到可行解 |
| 4 | 是 | `committed_robust_feasible` | 1/1 | 正常锁定 |

该案例综合门禁和独立产物核验均通过。逐轮记录还证明 `settled_*_departures_s` 与 `committed_*_departures_s` 完全一致。

## 6. 数据库与界面映射

现有数据库不需要新增表：

- `committed_robust_feasible`：按业务决策映射为 `simulation_optimization_decision.action=optimize` 或 `keep_baseline`；
- `withheld_infeasible`：映射为 `action=no_feasible_solution`，界面不得提供自动执行动作；
- `commit_status`、`core_robust_feasible`、`operational_intervention_required` 和 `reason` 写入决策 JSON，并保留完整结果工件；
- `committed_infeasible_experiment_only` 只能出现在实验任务，生产任务应拒绝该配置。

## 7. 验证入口

```powershell
python tests/smoke/verify_rolling_commit_gate.py
python tools/verify_synthetic_rolling_rescheduling_results.py --output-dir paper/experiments/E15_infeasible_commit_gate
python run_project.py smoke
```
