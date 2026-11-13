# 算法极端场景、分辨率和复现检查

## 参数区间检查

当前已有两层工具：

- `tools_energy_sensitivity_scan.py --only-interval` 用于储能参数的快速逐项/角点诊断；
- `python run_project.py benchmark-joint-parameter-robustness` 用于车辆动力学、储能、电气限制与运行扰动的联合稳健评价。

联合评价的合同、场景设计、逐组合输出和结论边界见 `joint_parameter_robustness.md`。它报告“已测试离散联合场景稳健”，不宣称连续参数区间已获数学证明。

运行 tools_energy_sensitivity_scan.py --only-interval，可围绕当前规划储能值执行容量、充放电功率和效率的区间角点组合，并输出 outputs/parameter_interval_scan/energy_sensitivity_summary.json。该检查用于识别结果范围和稳定性，不把区间边界当作正式设备参数。区间可行性必须先区分资源模板可行性；若所有角点共享同一资源冲突，结论标记为 blocked_by_baseline_resource_infeasibility，不能解释成储能参数导致的物理不可行。

工具：`tools/algorithm_robustness_checks.py`  
测试：`tests/smoke/verify_algorithm_robustness_checks.py`

## 检查内容

- 空功率序列、无再生、零储能、满 SOC、零效率和不可用供电臂等退化场景；
- 精确功率限值、极大/极小有限能量及多储能区段隔离；
- 1 秒与 10 秒结算步长在边界对齐样本上的结果一致性；
- 固定随机种子生成同一功率序列后的确定性重放。

## 最近结果

三类检查均通过。10项极端场景没有出现储能虚假充放电、非有限结果、微量能量丢失或设备SOC串扰；1 秒/10 秒结算的 7 项能量指标差异均为 0；确定性重放的 8 项指标差异均为 0。

## 运行

```powershell
python tools/algorithm_robustness_checks.py --output-dir outputs/algorithm_robustness_checks
```

结果写入 `algorithm_robustness_summary.json` 和 `ALGORITHM_ROBUSTNESS_CHECKS.md`，并已纳入本地 CI。
