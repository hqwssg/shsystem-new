# 合成状态驱动的多轮滚动重调度测试

更新时间：2026-09-08

## 1. 测试目的

本测试对应论文预实验 E15，验证滚动优化不是多次重复执行同一个静态案例，而是能够在连续轮次中接收新的运行状态、锁定已执行决策，并保持储能能量账本连续。

测试不用于发布正式节能率。当前车辆、线路、资源和储能数据仍包含规划或工程占位值，晚点序列也是合成事件。

## 2. 覆盖链路

四轮默认状态为：正常、重车晚点180秒、重车晚点60秒且空车晚点240秒、恢复为无新增晚点。每轮均执行以下流程：

1. 注入本轮重车晚点、空车晚点和窗口起点 SOC；
2. 使用当前 `RollingOptimizer`、稳健扰动集、资源约束和能量结算选择运行图；常规稳健搜索失败时，对冲突相关未来列车执行局部恢复修复；
3. 核心稳健门禁通过后，仅提交3300秒执行窗口内的发车；不可行候选只保留诊断，不提交新增发车；
4. 锁定已提交发车及对应储能区停车和储能预设；
5. 只结算本轮实际执行时间片，将终点 SOC 作为下一轮起点；
6. 下一轮预测能量从新的当前时刻开始，不重复计算历史功率。

## 3. 自动门禁

- 四轮全部完成且状态时钟按执行窗口递增；
- 合成晚点不仅进入状态对象，也进入所选方案的正常场景评价；
- 相邻轮次 SOC 首尾连续且始终位于物理容量范围；
- 已锁定重车、空车发车集合只能增加，不能被后续优化改写；
- 每个核心稳健可行轮至少产生一项可执行服务；不可行轮必须扣留未锁定的新服务；
- 能量评价起点随滚动窗口同步前移。
- SOC结算所用运行图必须与门禁确认的 `committed_execution_schedule` 完全一致。
- 恢复修复只能调整第一阶段识别出的冲突相关未来列车，锁定发车保持不变；采用的修复必须有明确逐车决策。

“所有轮次核心稳健可行”不是软件链路门禁。压力状态可能使已提交运行轨迹限制后续可行域；此时算法必须明确返回不可行回退和冲突分项，并以 `withheld_infeasible` 扣留新增决策，不能把结果伪装为可执行优化方案。

## 4. 执行与输出

```powershell
python run_project.py benchmark-rolling-rescheduling
python tools/verify_synthetic_rolling_rescheduling_results.py
```

默认结果目录为 `paper/experiments/E15_synthetic_rolling_rescheduling/`：

| 文件 | 内容 |
| --- | --- |
| `benchmark_summary.json` | 配置、逐轮状态、方案、约束、能量和门禁 |
| `rolling_cycles.csv` | 逐轮输入、锁定、可执行决策、SOC和失败分项 |
| `recovery_conflicts.csv` | 各核心场景的逐项资源冲突及直接可调列车 |
| `recovery_conflict_chains.csv` | 由共享列车连接的冲突链和修复可能性 |
| `recovery_adjustable_trains.csv` | 全体列车的锁定、可调整和冲突相关分类 |
| `recovery_adjustment_candidates.csv` | 可调列车优先级、所属冲突链和冲突负担 |
| `recovery_conflict_analysis.json` | 供后续恢复修复器读取的完整结构 |
| `recovery_repair_decisions.csv` | 实际尝试的逐列车发车修复量及采用状态 |
| `recovery_repair_scenarios.csv` | 修复前后各核心场景冲突分类 |
| `recovery_repair_results.json` | 第二阶段完整修复结果与诊断 |
| `exact_recovery_decisions.csv` | 第三阶段精确恢复产生的逐列车调整 |
| `exact_recovery_results.json` | 精确状态、证明、锁定边界、采用与完整评价结果 |
| `rolling_state_timeline.png` | 晚点观测与SOC连续状态图 |
| `SYNTHETIC_ROLLING_RESCHEDULING_REPORT.md` | 中文实验报告 |
| `verification.json` | 独立产物一致性核验 |

当前四轮中，第2轮通过名义调整 `H002 +90s`、`E002 +120s` 完全恢复稳健可行；叠加本轮重车观测晚点后实际提交时刻为3570秒。第3轮强联合扰动和第4轮恢复状态均保持核心稳健可行，四轮最终资源冲突均为0。

第五阶段已用相同输入增加关闭恢复的控制组。控制组仅1/4轮核心稳健可行、全部核心场景累计17个冲突；开启恢复后4/4轮可行且冲突为0。完整消融口径和能量影响见 `recovery_ablation_validation.md`。

第三阶段精确恢复仍在局部恢复未完成后接管。当前四轮由常规搜索或局部修复完成，因此未实际调用MILP；专项回归另以当前线路资源和真实轨迹缓存验证了带锁定历史的HiGHS求解路径可以返回 `feasible_verified`。

第四阶段进一步区分名义计划 `schedule` 与实际候选 `execution_schedule`。当前提交安全改进增加 `committed_execution_schedule`：只有通过核心稳健门禁的新增发车才会进入下一轮锁定和执行期能量结算。门禁之后由安全降级状态机执行有界增强重试、等待新观测和连续失败人工升级；完全相同请求通过指纹幂等复用。当前 schema 为 `1.7`，新增每轮 `storage_parameters_by_id` 以记录算法实际采用的逐设备数据库额定参数。生产门禁和状态机分别见 `rolling_infeasible_commit_gate.md`、`rolling_safety_degradation_state_machine.md`。

## 5. 正式数据后的扩展

正式数据到位后，应把合成晚点替换为带列车ID和事件时间的历史扰动回放，同时接入临时限速和运输任务队列。逐储能设备 SOC、设备可用状态及临时充放电功率上限已经接入滚动状态和数据库任务参数，正式平台只需按现有契约提供实时快照并重新验证。
