# 角色与模块权限矩阵

## 设计边界

- 本矩阵覆盖管理后台、碳核算、数据采集、统计分析、月度分析、报告、不确定性分析、大屏、重空协同、单列车能量回收和碳排放趋势预测。
- `admin` 与有效的管理员角色在服务端获得完整权限；`company_admin` 通过菜单权限表获得全部 `carbon:*` 和 `goview:*` 权限。
- 业务角色遵循最小权限原则。只读角色不获得维护、删除、训练或生成权限，操作角色不获得系统授权权限。
- 数据范围仍由 `sys_role.data_scope`、用户部门和采集范围共同约束。拥有菜单权限不等于可以越过数据范围。
- 迁移不创建示例账号、不设置密码，也不修改现有用户与角色的绑定关系。岗位范例写在角色备注中，管理员可按实际人员分配角色。

管理员识别兼容迁移库中的角色名称：启用的 `系统管理员`、`超级管理员`、`平台管理员`、`公司级系统管理员`、`公司管理员`，以及标准/历史英文角色键（含 `admin`、`company_admin`、`system_admin`、`platform_admin`、`super_admin` 及其无下划线别名）均按平台管理员处理。停用角色不获得管理员权限；昵称本身不会授予权限。所有已登录用户仍可读取趋势预测数据，预测写操作继续按具体权限校验。

## 角色范例

| 角色键 | 角色名称 | 数据范围 | 主要模块与操作 | 岗位范例 | 明确不授予 |
| --- | --- | --- | --- | --- | --- |
| `admin` | 系统管理员 | 全部数据 | 所有系统管理、碳业务和 GoView 操作 | 平台最高管理员 | 无；应严格控制账号数量 |
| `common` | 普通角色 | 本人 | 登录、个人中心 | 仅维护本人资料的普通用户 | 所有碳业务模块 |
| `company_admin` | 公司级管理员 | 全部数据 | 所有碳业务、专职模块和大屏设计 | 总部碳管理平台主管 | 无；不建议用于日常数据录入 |
| `region_admin` | 地区管理员 | 本部门及下级 | 模型、参数、采集、核算、统计、报告、分析、预测、重空协同、单列车、范围和日志 | 原平分公司系统管理员 | 重空项目删除、GoView 设计 |
| `department_admin` | 部门管理员 | 本部门及下级 | 部门数据录入/审核、报告维护、只读分析、范围维护 | 供电部部门管理员 | 全局模型配置、任务执行、报告生成/删除 |
| `carbon_accountant` | 碳核算员 | 本部门及下级 | 模型和核算参数、核算结果、统计、报告生成、不确定性分析、预测训练和预测生成 | 安全环保部碳核算专员 | 数据审核锁定、系统授权、任务删除 |
| `carbon_data_entry` | 数据录入员 | 本部门 | 活动数据录入/提交、统计查看、报告查看、预测历史数据维护 | 月度能耗填报人员 | 审核锁定、模型训练、报告生成 |
| `carbon_reviewer` | 数据审核员 | 本部门及下级 | 数据审核/锁定、报告校验、预测异常复核、日志查看 | 分公司数据复核人员 | 原始数据录入、模型训练、报告删除 |
| `carbon_auditor` | 审计查看员 | 全部数据 | 核算、统计、月度分析、报告、不确定性、预测、重空协同、单列车和日志的只读查看/下载 | 内控审计人员 | 所有写入、审核、训练和生成操作 |
| `screen_operator` | 大屏运维员 | 全部数据 | 碳排放大屏查看/维护、GoView 项目/模板/组件/数据源维护 | 信息化大屏运维人员 | 核算、报告、预测和业务数据修改 |
| `electricity_collector` | 供电采集员 | 本部门及下级 | 电表、采集点和采集范围维护 | 站区供电抄表人员 | 核算模型、报告、分析和系统管理 |
| `energy_operator` | 重空协同操作员 | 本部门及下级 | 重空协同数据版本、任务创建/查询/取消、工件下载 | 运输调度优化人员 | 项目对照和任务删除 |
| `single_train_operator` | 单列车操作员 | 本部门及下级 | 单列车数据版本、任务创建/查询/取消、工件下载 | 机辆能耗分析人员 | 其他碳业务和系统管理 |
| `prediction_analyst` | 趋势预测分析员 | 本部门及下级 | 趋势预测查看、模型训练、预测生成，以及统计/月度分析/报告查询 | 碳排放预测分析人员 | 历史数据直接修改、异常审核、系统授权 |

## 模块覆盖

