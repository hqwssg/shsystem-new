# 滚动优化安全降级与恢复状态机

更新时间：2026-09-08

## 1. 目的与边界

提交门禁负责阻止核心稳健不可行方案进入执行历史；本状态机负责门禁之后的生产处置。它复用既有常规搜索、局部恢复和精确恢复求解器，不放宽运输、资源、电气、SOC或服务完整性约束，也不自动取消列车。

默认策略允许每轮执行一次有界增强重试：预测时域扩大1.5倍，种群预算扩大2倍，代数增加1，并启用既有恢复级联；全部参数均有硬上限。重试仍失败时扣留新增发车，等待下一次现场观测。连续两轮不可行时升级为人工调度处置。

## 2. 状态与动作

| 状态 | 进入条件 | 平台动作 |
| --- | --- | --- |
| `normal` | 首次求解即核心稳健可行 | 执行已提交运行图 |
| `recovered_automatically` | 同轮增强重试后可行 | 执行已提交运行图，并保留重试记录 |
| `recovered_after_observation` | 前轮扣留，新观测到达后重新求解可行 | 解除本轮扣留并执行新提交结果 |
| `waiting_for_observation` | 本轮全部有限尝试失败，尚未达到人工升级阈值 | 保持历史锁定，扣留新增发车，等待新观测 |
| `manual_intervention_required` | 连续不可行达到阈值 | 保持历史锁定，禁止自动下发，提示调度员处置 |
| `experiment_only` | 显式允许提交不可行实验结果 | 仅研究使用，生产不得下发 |

## 3. 有界重试与幂等规则

- `max_retries_per_cycle` 默认1，禁止负数；所有重试均结束后才形成最终状态。
- `max_horizon_s`、`max_population_size`、`max_generations` 限制资源增长，状态机不存在无限循环。
- 完全相同的状态、模板、预算和策略请求使用确定性 `request_fingerprint`，控制器直接复用已完成结果，不重复求解和提交。
- 新观测由晚点、SOC及锁定历史共同识别；观测变化后允许重新进入求解流程。
- 只有 `committed_execution_schedule` 参与执行和SOC结算。扣留候选只用于诊断。

## 4. 输出契约

每轮 `RollingOptimizationResult` 增加：

- `safety_state`：当前安全状态；
- `safety_action`：平台下一步动作；
- `safety_attempt_count`：本轮实际求解次数；
- `safety_transition_history`：状态迁移、请求指纹、重试配置、扣留发车及失败核心场景。

同一结构同时写入 `search_diagnostics.safety_state_machine`。滚动基准的 `rolling_cycles.csv` 和 `benchmark_summary.json` 已包含这些字段；当前schema版本为1.7，并同时包含逐储能设备额定参数、运行状态和能量账本。

## 5. 数据库映射

数据库任务类型新增 `rolling_rescheduling`。每轮状态写入 `simulation_rolling_control_event`，主键由运行ID和轮次确定，并通过唯一约束保证幂等。主要字段包括提交状态、安全状态、安全动作、可行性、人工干预标志、尝试次数、请求指纹和完整事件JSON。

最新一轮为 `withheld_infeasible` 时，`simulation_optimization_decision.action` 投影为 `no_feasible_solution`；平台不得生成自动执行按钮。完整原始CSV、JSON和报告仍写入结果工件表。

## 6. 验证入口

当前真实算法组件合成回归保存在 `paper/experiments/E15_safety_state_machine/`。首轮恢复级联被关闭，第2轮初始结果不可行；状态机将时域从7200秒扩大到10800秒、种群从2扩大到4、代数从1增加到2并启用恢复级联，第二次尝试通过核心稳健门禁。最终4轮均可行，状态统计为 `normal=3`、`recovered_automatically=1`，独立验证器全部通过。

```powershell
python tests/smoke/verify_rolling_safety_state_machine.py
python tests/smoke/verify_database_integration.py
python run_project.py benchmark-rolling-rescheduling
python run_project.py benchmark-rolling-rescheduling --disable-recovery --output-dir paper/experiments/E15_safety_state_machine
python tools/verify_synthetic_rolling_rescheduling_results.py --output-dir paper/experiments/E15_synthetic_rolling_rescheduling
python run_project.py smoke
```

正式数据到位后仍需重新确定自动重试预算和连续失败升级阈值；当前默认值属于保守的软件控制策略，不代表现场调度规章。
