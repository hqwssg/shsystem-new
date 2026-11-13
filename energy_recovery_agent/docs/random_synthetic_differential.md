# 随机合成案例差分测试

## 1. 测试目的

固定样例和属性测试只能证明已列出的行为成立；差分测试进一步用大量随机合成输入，同时运行生产实现和独立参考实现，并逐项比较结果。它适合在正式数据到位前发现边界组合、共享资源聚合和数值容差中的静默错误。

本测试不使用甲方数据，不能证明当前规划参数准确，也不形成正式节能结论。

## 2. 差分范围

| 套件 | 生产实现 | 独立参考实现 | 比较项 |
| --- | --- | --- | --- |
| `energy_bucket` | `settle_energy_bucket_group` | 单供电臂、单储能设备的独立能量账本 | 直用、充放电、受限量、弃能、购电、电气超限和末端 SOC |
| `energy_time_slicing` | `EnergySettlementSystem.settle` | 独立区间切片积分 | 多功率序列、跨桶和部分桶的总能量及逐桶购电/弃能 |
| `resource_overlap` | `detect_resource_conflicts`、`resource_capacity_overlap_violation_s` | 逐对重叠与逐秒占用枚举 | 冲突列车对、重叠窗口和超容量秒 |
| `pareto_front` | 运行图优化器支配关系与 `pareto_rows` | 量化目标的独立穷举前沿 | 双向支配关系、可行候选前沿、重复目标去重 |

能量案例随机覆盖直用开关、储能开关、1至5个同时请求、部分可转移能量、无储能标签、初始 SOC、容量、充放电功率和供电臂限值。资源案例随机覆盖三类资源、多个资源组、方向、重叠阈值和多列车同时占用。Pareto 案例随机覆盖可行/不可行候选、目标容差边界和重复目标。

## 3. 运行方式

默认正式合成测试使用 3 个固定种子，每个种子执行 500 个桶内能量案例、300 个时间分桶案例、500 个资源案例和 300 个 Pareto 案例，共 4800 个案例：

```powershell
python run_project.py test-random-differential
```

扩大覆盖时可以增加种子和案例数：

```powershell
python run_project.py test-random-differential --seeds 11 23 37 53 71 --energy-cases 1000 --time-slicing-cases 500 --resource-cases 1000 --pareto-cases 500
```

smoke 使用 2 个种子执行两次相同的 420 案例测试，同时验证案例集合哈希和汇总结果完全复现；另注入一次生产实现异常，确认失败输入仍会写入回放文件：

```powershell
python tests/smoke/verify_random_synthetic_differential.py
```

## 4. 当前验证结果

2026-09-09 使用默认 3 个固定种子完成两次独立运行，每次均为 4800/4800 个案例通过，失败数为 0。两次案例集合 SHA-256 均为 `1478ba742ec1d560cb3710147691baba752623232a920c27f7050b6ecd21081f`，证明相同配置下的案例生成与汇总结果可复现。

桶内能量账本最大绝对误差为 `2.274e-13`，时间分桶最大绝对误差为 `1.307e-12`，资源冲突和 Pareto 前沿差异均为 0，全部低于 `1e-8` 判定门限。结果见 `paper/experiments/random_synthetic_differential_current/`。

## 5. 输出与失败回放

| 文件 | 用途 |
| --- | --- |
| `RANDOM_SYNTHETIC_DIFFERENTIAL_REPORT.md` | 人员阅读的范围、数量、误差和结论 |
| `random_synthetic_differential_summary.json` | 种子、配置、套件统计、案例集合 SHA-256 和输出合同 |
| `random_synthetic_differential_cases.csv` | 每个案例的套件、种子、编号、输入哈希、状态和最大误差 |
| `random_synthetic_differential_failures.json` | 失败案例的完整随机输入、实际/期望差值及异常，可用于确定性回放 |

失败文件即使没有失败也会生成，内容为一个空数组，便于自动化平台使用稳定的工件合同。输入由“种子 + 套件 + 案例序号”确定；案例本身另有 SHA-256，防止生成规则变化后误认为是同一批输入。

## 6. 判定边界

能量和资源连续量采用 `1e-8` 最大绝对误差门限。Pareto 目标采用优化器合同规定的 `0.01` 量化容差，候选约束违反度大于 `1e-9` 时不进入可行前沿。

参考实现不得调用被比较的生产函数。若生产实现和参考实现同时需要相同的物理定义，定义写在测试文档和输入合同中，计算过程分别实现。差分不一致必须保留失败输入并人工判断是生产实现、参考实现还是合同发生变化，不能直接刷新预期值掩盖差异。
