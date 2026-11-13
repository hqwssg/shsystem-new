# 五类任务算法升级记录（2026-10-11）

本次将现有重空协同与能量优化模块同步到 `new_function/algorithm_release_20261010_v1` 中适用于原五类任务的算法。上游版本为 `2026.10.10.1`，本地适配版本为 `2026.10.10.1-mysql-five-tasks`。

## 升级范围

平台为 `shuohuang-main`，算法由该平台当前配置的外部 `energy_recovery_agent` 提供。保留 MySQL `energy_` 数据层、原有任务参数白名单、Excel 中文路径和 Java 调用方式。

| 原任务类型 | 算法入口 |
| --- | --- |
| `dispatch` | `dispatch-case` |
| `timetable_audit` | `audit-timetable` |
| `timetable_optimization` | `optimize-timetable` |
| `rolling_rescheduling` | `benchmark-rolling-rescheduling` |
| `joint_parameter_robustness` | `benchmark-joint-parameter-robustness` |

本次未接入第六类储能规划任务，也未接入独立的 `single_train_energy_optimization-f6d1797`。未同步 `shsystem-main`、`shsystem-main01` 或交付 ZIP；没有运行数据库迁移、替换数据库版本或重算历史任务。

## 算法和适配变化

同步了八个算法文件：`data_ingestion.py`、`train_simulator.py`、`energy_settlement.py`、`run_dispatch_case.py`、`timetable_input.py`、`timetable_energy_audit.py`、`timetable_optimizer.py`、`optimization_attribution.py`。

- 柔性能量传输采用设施最大传输功率和效率；运行基线读取启用状态，未启用的规划设施不参与运行基线。
- 储能结算支持逐设备自放电率和明确的折旧计费口径。最大放电功率允许为零，缺失放电能力的新版样例按零处理。
- 运行图审查报告增加问题和建议的中文分类汇总；优化和归因沿用上游更新后的实现。
- 数据库设备额定参数仍然优先。版本快照中的逐设备自放电率可补充数据库尚未提供的字段，缺省为零；非法数值在生成快照前拒绝。
- 新版 `zone_id` 标识柔性传输设施，不能直接作为储能设备 ID。没有旧储能区段编号时，数据库输入投影按供电臂实际引用的储能编号和里程生成设备记录，继续支持旧格式。缺少逐设备额定资料时沿用聚合储能参数等分的适配方式，并标为规划占位。
- Excel 导入和在线编辑保存新版字段，同时保留已有来源信息和未展示的扩展字段。旧模板缺列时保留原值。浏览器及 Excel 校验均支持新旧编号，允许未启用规划设施与运行区段重叠，继续拦截重复编号、无效里程和启用区段重叠。

## 浏览器输入和输出

五类任务提交表单没有新增必填参数，Java 请求/响应和 MySQL 表结构没有变化。储能版本表增加以下可选列：

| 工作表 | 新增列 | 用途 |
| --- | --- | --- |
| 储能参数 | 折旧计费口径 | `total_throughput`、`charge_energy`、`discharge_energy`，也接受对应中文 |
| 储能区段 | 设施编号、最大传输功率kW | 柔性传输设施身份和功率上限 |
| 储能区段 | 实施状态、运行基线启用 | 区分已实施/规划，以及是否进入运行基线 |
| 储能区段 | 来源文件、来源SHA256 | 保存资料来源 |

逐设备自放电率从版本文件 `storage_devices.json` 的 `self_discharge_rate_per_hour` 读取，数据库额定字段仍优先。它没有被增加为五类任务提交表单的新控件。

原有汇总 JSON、CSV、Markdown 报告和结果投影入口继续使用。新增分类汇总由现有 Markdown 报告组件显示；原始文件中的新增字段保留在任务产物中，不新增数据库结果表。

## 新版数据模板

新版样例放在 `data_templates/five_task_update_20261010/`。该目录在当前线路样例基础上叠加上游电池、柔性传输设施、供电臂和线路元数据资料。

样例电池容量 145 kWh、充电上限 2000 kW、放电上限 0 kW；柔性传输运行基线启用 108–219 km 已实施设施，16–139 km 规划设施不启用。样例仍含部分规划接入和占位电气能力，不能作为正式运营验收数据。

现有 `data/real_shuohuang` 及 MySQL 已发布版本没有覆盖。需要采用新版数据时，通过平台发布新版本；已有版本继续使用各自保存的输入。

## 验证

验证输出全部隔离到工作区 `output/energy_upgrade_20261010/verification/`。本次未连接现有业务数据库。汇总见该目录的 `unit_summary.json`、`smoke_summary.json`、`e2e_summary.json`、`bound_summary.json` 和 `browser_summary.json`。

- Python：50 项测试通过；另一个会连接现有数据库的删除任务测试未执行。
- 算法：16 个现有验证脚本通过，覆盖结算守恒、停放能量、多设备 SOC、数据库参数绑定、列车终态、资源约束、运行图优化、滚动状态和联合参数。
- 五类任务分别以新版隔离样例执行，并使用现有结果投影函数读取产物；另外按数据库设备投影、绑定快照的流程复验五类任务。
- Java：`EnergyCliClientTest`、`EnergyPropertiesTest`、`EnergyAccessGuardTest` 共 12 项通过。
- 浏览器：校验新旧设施编号、启用区段重叠和规划区段编辑；实际报告交给现有 Markdown/CSV 组件解析。前端生产构建输出位于隔离的 `verification/frontend/`。

以上属于代码与隔离样例的回归验证，没有进行带登录会话和真实 MySQL 的整个平台浏览器验收。本地升级标记的 `formal_acceptance` 保持 `false`。

可复跑：

```powershell
python scripts/verify_energy_five_tasks_20261010.py --phase unit
python scripts/verify_energy_five_tasks_20261010.py --phase smoke
python scripts/verify_energy_five_tasks_20261010.py --phase e2e
python scripts/verify_energy_five_tasks_20261010.py --phase bound
node scripts/verify_energy_browser_20261010.mjs
```

上述命令在工作区根目录运行，生成的是隔离验证结果，不会创建平台任务或修改业务数据库。

## 变更清单和回退

完整修改清单及前后 SHA256：工作区 `output/energy_upgrade_20261010/change_manifest.json`；文本差异：`changes.diff`；原文件备份：`backup/`。算法目录的 `LOCAL_ALGORITHM_UPDATE.json` 标记本次本地版本。

如需回退，先停止正在使用本地代码的任务，按清单将 `existed=true` 的文件从 `backup/` 恢复，将 `existed=false` 的新增文件按清单移除，并移除本地升级标记。回退代码不需要改动数据库版本或历史结果。保留升级说明和验证记录可供后续核查。
