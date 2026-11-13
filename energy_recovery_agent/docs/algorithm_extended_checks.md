# 算法扩展检查（第 5～11 项）

工具：`tools/algorithm_extended_checks.py`  
测试：`tests/smoke/verify_algorithm_extended_checks.py`

本检查覆盖缓存等价性、优化器不变量、结果序列化重载、缺失数据门禁、资源边界、轻量性能压力和静态质量扫描：

- 缓存结果与直接构造结果一致；
- 可行候选支配不可行候选，Pareto 集过滤被支配项；
- JSON 写出/重载后仍可通过结果审计；
- 缺失正式输入在严格模式下阻断，而不是静默补齐；
- 相邻资源区间不冲突，重叠区间被识别；
- 小型 20 序列压力场景在时间和内存阈值内完成；
- 静态扫描记录裸 `pass` 和 TODO 供人工复核，合法异常处理不作为失败。

最近结果：7/7 子检查通过。裸 `pass` 均位于已有异常/兼容处理路径，未发现新的未处理 TODO。

```powershell
python tools/algorithm_extended_checks.py --output-dir outputs/algorithm_extended_checks
```