| 模块 | 管理角色 | 日常操作角色 | 只读/审核角色 |
| --- | --- | --- | --- |
| 模型与核算参数 | `admin`、`company_admin`、`region_admin` | `carbon_accountant`、`electricity_collector` | `department_admin`、`carbon_reviewer` |
| 人工数据录入与采集 | `admin`、`company_admin`、`region_admin`、`department_admin` | `carbon_data_entry`、`electricity_collector` | `carbon_reviewer`、`carbon_auditor` |
| 核算结果与统计查询 | `admin`、`company_admin`、`region_admin` | `carbon_accountant` | `department_admin`、`carbon_data_entry`、`carbon_reviewer`、`carbon_auditor`、`prediction_analyst` |
| 月度能耗统计分析 | `admin`、`company_admin`、`region_admin` | `carbon_accountant`、`prediction_analyst` | `department_admin`、`carbon_auditor` |
| 碳排放报告 | `admin`、`company_admin`、`region_admin` | `carbon_accountant` | `department_admin`、`carbon_data_entry`、`carbon_reviewer`、`carbon_auditor`、`prediction_analyst` |
| 不确定性分析 | `admin`、`company_admin`、`region_admin` | `carbon_accountant` | `department_admin`、`carbon_auditor` |
| 碳排放大屏/GoView | `admin`、`company_admin` | `screen_operator` | 具有 `carbon:screen:view` 的业务角色 |
| 重空协同 | `admin`、`company_admin`、`region_admin` | `energy_operator` | `department_admin`、`carbon_accountant`、`carbon_auditor` |
| 单列车能量回收 | `admin`、`company_admin`、`region_admin` | `single_train_operator` | `department_admin`、`carbon_accountant`、`carbon_auditor` |
| 碳排放趋势预测（查询页面） | 所有已登录用户 | 无（查询不需要角色菜单权限） | 无；训练、重新预测、异常复核和数据写入仍按 `prediction_analyst`/`carbon_accountant` 等写权限校验 |
| 权限、范围和日志 | `admin`、`company_admin`、`region_admin` | `department_admin`、`electricity_collector`（仅范围） | `carbon_auditor` |

## 项目内任务范例

以下范例对应当前项目中的真实菜单和接口，用于上线后逐角色验收；范例只说明岗位职责，不会自动创建测试账号。

| 角色 | 页面任务 | 允许的典型操作 | 验收接口 |
| --- | --- | --- | --- |
| `energy_operator` | 重空协同 | 上传数据版本、创建/取消任务、下载工件 | `/carbon/energy`、`carbon:energy:run` |
| `single_train_operator` | 单列车能量回收 | 上传数据版本、创建/取消回收任务、下载结果 | `/carbon/singleTrain`、`carbon:singleTrain:run` |
| `prediction_analyst` | 碳排放趋势预测 | 查看历史和预测、训练模型、生成预测 | `/carbon/prediction`、`carbon:prediction:model`、`carbon:prediction:forecast` |
| `carbon_accountant` | 核算与报告 | 核算、统计查询、报告和不确定性分析 | `/carbon/statistics`、`/carbon/report`、`carbon:uncertainty:view` |
| `carbon_data_entry` | 人工数据录入 | 录入、提交活动数据；可查看预测历史 | `/carbon/data`、`carbon:prediction:data:edit` |
| `carbon_reviewer` | 数据质量审核 | 审核/锁定数据、复核预测异常 | `/carbon/data`、`carbon:prediction:review` |
| `screen_operator` | 碳排放大屏 | 维护大屏项目、模板、组件和数据源 | `/carbon/screen`、`goview:*` |

趋势预测模块采用“读权限与写权限分离”策略：只要用户已登录，主系统菜单、历史数据、组织、模型、任务和预测结果等 `GET` 页面正常展示；训练、重新预测、异常复核、数据录入、因子和规则维护等写操作仍按上表权限拒绝未授权账号。前端的 `publicRead` 只负责显示入口，不能替代后端鉴权。

## 上线后的分配方式

1. 在“系统管理 > 用户管理”中选择真实用户，不创建共用账号。
2. 按岗位选择一个主业务角色；确有跨岗需求时再叠加专职角色。
3. 校对用户所属部门。地区、部门、核算、录入、审核和专职角色的数据范围都依赖部门树。
4. 对采集人员继续维护采集范围；菜单权限不会替代采集范围授权。
5. 重新登录以刷新令牌中的权限集合，然后验证菜单、查询范围和写操作。

角色和权限的幂等迁移位于 `sql/carbon-role/V1__complete_module_roles.sql`。重复执行只会重建这些托管角色的 `carbon:*`/`goview:*` 授权，不会删除原生 RuoYi 权限，也不会改动用户角色关系。
