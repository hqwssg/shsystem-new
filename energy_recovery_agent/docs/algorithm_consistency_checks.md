# 算法一致性、消融与参数单调性检查

工具：`tools/algorithm_consistency_checks.py`  
测试：`tests/smoke/verify_algorithm_consistency_checks.py`

该检查使用小型确定性合成场景，不修改默认算法逻辑，也不使用正式工程数据。

## 检查内容

- 模块交叉：直接能量结算与运行图时间片审计逐项对齐；
- 消融：启用储能与禁用储能比较，检查储能带来的方向性影响；
- 单调性：容量、充放电功率、效率增加时，电网购电和弃电不应反向增加。

## 最近结果

最近运行结果为 PASS：交叉验证 7 项指标差异均为 0；储能使合成场景电网购电从 9 kWh 降至 0、弃电从 10 kWh 降至 0；容量、功率和效率的单调性检查全部通过。

## 运行方式

```powershell
python tools/algorithm_consistency_checks.py --output-dir outputs/algorithm_consistency_checks
```

结果文件：

- `algorithm_consistency_summary.json`：机器可读结果和数值；
- `ALGORITHM_CONSISTENCY_CHECKS.md`：摘要报告。

检查通过只说明当前模块之间的账本和基本趋势一致，不能证明正式现场参数已经准确。
