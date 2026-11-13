# 性能分析与复现

## 工具

使用 `tools/performance_analysis.py` 在独立 Python 子进程中运行 `cProfile`，不修改算法代码、参数默认值或数据。命令后使用 `--` 传入待测命令：

```powershell
python tools/performance_analysis.py `
  --output-dir outputs/performance_analysis_timetable `
  --top 40 `
  -- tests/smoke/verify_timetable_optimizer_nsga2.py
```

工具输出：

- `PERFORMANCE_REPORT.md`：端到端耗时与累计耗时最高函数。
- `summary.json`：机器可读的命令、返回码、Python 版本和热点函数。
- `profile.prof`：原始 `cProfile` 数据，可用 `python -m pstats` 或其他兼容工具复核。
- `stdout.txt` / `stderr.txt`：被测命令的原始输出。

## 当前基准

在当前虚拟数据和本机环境下，`verify_timetable_optimizer_nsga2.py` 的轻量回归基准端到端耗时约 **32.5 s**。累计耗时主要集中在：

1. `timetable_optimizer.optimize_timetable` / `evaluate_candidates`；
2. `optimize_timetable_nsga2` 与 `evaluate_genome_population`；
3. `timetable_energy_audit.evaluate_scenario_time_slices`；
4. `energy_settlement.settle_energy_bucket_group`。

同一环境下，`verify_energy_scenarios.py` 端到端耗时约 **3.3 s**；其中包含运行图审查和 10 秒结算回退路径，适合用于快速回归。

这只是回归基准，不是正式生产数据的 SLA，也不能单凭耗时判断节能效果。正式数据到位后，应固定代码快照、输入 SHA-256、参数摘要、随机种子和硬件，至少重复 3 次并比较中位数，同时核对输出质量审计结果。

本轮没有对上述热点做算法优化，避免改变计算口径；性能结果仅用于后续定位和容量规划。

2026-09-01：对 `heavy_empty_network_optimizer._arc_infrastructure_attributes` 增加了按里程排序后的提前终止，跳过当前弧终点之后的区段、曲线和供电臂记录。该优化只减少无关相交计算，不改变结果口径；运行图优化 smoke profile 从约 32.5 s 降至约 25.8 s（单次观测，约 20% 改善），合成回归基线和重空网络测试均通过。

2026-09-05：对重空协同调度完成专项剖析和优化。限速及供电臂查询改为有界空间索引，固定/移动闭塞检查改为按列车对预处理停车映射并直接二分轨迹。最终代码的相同2列车受监控命令由约383.17秒降至96.35秒，约3.98倍加速且语义摘要完全一致；4列车由480秒超时改善为185.99秒完成。详细证据见 `docs/dispatch_performance_optimization.md`。

同日完成第四阶段单候选隔离剖析。新增 `python run_project.py profile-dispatch-candidate`，初始化和写盘不计入候选耗时。8列车、5场景候选通过单次结算供电臂解析缓存和单次时空网络弧能量缓存，中位数由 `6.261449 s` 降至 `5.049406 s`，降低 `19.357%`，优化前后语义 SHA-256 完全一致。详细证据见 `docs/dispatch_single_candidate_performance.md`。
