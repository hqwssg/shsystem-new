# E12定向修复重复资源检查性能优化

更新时间：2026-09-06

## 1. 优化对象

12列车定向可行性修复需要在三个核心扰动场景下反复检查候选运行图。相邻局部错峰模板会重复查询同一基础轨迹的站点穿越时刻和首次进入储能区段时刻。本轮只消除这些严格等价的重复计算，不改变候选生成、束宽、迭代轮数、资源约束或稳健评价规则。

## 2. 瓶颈证据

E12独立定向修复基线共评价239个模板。`cProfile` 下端到端耗时为 `263.250 s`，其中：

- `crossing_elapsed_time_s` 调用1,591,740次，累计约 `190.468 s`；
- `_run_station_timings` 累计约 `170.699 s`；
- `build_resource_intervals`、`detect_overtaking_conflicts` 和 `check_flow_continuity` 均随239个模板在三个核心场景中重复执行。

证据位于 `paper/experiments/dispatch_targeted_repair_profile_baseline/`。

## 3. 等价缓存机制

`PowerSeriesCache` 增加两类惰性查询缓存：

- 线路位置穿越时刻缓存；
- 首次进入储能区段时刻缓存。

时间无关工况共享同一基础轨迹结果；时间相关工况将发车时刻纳入缓存键，防止错误复用。缓存同时记录有效结果和“未找到”结果。输入校验、轨迹计算公式和所有资源约束保持不变。

## 4. 验收结果

| 口径 | 优化前 | 优化后 | 变化 |
| --- | ---: | ---: | ---: |
| 独立定向修复实跑耗时 | 252.836792 s | 7.574947 s | -97.004% |
| cProfile端到端耗时 | 263.250 s | 27.221 s | -89.660% |
| cProfile中穿越时刻累计耗时 | 190.468 s | 1.663 s | -99.127% |
| 完整F12端到端耗时 | 388.498929 s | 152.627114 s | -60.714% |
| 完整E12端到端耗时 | 609.858808 s | 152.669016 s | -74.967% |
| 完整F12/E12峰值内存 | 139.258/151.062 MB | 139.090/150.895 MB | 基本不变 |

独立探针前后均评价239个模板，得到相同最优分数和相同局部错峰种子。完整F12和E12前后均保持各自语义SHA、候选数量、可行性及能源成本结果；其中E12保持：

- 语义 SHA-256：`3fddb81cd1488f0705b39720582da7c34029f1678b4b640acdf6bd12e754d310`；
- 候选数21、核心稳健可行候选数5、Pareto候选数1；
- 约束违反度0，不使用标称回退；
- 电网购电量、弃能、回收率和总成本逐项一致。

优化后证据位于 `paper/experiments/dispatch_targeted_repair_profile_optimized/`、`paper/experiments/dispatch_targeted_repair_optimized/`、`paper/experiments/dispatch_extended_scale_phase8_cached/` 和 `paper/experiments/dispatch_extended_scale_phase8_cached_f12/`。

## 5. 当前判断与下一步

E12完整耗时已从720秒门限的84.7%降至21.2%，重复轨迹查询不再是当前阻塞项，因此没有必要继续对这两类查询做微优化，也不触发增量评价或并行架构重构。

F12共享路径复验已经通过，71个 smoke 脚本也全部通过。E16/F16快速档均在约258秒完成，证明当前16列车计算规模未触发性能门限；第二级修复后E16已找到核心稳健可行候选，F16的高密度资源边界诊断见 `docs/dispatch_f16_density_boundary_diagnosis.md`。正式数据到位后仍须冻结输入、环境和搜索预算重新基准，本结果不代表生产SLA或正式线路容量。16列车结果见 `docs/dispatch_16train_quick_boundary.md`。
