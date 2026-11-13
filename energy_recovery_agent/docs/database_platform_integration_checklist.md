# 数据库部署与平台联调验收清单

## A. 环境与部署

- [ ] `python run_project.py verify-interface-contract` 返回 `status=PASS`，并记录冻结版本；
- [ ] PostgreSQL 主版本不低于16，数据库编码为UTF-8；
- [ ] 数据库名为 `carbon_emissions`，业务 schema 为 `energy_recovery`；
- [ ] `001-007` 迁移全部登记且校验和一致；
- [ ] 部署前备份、恢复点和回退负责人已记录；
- [ ] 生产连接启用 TLS，凭据由密钥系统注入；
- [ ] `database_healthcheck.py` 返回 `accepted=true`。
- [ ] `verify_target_database_access.py` 返回`accepted=true`，报告不含连接串或凭据；

## B. 权限

- [ ] 四类 `simulation_*` 角色存在且为 NOLOGIN；
- [ ] 平台登录账号只继承 `simulation_platform`；
- [ ] 算法工作进程只继承 `simulation_worker`；
- [ ] 查询账号只继承 `simulation_readonly`；
- [ ] 只读账号写入测试被拒绝；
- [ ] 非迁移账号执行 DDL 被拒绝。

## C. 数据版本

- [ ] 原始文件和关系投影来自同一不可变版本；
- [ ] 版本包含运行图、历史扰动和联合参数区间文件；
- [ ] 当前占位数据明确标记 `planning_placeholder`；
- [ ] 相同版本和相同内容重复发布幂等；
- [ ] 相同版本代码、不同内容发布被拒绝；
- [ ] 平台保存版本内容 SHA-256。

## D. 任务接口

- [ ] 五类 `run_type` 均可通过平台创建；
- [ ] `run_database_five_run_acceptance.py`使用三个独立登录账号返回`accepted=true`；
- [ ] 未批准参数、越界文件路径和非法枚举被拒绝；
- [ ] 同幂等键同请求返回原 `run_id`；
- [ ] 同幂等键不同请求被拒绝；
- [ ] 两个 worker 不会领取同一任务；
- [ ] 租约心跳、过期回收、最大重试和取消行为符合合同；
- [ ] 旧租约不能冻结输入、写结果或覆盖新任务状态。

## E. 五类结果

- [ ] `dispatch`：KPI、能量时间片、运行弧、候选和场景结果非空；
- [ ] `timetable_audit`：运行弧、能量时间片和供电臂结算非空；
- [ ] `timetable_optimization`：候选和场景结果非空；
- [ ] `rolling_rescheduling`：逐轮控制事件非空且提交门禁状态可解释；
- [ ] `joint_parameter_robustness`：摘要、参数场景和逐组合结果三个工件齐全；
- [ ] 每类成功任务均有输入 SHA-256、结果 SHA-256 和完整状态事件；
- [ ] 关系结果、工件和 `succeeded` 状态在同一事务提交；
- [ ] 人为制造投影错误时任务整体失败，不留下半套结果。

## F. 平台展示

- [ ] 任务状态、失败原因和状态事件可查询；
- [ ] `keep_baseline`、`optimize`、`no_feasible_solution` 显示语义正确；
- [ ] `withheld_infeasible` 不允许下发新增发车；
- [ ] 能量单位、时间单位、时区和小数精度与合同一致；
- [ ] 工件列表不读取大字段内容，下载接口有鉴权和审计；
- [ ] 失败任务不会展示其他任务的旧结果。

## G. 运维

- [ ] worker 由进程管理器托管，具有唯一 ID、自动重启和日志采集；
- [ ] 监控 pending 数量、最老排队时间、失败率、心跳和租约过期；
- [ ] 监控数据库容量、WAL、工件增长和慢查询；
- [ ] 完成备份恢复实操并记录恢复时间；
- [ ] 完成目标并发量压测和工作进程异常演练；
- [ ] 在目标测试库运行`python run_project.py test-platform-tasks`并保存参数、逐操作时延和故障矩阵报告；
- [ ] 正式数据版本上线前重新执行五类端到端验收。

## H. 证据边界

- 本地部署前证据：`outputs/target_platform_predeployment/`与`outputs/database_postgres_segregated_e2e_acceptance_v4/`；
- 目标平台必须生成独立输出目录并记录目标环境、代码版本、迁移版本和执行时间；
- 本地无TLS、信任认证和回环地址结果不得用于勾选目标平台TLS、账号发放、备份恢复或生产负载项目。
