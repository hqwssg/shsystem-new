# 数据库运行状态事务与幂等保障

更新时间：2026-09-08

## 1. 保障目标

本机制保证平台重复提交、多个工作进程并发领取、工作进程崩溃、租约过期、取消与迟到写回时，不会产生重复任务执行权、半份结果或终态覆盖。算法仍从冻结快照一次性加载数据并在内存中计算。

## 2. 分层保障

| 风险 | 保障机制 |
| --- | --- |
| 平台请求超时后重复创建 | 项目内唯一 `idempotency_key`；请求内容计算 `request_sha256` |
| 同键被用于不同参数 | 同键同摘要返回原 `run_id`，同键异摘要抛出状态冲突 |
| 多工作进程领取同一任务 | `FOR UPDATE SKIP LOCKED` 和原子 `pending -> validating` |
| 长任务被误判失联 | 默认300秒租约、60秒心跳续期 |
| 工作进程崩溃 | 过期任务回到 `pending`，由新令牌重新领取 |
| 无限崩溃重跑 | 默认累计3次领取后转为 `failed` |
| 旧工作进程迟到写回 | 冻结、心跳、成功和失败均校验 `run_id + worker_id + lease_token + 未过期` |
| 输入快照被替换 | 同一运行只接受相同 `version_id + input_sha256` 的重复冻结 |
| 结果只写入一部分 | 明细删除、重新投影、工件写入、结果哈希、成功状态和状态事件在同一事务提交 |
| 成功结果被覆盖 | 相同结果SHA-256返回幂等成功，不同结果拒绝 |
| 非法状态跳转 | PostgreSQL触发器校验允许边、终态不可变和 `state_version + 1` |
| 状态变化无审计 | `simulation_run_state_event` 与主状态在同一事务追加，运行内版本唯一 |

## 3. 数据字段

`simulation_run` 新增：

- `idempotency_key`：平台生成的项目内唯一请求键，新任务必填；
- `request_sha256`：版本、任务类型、参数、请求人和代码版本的规范化摘要；
- `attempt_count`：成功领取次数；
- `lease_token`、`lease_expires_at`、`heartbeat_at`：当前执行权；
- `state_version`：每次状态变化严格增加1。

`simulation_run_state_event` 保存前后状态、状态版本、工作进程、当时租约、原因和详情JSON。事件只允许追加，不作为当前状态的替代；当前状态仍以 `simulation_run.status` 为准。

## 4. 状态转换

```text
pending -> validating -> running -> succeeded
   |           |           |
   +-----------+-----------+-> cancelled
               +-----------+-> failed
               +-----------+-> pending  （租约过期、未达尝试上限）
               +-----------+-> failed   （租约过期、达到尝试上限）
```

`succeeded`、`failed` 和 `cancelled` 均为不可逆终态。心跳只更新时间和租约，不改变状态版本。

## 5. 平台调用

```powershell
python -m database.cli create-run `
  --project-code shuohuang-energy `
  --version-code planning-2026-09 `
  --run-type dispatch `
  --parameters-file database/examples/dispatch_parameters.json `
  --idempotency-key platform-request-0001

python -m database.cli worker-once `
  --lease-seconds 300 `
  --heartbeat-interval-seconds 60

python -m database.cli status --run-id <运行ID> --include-events
python -m database.cli recover-expired --max-attempts 3
python -m database.cli cancel-run --run-id <运行ID> --reason operator_cancelled
```

平台对一次业务请求重试时必须复用原幂等键；用户主动发起一次新计算时必须生成新键。不能用参数哈希直接充当永久幂等键，否则同参数的合法新运行会被错误合并。

## 6. 验证

- `tests/smoke/verify_database_integration.py`：事务回滚、请求摘要、SQL守卫、令牌传递、心跳次数和心跳失败终止子进程。
- `tests/integration/verify_postgres_database.py`：专用 PostgreSQL 库中的双连接并发领取、重复创建、异内容冲突、快照冲突、租约回收、旧令牌拒绝、取消、结果幂等和事件版本。
- `tools/platform_task_stress_fault.py`与`tests/integration/verify_platform_task_stress.py`：真实多连接并发创建、幂等突发、领取、心跳、取消、崩溃回收、最大重试、四类旧令牌操作和结果投影中途失败回滚。
- 所有迁移及权限脚本已通过 PostgreSQL AST 解析；真实集成测试只允许连接名为 `carbon_emissions_test` 的专用数据库。

```powershell
$env:SIMULATION_TEST_DATABASE_URL='<carbon_emissions_test连接串>'
python tests/integration/verify_postgres_database.py
```

2026-09-09已在仅监听本机的PostgreSQL 16 `carbon_emissions_test`专用库完成真实集成与三档压力测试。120/500/1000任务、12/24/32并发worker均通过唯一领取、幂等突发、心跳、取消、租约和状态事件门禁；六类故障注入全部通过。测试发现并修复了同一幂等键并发插入时未捕获确定性`run_id`主键竞争的问题。完整结果见`outputs/platform_task_stress_fault_current/`、`outputs/platform_task_stress_fault_500/`、`outputs/platform_task_stress_fault_1000/`及容量对照目录。

上述结果仍不是目标数据库实测。部署前必须在目标测试环境重跑，并在旧工作进程停止后执行迁移006；迁移会为历史任务回填`legacy-<run_id>`幂等键。
