# 数据库平台联调说明

## 1. 各方职责

| 参与方 | 负责内容 | 不负责内容 |
| --- | --- | --- |
| 数据库管理员 | 建库、迁移账号、生产登录账号、TLS、备份恢复、容量监控 | 算法参数含义和结果解释 |
| 平台后端 | 数据版本发布、任务创建、状态轮询、结果查询、工件下载和鉴权 | 修改算法内部文件或直接写结果表 |
| 算法部署 | 部署完整算法项目、启动数据库工作进程、维护同版本依赖 | 平台页面开发和生产账号发放 |
| 业务验收 | 核对输入版本、任务参数、结果语义和是否允许采用 | 绕过质量门禁直接下发方案 |

数据库交付包包含数据库接入层和运维工具，但算法工作进程仍依赖同一版本的完整项目代码。平台不能直接调用内部算法函数，也不能直接修改任务状态或结果表。

平台联调以 `database/interface_contract_freeze.json` 的冻结版本为权威基线。平台自行设计的REST或RPC接口只能包装该逻辑合同；字段、枚举、状态和结果语义的变更必须遵循 `docs/interface_contract_freeze.md` 的版本与兼容规则。

## 2. 标准调用链

1. 平台把一组输入文件发布为不可变数据版本，并保存版本 ID 与内容 SHA-256。
2. 平台按任务类型提交参数和项目内唯一的幂等键，得到 `run_id`。
3. 工作进程通过租约领取任务，冻结输入快照，执行算法并发送心跳。
4. 工作进程在同一事务中写入关系结果、完整工件和最终状态。
5. 平台轮询任务状态；只有 `succeeded` 才读取结果，`failed` 显示本任务错误。
6. 业务人员查看基线、候选、稳健场景和约束解释，再决定是否采用。

## 3. 五类任务与页面用途

| `run_type` | 主要用途 | 页面重点 |
| --- | --- | --- |
| `dispatch` | 重空协同运输方案求解和能量评估 | KPI、列车弧、候选、场景、冲突 |
| `timetable_audit` | 判断现有运行图是否存在问题和节能空间 | 审查结论、能量时间线、供电臂结算、问题建议 |
| `timetable_optimization` | 在审查基础上生成并比较运行图候选 | 是否优化、候选排名、逐车调整、场景稳健性 |
| `rolling_rescheduling` | 扰动后按周期修复并控制能否提交 | 周期状态、提交门禁、安全动作、人工介入 |
| `joint_parameter_robustness` | 在车辆、储能、电气和扰动区间下复核结论 | 参数覆盖、最差场景、稳健结论、失败组合 |

## 4. 状态和结果读取规则

- `pending`、`validating`、`running`：仅显示当前任务状态和时间，不展示历史任务结果。
- `succeeded`：读取本 `run_id` 的摘要、明细和工件。
- `failed`：显示 `error_message` 和状态事件，不回退到同项目旧结果。
- `cancelled`：停止结果轮询。
- 滚动事件 `commit_status=withheld_infeasible`：不得把新增发车计划下发到生产系统。
- 优化决策 `keep_baseline`：基线已经满足门禁或没有证据表明候选更优，并非算法没有运行。
- 优化决策 `no_feasible_solution`：候选未通过硬约束，不能按最小目标值强行采用。

## 5. 接口实现建议

平台后端可以把 `database/platform_api_contract.json` 映射为内部 REST 或 RPC 接口。所有 SQL 使用参数化查询，页面只持有 `run_id`，不接收任意表名、字段名或文件路径。

结果工件列表只读取元数据。下载时使用 `(run_id, relative_path)` 定位，并在服务端完成权限校验、审计和内容返回。禁止在任务列表查询中批量读取 `bytea content`。

推荐轮询节奏为短任务 2至5秒、长任务 10至30秒，并在状态进入终态后停止。具体间隔属于平台策略，不写入算法任务参数。

## 6. 联调完成标准

联调不能只以“任务状态成功”为准。至少应完成：五类任务各一次端到端成功、幂等重试、非法参数拒绝、双工作进程防重复领取、失败任务不残留半套结果、只读账号写入失败、滚动不可行结果不下发、工件下载校验和一致。

逐项签字口径见`docs/database_platform_integration_checklist.md`。自动核验依次使用`tools/database_healthcheck.py`、`tools/verify_target_database_access.py`、`tools/run_database_five_run_acceptance.py`、`tools/platform_task_stress_fault.py`和`tools/verify_database_delivery_package.py`；单独复核已有五任务结果时使用`tools/verify_database_five_run_e2e.py`，且必须提供只读账号连接。
