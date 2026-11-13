# 性能容量分析

运行：

```powershell
python tools/performance_capacity_analysis.py --output-dir outputs/performance_capacity
```

工具按多个标记值执行同一命令，记录返回码、超时和端到端耗时。默认使用轻量 `verify_energy_scenarios.py`（标记值 1、2、4、8），用于检测启动/基础处理基线；由于该默认命令不含 `{scale}`，不能解读为算法规模扩展。对真实容量趋势应使用带 `{scale}` 的命令模板。

输出：

- `CAPACITY_ANALYSIS.md`：人工可读报告。
- `capacity_summary.json`：机器可读结果。

若要测量特定命令，可在命令中使用 `{scale}` 占位符，例如：

```powershell
python tools/performance_capacity_analysis.py --case 1 --case 2 -- run_project.py dispatch-case --population-size {scale} --generations 1
```

正式数据接入后，应固定代码、输入 SHA-256、随机种子、硬件和重复次数，再比较耗时与结果质量；容量分析本身不构成节能效果结论。
