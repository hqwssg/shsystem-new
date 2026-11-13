# 合成数据回归基线与场景覆盖矩阵

正式数据尚未到位时，项目使用固定的合成/混合输入和已有 smoke 测试建立行为基线。该机制只观测现有算法，不修改算法逻辑，也不把合成结果当作正式节能结论。

## 场景矩阵

运行：

```powershell
python tools/synthetic_scenario_matrix.py --output-dir outputs/synthetic_scenario_matrix
```

输出：

- `SCENARIO_MATRIX.md`：场景、预期行为、通过状态、耗时和输出指纹。
- `scenario_matrix.json`：机器可读的完整结果、标准输出/错误尾部和超时信息。

当前 9 个场景覆盖：常规结算、重空储能无直供、能量/SOC 不变量、多储能终端 SOC、零长度列车缓存、运行图资源冲突、非法输入、功率臂查找和滚动优化约束。

静态输入数据包的异常覆盖不并入上述输出指纹基线，独立由 `tools/synthetic_data_anomaly_matrix.py` 执行。该矩阵现有29项，覆盖缺文件、坏JSON、缺列、线路拓扑、车辆物理、储能电气、资源容量和跨表引用，详见 `synthetic_data_anomaly_matrix.md`。

## 回归基线

首次建立或确认基线：

```powershell
python tools/synthetic_regression_baseline.py --output-dir outputs/synthetic_regression_baseline --write-baseline
```

日常检查：

```powershell
python tools/synthetic_regression_baseline.py --output-dir outputs/synthetic_regression_baseline
```

基线严格比较每个场景的返回码、通过状态、超时状态和规范化输出 SHA-256；耗时只记录和展示，不因机器负载差异导致误报。报告文件为 `BASELINE_REPORT.md`，基线数据为 `baseline.json`，最近一次检查为 `latest_check.json`。

## 解释边界

输出指纹变化表示行为或输出文本变化，需要结合代码快照、输入哈希和结果质量审计判断是否为预期修复；它不等同于节能效果变差。正式数据接入后，应复制相同场景定义，替换为正式输入版本，并重新建立独立的正式基线。
