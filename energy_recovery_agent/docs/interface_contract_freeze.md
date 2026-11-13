# 平台数据库接口契约冻结说明

冻结日期：2026-09-09  
冻结版本：`1.3.1`  
状态：`frozen`

## 1. 冻结结论

平台后端与算法数据库工作进程之间的逻辑接口已经冻结。机器可读权威入口为 `database/interface_contract_freeze.json`，核验命令为：

```powershell
python run_project.py verify-interface-contract
```

冻结表示平台可以按当前数据库、任务、状态和结果语义开展界面及后端开发。它不表示目标环境数据库联调已经完成，也不规定 REST URL、HTTP 方法、RPC 框架、登录鉴权或页面布局；这些属于平台实现层，应映射到本合同而不改变其业务语义。

## 2. 冻结边界

| 项目 | 冻结内容 |
| --- | --- |
| 数据库 | PostgreSQL 16及以上，`carbon_emissions` 数据库，`energy_recovery` Schema |
| 表命名 | 全部业务表使用 `simulation_` 前缀 |
| 输入方式 | 已发布不可变数据版本、任务参数、运行时冻结快照 |
| 输出方式 | 关系结果、完整工件和最终状态在受控事务中写入 |
| 时间与单位 | 绝对时间UTC `timestamp with time zone`；相对时间秒；km、t、kN、kW、kWh |
| 任务标识 | `run_id` 为平台查询和结果关联的唯一任务标识 |
| 幂等 | 项目范围内 `idempotency_key`；同键同请求返回原任务，同键异请求拒绝 |
| 工作进程 | 租约令牌、心跳、过期回收、最大尝试次数、旧租约拒绝 |

## 3. 冻结任务

| `run_type` | 必需任务参数 | 主要可选参数 | 主要输出 |
| --- | --- | --- | --- |
| `dispatch` | 无 | 能量场景、目标模式、搜索规模、重空数量、相位、间隔、窗口、结算步长 | KPI、能量时间片、运行弧、候选、场景和冲突 |
| `timetable_audit` | `timetable_relative_path` | `strict_visualizations` | 审查摘要、运行弧、能量时间片、供电臂结算、问题与建议 |
| `timetable_optimization` | `timetable_relative_path` | 模式、调整范围、种群、代数、交叉/变异率、种子 | 优化决策、候选、Pareto集、场景结果和归因工件 |
| `rolling_rescheduling` | 无 | 求解规模、恢复/安全重试、分设备状态或历史扰动文件 | 逐周期提交状态、安全动作、恢复结果和回放工件 |
| `joint_parameter_robustness` | `parameter_ranges_relative_path` | 重空数量、间隔、相位、结算步长 | 参数场景、逐组合结果、最差场景和稳健结论 |

完整参数白名单、必需项和扩展结构以 `database/io_mapping.json` 为准。未列入白名单的字段、未知枚举、非有限数和违反范围的值必须拒绝，不能静默忽略。滚动任务的 `disturbance_history_relative_path` 与 `storage_devices` 互斥；联合参数区间和历史扰动文件必须属于本次已发布版本并进入冻结快照。

## 4. 状态与决策语义

任务状态固定为：

```text
pending -> validating -> running -> succeeded
                              \-> failed
pending/validating/running    \-> cancelled
validating/running --租约过期且可重试--> pending
validating/running --达到尝试上限--> failed
```

终态为 `succeeded`、`failed`、`cancelled`。终态不得回退；平台只有在 `succeeded` 时读取本 `run_id` 的结果，失败任务不得展示其他任务的旧结果。

优化决策固定为：

| 值 | 页面和业务语义 |
| --- | --- |
| `optimize` | 存在通过约束和改善门槛的候选，可进入人工审查 |
| `keep_baseline` | 没有足够证据替换基线，继续采用原运行图 |
| `no_feasible_solution` | 没有通过核心可行门禁的方案，不得强行采用最低目标值候选 |

滚动提交状态 `withheld_infeasible` 表示必须扣留新增发车，不得作为可下发计划。`committed_infeasible_experiment_only` 只能用于实验，不得进入生产执行。

## 5. 平台逻辑操作

冻结的逻辑操作包括：数据版本发布、任务创建、心跳、过期回收、取消、状态查询、摘要查询、运行图明细、优化明细、滚动控制时间线、历史扰动回放结果、联合参数稳健性结果和工件下载。完整操作名称、必需字段、读写表和返回字段见 `database/platform_api_contract.json`。

平台可以自行设计 REST 或 RPC 包装，但必须满足：

- 创建任务返回 `run_id` 和状态；
- 状态查询返回状态、时间、尝试次数、租约诊断、错误信息、输入/结果哈希和状态事件；
- 工件下载使用 `(run_id, relative_path)` 定位，并执行权限校验和审计；
- 页面不得提交任意表名、SQL、绝对文件路径或白名单外算法参数；
- 列表查询不得批量读取工件 `bytea content`。

## 6. 冻结文件

冻结清单记录以下内容的精确版本和 SHA-256：

- 数据库约定 `database/database_contract.json`，版本 `1.8`；
- 平台逻辑操作 `database/platform_api_contract.json`，版本 `1.11`；
- 输入、参数和结果映射 `database/io_mapping.json`，版本 `1.12`；
- 原型字段映射 `docs/prototype_backend_contract.json`，版本 `1.0`；
- 数据库交付清单、`001-007` 迁移、五类任务示例和扩展输入模板。
- 求解资源预算实现及说明，冻结版本 `1.1.0` 新增；该变更只增加部署档位和结果审计工件，不增加平台业务请求字段。
- 历史扰动执行语义在冻结版本 `1.2.0` 中升级：回放合同 `1.2` 可执行取消、加车、资源封锁和动态供电限值；旧 `1.0/1.1` 输入仍保持原阻断语义。
- 冻结版本 `1.3.0` 将回放合同升级到 `1.3`：方向专用临时限速按 `forward/reverse` 执行；`1.2` 及以下的同类事件继续阻断，避免静默改变历史复算。
- 冻结版本`1.3.1`补充部署、平台、worker和只读账号分离验收入口；五类任务字段、枚举、状态、单位和结果语义不变。

历史迁移文件不可原地修改。数据库结构变化必须新增迁移；已冻结文件内容变化而未更新版本和冻结清单时，CI会失败。

## 7. 兼容与变更规则

| 变更级别 | 允许范围 |
| --- | --- |
| Patch | 文字澄清或不改变字段、枚举、约束和语义的缺陷修复 |
| Minor | 向后兼容地新增可选字段、查询或结果工件 |
| Major | 删除/重命名字段，收紧输入，改变单位、默认值、状态或结果语义 |

任何变更都必须先记录原因和调用方影响，再更新机器契约及版本，提供迁移或兼容期，重新生成冻结哈希，并通过契约检查、数据库集成测试和五类任务验收。不能仅修改代码白名单、SQL或文档中的一处。

## 8. 当前验收边界

冻结检查能够证明仓库内合同文件未漂移，任务白名单与映射一致，DDL包含冻结枚举，结果映射目标表存在，五类示例可以通过参数校验。正式上线仍需平台团队完成目标数据库部署、接口包装、权限、TLS、并发、备份恢复和五类任务端到端签字。
