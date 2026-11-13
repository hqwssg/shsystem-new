# 参数区间联合稳健性评价

## 1. 目的

本功能用于回答：在正式车辆、储能和供电参数尚未形成单点定值时，同一运行图在一组可追溯参数区间及运行扰动下，核心可行性和能量结论是否稳定。

它不是新的运行图优化器，也不修改候选方案。它固定一张待评价运行图，重新构造不同车辆动力学、储能和供电参数，再叠加既有晚点场景进行联合评价。

## 2. 当前覆盖

区间合同为 `data_templates/joint_parameter_ranges_template.json`，支持15类相对名义值因子：

- 重车质量、空车质量；
- Davis A/B/C 阻力系数；
- 最大牵引力、最大制动力、最大功率；
- 储能容量、最大充电功率、最大放电功率、往返效率；
- 牵引供电上限、再生吸收上限、电网反馈上限。

每个物理参数场景与 `default_scenarios()` 的正常、轻度重/空车晚点及诊断性重/空车晚点组合。质量和阻力增大、能力参数减小构成定向不利角点。

## 3. 场景设计

默认设计包含名义值、定向不利/有利角点、全低/全高角点、每个参数单独取上下边界以及固定种子拉丁超立方内部样本。当前15维模板去重后为39个物理场景，与5个运行扰动形成195个联合组合。

这种方法兼顾边界覆盖、单因素定位和内部取样，但不是对连续参数盒内所有无限取值的数学证明。输出字段 `claim_scope=tested_discrete_joint_scenarios_only`、`continuous_interval_certified=false` 固化了这一边界。

## 4. 运行与输出

```powershell
python run_project.py benchmark-joint-parameter-robustness `
  --parameter-ranges data_templates/joint_parameter_ranges_template.json `
  --output-dir paper/experiments/E13_joint_parameter_robustness
```

主要输出：

| 文件 | 用途 |
| --- | --- |
| `joint_parameter_scenarios.csv` | 逐场景、逐参数记录上下界、名义值和实际因子 |
| `joint_robustness_results.csv` | 逐物理参数场景×运行扰动记录可行性、冲突、购电、弃能、充放电和SOC |
| `joint_robustness_summary.json` | 覆盖数量、稳健判定、最差组合、输入SHA-256和结果语义SHA-256 |
| `JOINT_PARAMETER_ROBUSTNESS_REPORT.md` | 面向评审的中文摘要 |

`tested_joint_robust=true` 只表示全部已测试核心组合可行；诊断性强晚点失败不会改变核心判定，但会保留在逐组合结果中。

## 5. 数据库调用

平台提交 `run_type=joint_parameter_robustness`，并通过必填参数 `parameter_ranges_relative_path` 引用已发布数据版本和冻结运行快照中的区间JSON。工作进程只允许读取快照内逻辑路径，完整结果作为 `simulation_result_artifact` 保存，摘要和采用判断进入通用结果表。

正式数据到位后，应把区间改为经确认的测量误差、设备容差或运行波动范围，修改 `evaluation_code` 和数据版本后重跑，不应覆盖现有规划情景证据。

## 6. 验证

快速合同测试：

```powershell
python tests/smoke/verify_joint_parameter_robustness.py
```

长耗时物理链路测试：

```powershell
python tools/run_long_dispatch_tests.py --test joint_parameter_robustness
```
