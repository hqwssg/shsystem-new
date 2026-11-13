# 求解资源预算与降级策略

更新时间：2026-09-09

## 1. 目标与边界

数据库工作进程现在为每类算法任务设置独立墙钟预算。预算到期会终止当前算法子进程，避免任务无限占用工作进程；只有搜索型任务允许在超时后用更小搜索预算再尝试一次。超时表示“在给定计算时限内未完成”，不表示运行图或资源模型不可行。

资源档位由算法部署方在工作进程启动时选择，不属于平台业务参数，也不会改变数据版本、运输任务、扰动场景或正式参数区间。默认档位为 `standard`。

## 2. 主尝试墙钟预算

| 任务类型 | quick | standard | fine | 超时后动作 |
| --- | ---: | ---: | ---: | --- |
| `dispatch` | 480秒 | 900秒 | 1200秒 | 降为4种群、1代、quick搜索档，最多再运行480秒 |
| `timetable_audit` | 120秒 | 300秒 | 600秒 | 不降级；审查范围不能缩减 |
| `timetable_optimization` | 180秒 | 480秒 | 900秒 | 改用规则模式、候选上限60，最多再运行180秒 |
| `rolling_rescheduling` | 300秒 | 600秒 | 900秒 | 降为2种群、1代、关闭额外安全重试，最多再运行300秒 |
| `joint_parameter_robustness` | 600秒 | 1200秒 | 1800秒 | 不降级；联合参数与扰动组合不能偷减 |

以上数值来自当前合成数据与16列车以内的工程基准，只是上线前的软件默认值，不是正式生产SLA。正式数据、目标服务器和并发配置到位后，应按相同口径重新测量并调整。

工作进程一次只领取并执行一个任务，因此单进程并发上限为1。内存、CPU核数和整个服务的工作进程数量依赖目标操作系统与部署平台，必须由 Windows 服务管理器、容器或作业调度器设置硬限制；当前代码不声称提供跨平台内存硬隔离。

## 3. 降级安全规则

- 主尝试正常完成后直接采用，不额外重复运行低档搜索。
- 只有墙钟超时触发降级；程序异常、非零退出和输入错误直接失败，不能用降级掩盖缺陷。
- 降级只减少搜索工作量，不减少列车、运行图记录、联合参数组合或扰动事件。
- 滚动重调度即使降级，仍执行核心稳健可行性与提交门禁；不可行候选仍被扣留。
- 所有尝试均超时时任务进入 `failed`，错误信息说明预算内未完成；平台不得显示为“无可行解”。

## 4. 结果与平台展示

成功任务新增工件 `solver_resource_report.json`，其中包含：

- `resource_profile`：部署时选择的资源档位；
- `attempts`：每次尝试的名称、墙钟上限、实际耗时、状态、参数覆盖和返回码；
- `degradation_applied`：是否采用了降级结果；
- `selected_attempt` 与 `effective_parameters`：最终结果来自哪次尝试、实际使用了哪些参数；
- `timeout_is_infeasibility=false`：固定声明超时不能解释为不可行。

平台在 `degradation_applied=true` 时可以显示“已在受限搜索预算下完成”，但结果是否可采用仍以 `optimization_decision.action`、核心稳健可行性和滚动提交状态为准。资源报告是审计工件，不替代业务结果表。

## 5. 部署与复核

常驻工作进程：

```powershell
python tools/run_database_worker_loop.py --resource-profile standard
```

也可设置环境变量 `SIMULATION_WORKER_RESOURCE_PROFILE=quick|standard|fine`。单次探针使用：

```powershell
python -m database.cli worker-once --resource-profile standard
```

相关实现位于 `database/solver_budget.py` 和 `database/worker.py`；数据库集成 smoke 覆盖策略结构、真实子进程超时终止、调度降级参数和资源报告持久化。
