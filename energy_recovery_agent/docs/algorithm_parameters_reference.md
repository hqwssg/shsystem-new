# 算法参数说明

## 1. 能量结算参数

| 参数 | 单位 | 作用 | 当前状态 |
|---|---:|---|---|
| `settlement_step_s` | s | 能量结算时间桶长度 | 原型控制项，必须为正整数 |
| `capacity_kwh` | kWh | 储能容量上限 | 当前为规划/占位值 |
| `max_charge_power_kW` | kW | 最大充电功率 | 当前为规划/占位值 |
| `max_discharge_power_kW` | kW | 最大放电功率 | 当前为规划/占位值 |
| `round_trip_efficiency` | 0–1 | 储能往返效率 | 当前为规划/占位值 |
| `initial_soc_kwh` | kWh | 评价窗口初始 SOC | 测试或正式状态快照 |
| `target_final_soc_kwh` | kWh | 终端 SOC 目标 | 可选约束 |
| `allow_direct_use` | 布尔 | 是否允许同时间直接供能 | 朔黄主场景为否 |
| `allow_storage` | 布尔 | 是否允许进入储能 | 主场景为是 |

## 2. 运行图优化参数

| 参数 | 单位 | 作用 |
|---|---:|---|
| `max_shift_min` | min | 单列车最大时刻偏移 |
| `step_min` | min | 候选时间离散步长 |
| `max_dwell_extension_min` | min | 最大停站延长 |
| `max_candidates` | 个 | 规则候选上限 |
| `population_size` | 个 | NSGA-II 种群规模 |
| `generations` | 代 | NSGA-II 迭代代数 |
| `seed` | — | 随机种子，用于复现 |

优化目标当前按以下字段比较，数值越小越好：`effective_regen_loss_kwh_est`、`grid_kwh_est`、`total_adjustment_min`。前两项改善必须超过 `0.01` 的数值容差，且不得明显恶化另一项；否则决策门控返回 `keep_baseline`。

## 3. 约束参数

运行图必须满足站点时序、到发一致性、方向和里程顺序、追踪间隔、站场股道、咽喉并发、区间占用和供电/储能区段约束。`constraint_violation` 或电气约束违反度超过容差时，候选不得被采用。

## 4. 参数使用原则

规划值、工程占位值和启发式默认值只能用于流程验证、相对比较和区间敏感性分析。正式节能量、储能容量和投资收益结论必须在参数来源、版本、适用范围和单位均确认后重新计算。
