# 异常与极端输入测试总报告

- 总状态：`FAIL`
- 测试层：6
- 可枚举案例/专项：204
- 失败测试层：1
- 随机案例指纹：`3e51c3b6e914f9e5432cfc9a0f543e70f12cd5ce1bb71c767dff8089d9e9b6ac`

| 测试层 | 案例/专项数 | 范围 | 状态 | 详细结果 |
| --- | ---: | --- | --- | --- |
| `static_data_anomalies` | 29 | 静态数据文件、拓扑、车辆、储能和跨表引用 | PASS | `static_data/SYNTHETIC_DATA_ANOMALY_REPORT.md` |
| `platform_parameter_anomalies` | 49 | 五类任务的结构、数值、枚举、路径和设备状态 | PASS | `platform_parameters/PLATFORM_PARAMETER_ANOMALY_REPORT.md` |
| `realtime_state_anomalies` | 40 | 实时字段、时钟、顺序、断流、设备和滚动恢复 | PASS | `realtime_state/REALTIME_STATE_ANOMALY_MATRIX_REPORT.md` |
| `core_extreme_scenarios` | 10 | 空输入、零/满SOC、零效率、极大/极小有限量和多设备隔离 | PASS | `core_extremes/ALGORITHM_ROBUSTNESS_CHECKS.md` |
| `random_differential` | 70 | 能量桶、时间切片、资源重叠和Pareto独立参考差分 | PASS | `random_differential/RANDOM_SYNTHETIC_DIFFERENTIAL_REPORT.md` |
| `deep_guard_scripts` | 6 | 核心构造器、数据导入、供电臂、资源、扰动回放和数据库适配器 | FAIL | `component_logs/` |

## 判定

只有六个测试层全部通过时，总状态才为PASS。异常输入必须在进入计算前拒绝；合法边界和极端有限值必须保持能量守恒、数值有限和设备隔离；随机案例必须与独立参考实现一致。

## 边界

本报告验证当前软件合同中的异常处理和已枚举极端场景，不证明正式工程参数真实，也不替代目标数据库、网络、中间件和现场设备的压力及故障联调。
