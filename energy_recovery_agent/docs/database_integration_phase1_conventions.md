# 数据库集成第一阶段约定

## 1. 阶段结论

数据库集成第一阶段技术约定已经冻结。后续逻辑模型、DDL、数据库适配器和平台接口均以本文件及 `database/database_contract.json` 为基线。

| 项目 | 冻结值 |
| --- | --- |
| 生产数据库名 | `carbon_emissions` |
| 数据库类型 | PostgreSQL 16及以上兼容版本 |
| 字符编码 | UTF-8 |
| 模块Schema | `energy_recovery` |
| 业务表统一前缀 | `simulation_` |
| 标识符风格 | 小写ASCII `snake_case` |
| 应用显示时区 | `Asia/Shanghai` |
| 数据库存储时区 | UTC，字段使用 `timestamp with time zone` |
| 距离/功率/能量 | km、kW、kWh |

生产环境使用数据库名 `carbon_emissions`。开发、测试与生产必须使用隔离的数据库实例或集群；为减少环境差异，各环境可保持相同逻辑数据库名，不能在生产库中运行自动化测试。

## 2. 命名空间

所有本算法模块创建的业务表必须同时满足：

1. 位于 `energy_recovery` Schema；
2. 表名以 `simulation_` 开头；
3. 使用小写ASCII和下划线，不使用中文、缩写混排或大小写敏感标识符。

示例完整名称：

```text
energy_recovery.simulation_project_version
energy_recovery.simulation_run
energy_recovery.simulation_energy_time_slice
energy_recovery.simulation_result_kpi
```

约束与索引统一命名：

| 对象 | 前缀 | 示例 |
| --- | --- | --- |
| 普通索引 | `idx_simulation_` | `idx_simulation_energy_slice_run_time` |
| 唯一约束 | `uq_simulation_` | `uq_simulation_station_version_code` |
| 外键 | `fk_simulation_` | `fk_simulation_station_version` |
| 检查约束 | `ck_simulation_` | `ck_simulation_storage_soc_bounds` |

## 3. 主键和关联规则

- 项目、版本、车站、车辆、运行图、任务、运行、候选等领域实体使用UUID主键。
- 能量时间片、运行弧、冲突日志等高体量明细使用 `bigint generated always as identity`，同时保留 `run_id` 或 `candidate_id` 外键。
- 外键字段使用 `<被引用实体>_id`，不得使用名称或自然文本代替稳定ID。
- 所有基础数据通过 `project_id` 和不可变 `version_id` 隔离；一次算法运行只能引用同一已发布版本的数据。
- 业务版本发布后不原地修改。修订数据必须生成新的 `version_id`。

## 4. 时间与数值规则

- 绝对时间使用 PostgreSQL `timestamp with time zone`，以UTC存储，由平台按 `Asia/Shanghai` 展示。
- 算法内部相对时间使用非负整数秒；写入明细表时同时关联本次运行的绝对起点。
- 公里标、质量、力、功率和能量分别使用 km、t、kN、kW、kWh，不在数据库中混存不同单位。
- 需要结算或比较的数值使用 `numeric`，不使用数据库浮点类型保存正式汇总值。
- JSONB只用于来源说明、输入哈希、可变诊断详情等扩展字段；需要筛选、关联或统计的核心字段必须结构化建列。

## 5. 数据可信状态

所有版本化输入必须记录 `data_status`：

| 值 | 含义 |
| --- | --- |
| `official` | 甲方或权威系统正式发布数据 |
| `derived_from_official` | 可追溯地由正式数据计算或整理得到 |
| `planning_placeholder` | 规划值或工程占位，不得形成正式工程结论 |
| `synthetic` | 测试或算法验证使用的合成数据 |

当前 `data/real_shuohuang/` 导入数据库时必须标记为 `planning_placeholder` 或按字段来源使用更严格状态，不能整体标记为 `official`。

## 6. 任务状态与事务边界

算法任务状态固定为：

```text
pending -> validating -> running -> succeeded
                              \-> failed
pending/validating/running    \-> cancelled
validating/running --租约过期且未达尝试上限--> pending
validating/running --租约过期且达到尝试上限--> failed
```

- 平台创建任务和冻结输入快照；算法工作进程不得修改已发布基础数据。
- 算法按 `run_id` 一次性读取不可变输入快照，在内存中完成计算，禁止在时间步循环中频繁查询数据库。
- 明细结果批量写入，最终候选、决策、KPI和任务成功状态在受控事务中提交。
- 平台创建重试使用项目内唯一 `idempotency_key`；同键同请求返回原 `run_id`，同键不同请求拒绝。
- 工作进程使用带心跳的限时租约；所有关键写回必须匹配当前租约令牌，旧进程不得覆盖新状态。
- 写入失败时不得留下 `succeeded` 状态；成功结果只允许相同结果哈希幂等重试。
- 状态主表更新和不可变状态事件在同一事务提交，`state_version` 单调递增。
- 每次运行必须记录 `version_id`、输入哈希、代码版本、随机种子、开始时间和结束时间。

## 7. 数据库角色和权限

| 角色 | 权限边界 |
| --- | --- |
| `simulation_migrator` | 创建和升级Schema、表、索引及约束；仅部署时使用 |
| `simulation_platform` | 维护版本化输入、创建和取消运行任务；不写算法结果 |
| `simulation_worker` | 读取已冻结输入，更新自身任务状态并写入算法结果；不执行DDL |
| `simulation_readonly` | 查询允许展示的任务状态、KPI和结果明细 |

数据库连接凭据不得写入仓库。应用统一通过环境变量 `SIMULATION_DATABASE_URL` 取得连接串；除本地开发外必须使用TLS，并由平台密钥管理能力提供凭据。

## 8. 数据保存与删除

- 项目主数据和发布版本不自动物理删除，停用通过状态字段表达。
- 任务元数据、KPI、最终决策和审计信息至少保存至项目生命周期结束。
- 能量时间片、运行弧等高体量明细默认至少保存365天；平台可制定更长周期。
- 自动清理只能处理已超过保留期且不处于审计、论文实验或验收引用状态的明细。

## 9. 系统责任边界

- 平台界面负责参数录入、权限控制和结果展示。
- 平台后端负责版本发布、任务创建、状态查询和接口编排。
- 算法模块负责读取冻结快照、执行校验与计算、写入结构化结果。
- 数据库负责持久化和一致性，不承载算法核心计算逻辑。
- 图像和大文件优先保存到文件或对象存储，数据库只保存路径、哈希、类型和生成状态。

## 10. 后续阶段完成情况

本约定之后的字段映射、逻辑模型、版本化DDL、数据库输入输出适配器、任务状态机、事务幂等写回、平台接口契约和集成测试均已实现。部署及调用方式见 `database_integration_guide.md`，表级数据字典见 `simulation_program_database_schema.md`。未经变更记录，不得更改数据库名、Schema、`simulation_` 表前缀、主键策略或时间单位。
