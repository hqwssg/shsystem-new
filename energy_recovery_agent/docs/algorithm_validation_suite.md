# 算法验证套件（五项专项工作）

工具：`tools/algorithm_validation_suite.py`  
测试：`tests/smoke/verify_algorithm_validation_suite.py`

## 覆盖范围

1. **快速/精细评价误差**：对 aligned、跨桶和 mixed 三类功率序列比较 1/5/10/30 秒结算。总发电量和总牵引量必须保持一致；充放电分配在 30 秒粗桶下可能变化，该差异作为敏感性报告，不隐藏。
2. **基线/消融对比**：完整储能、无储能、低容量、低功率和低效率五个变体，检查储能和参数变化方向。
3. **优化器稳定性**：使用 5 个随机种子运行小规模 NSGA-II，检查有效性、候选数量和 Pareto 输出。
4. **储能策略对比**：禁用储能、均衡充放电、保守容量、高效率和终端 SOC 目标五种策略。
5. **供电臂/候选评估性能**：重复 200 个时间序列结算 5 次，记录中位耗时。

## 最近结果

五项均 PASS。优化器 5 个种子全部有效、每次 6 个候选和 1 个 Pareto 结果；快速/精细检查显示 30 秒粗时间桶会因合并充放电事件产生敏感性，1/5/10 秒结果保持一致；性能探针中位耗时约 0.009 秒。

```powershell
python tools/algorithm_validation_suite.py --output-dir outputs/algorithm_validation_suite
```

结果写入 `algorithm_validation_summary.json` 和 `ALGORITHM_VALIDATION_REPORT.md`，并已纳入本地 CI。
