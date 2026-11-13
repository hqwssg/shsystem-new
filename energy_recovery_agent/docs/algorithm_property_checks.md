# 算法属性测试

工具：`tools/algorithm_property_checks.py`  
测试：`tests/smoke/verify_algorithm_property_checks.py`

这组测试针对节能计算和资源可行性中容易出现“固定样例没覆盖”的性质，不依赖正式数据：

1. **随机化属性测试**：固定种子生成 200 组容量、效率、功率、SOC、牵引/再生组合，检查非负有限、SOC 不越界和结算不异常。
2. **时间跨桶和边界测试**：验证跨越 10 秒边界的 15 秒样本不丢能量，首尾相接的样本不重复计量。
3. **正反向对称性测试**：在镜像平坦线路上比较正向/反向列车的步数、运行时间、能量代理值和终点位置。
4. **终端 SOC 目标测试**：验证目标 SOC 已满足时无惩罚，以及无能量流时目标短缺会被报告。
5. **资源约束性质测试**：验证边界相接区间无冲突、真实重叠会报告冲突，重叠违规量不会减少。

运行：

```powershell
python tools/algorithm_property_checks.py --output-dir outputs/algorithm_property_checks
```

结果写入 `algorithm_property_summary.json` 和 `ALGORITHM_PROPERTY_CHECKS.md`，并已纳入本地 CI。

最近结果：随机测试 200/200 通过，时间边界、方向对称、终端 SOC 和资源性质检查全部通过。
