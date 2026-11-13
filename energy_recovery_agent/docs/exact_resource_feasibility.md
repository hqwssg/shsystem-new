# 精确资源可行性求解与F16复核

更新时间：2026-09-07

## 1. 目的

启发式搜索没有找到可行运行图，只能说明既定候选域和搜索预算内没有命中，不能证明模型无解。精确资源可行性层用于补足这一判断缺口：

1. 验证启发式给出的运行图是否满足核心扰动场景下的资源约束；
2. 启发式无解时，在明确发车时域内直接求解整数秒发车时刻；
3. 区分“启发式漏解”“模型在显式定义域内确实不可行”和“求解时限内仍未知”。

该层只判断运行图资源可行性，不替代后续能量、电气、信号、服务数量和SOC完整评价。

## 2. 模型范围

决策变量是每列重车、空车的整数秒发车时刻。模型保持同类列车顺序并满足最小发车间隔，对三个核心场景分别建立站线、咽喉和区间占用约束。

默认模式先求解容量为1的资源约束松弛模型：

- 若松弛模型被HiGHS证明不可行，则包含更多约束的完整资源模型也必然不可行；
- 若松弛模型找到候选，必须再由现有 `check_schedule_resources` 完整检查器逐场景复核，全部通过后才返回可行；
- 求解达到时限且没有候选时，只返回“未知”，绝不写成“模型不可行”。

`max_adjustment_s=None` 表示在 `[0, horizon_s]` 完整发车域内求解；给出调整上限时，不可行结论只适用于该局部调整域。扰动恢复第三阶段已增加完整合并运行图适配：历史和未来列车均进入同一精确模型，当前时刻之前及显式锁定的发车固定不变，只有未提交未来列车可调整。若权威检查已发现双方均锁定的冲突，则直接输出锁定历史阻断，不运行无意义的MILP。详见 `recovery_exact_resource_integration.md`。

## 3. 输出结论

| 精确层状态 | 含义 | 可否证明模型无解 |
| --- | --- | :---: |
| `feasible_verified` | 找到整数秒方案，且完整资源检查器验证通过 | 否，证明存在可行解 |
| `model_infeasible` | HiGHS证明完整模型或其严格松弛不可行 | 是，仅限输出记录的时域、边界、场景和当前输入 |
| `solver_limit_no_solution` | 达到时限且没有可验证候选 | 否 |
| `solver_candidate_rejected` | 求解器候选未通过完整资源检查 | 否 |
| `solver_error` | 建模或求解异常 | 否 |

优化器进一步给出 `feasibility_conclusion`：

| 结论 | 解释 |
| --- | --- |
| `heuristic_search_missed_feasible_solution` | 启发式没有找到，但精确层找到并验证了可行解 |
| `heuristic_solution_exactly_verified` | 启发式解被精确层固定验证通过 |
| `model_proven_infeasible_in_explicit_domain` | 显式定义域内模型被证明不可行 |
| `search_exhausted_but_model_feasibility_unknown` | 搜索和求解时限均未得到定论 |
| `heuristic_exact_model_inconsistency` | 启发式权威检查已通过，但精确模型报告不可行；属于模型一致性错误，不采信不可行证明 |

## 4. F16结果

F16采用8重+8空、14400秒时域、1800秒重车/空车基准间隔、1590秒重空相位和三个核心扰动场景。纯可行性模型在23.229秒内结束，HiGHS状态为最优，完整资源检查结果如下：

| 场景 | 资源可行 | 冲突数 | 重叠违反量 | 流连续性 |
| --- | :---: | ---: | ---: | :---: |
| normal | 是 | 0 | 0秒 | 通过 |
| heavy_delay_light | 是 | 0 | 0秒 | 通过 |
| empty_delay_light | 是 | 0 | 0秒 | 通过 |

因此，F16在当前规划/占位资源输入和上述显式定义域内存在核心稳健资源可行运行图。此前第二级启发式没有找到解，应归类为 `heuristic_search_missed_feasible_solution`，不能继续解释为高密度结构性不可行。

该结论仍不是正式线路容量证明，也不代表该可行解已经取得最佳能耗或工程上可直接实施。正式咽喉、闭塞、运行图和扰动数据到位后必须重算。

## 5. 复现

运行环境需要支持 `scipy.optimize.milp`；本轮证据使用SciPy 1.13.1及其HiGHS后端。

```powershell
python tools/run_exact_resource_feasibility.py `
  --data-dir data/real_shuohuang `
  --output-dir paper/experiments/dispatch_exact_resource_f16 `
  --heavy-count 8 --empty-count 8 `
  --heavy-headway-s 1800 --empty-headway-s 1800 `
  --phase-s 1590 --horizon-s 14400 --time-limit-s 120
```

标准证据文件为 `paper/experiments/dispatch_exact_resource_f16/exact_resource_feasibility.json`。其中记录输入模板、求解状态、证明类型、模型规模、求解后的逐列车发车调整及逐场景权威复核结果。

相关实现：

- `exact_resource_feasibility.py`：混合整数可行性模型和权威复核；
- `tools/run_exact_resource_feasibility.py`：独立复现入口；
- `rolling_optimizer.py`：启发式之后的精确验证/补解及结论分类；
- `tests/smoke/verify_exact_resource_feasibility.py`：可行与经证明不可行两类测试；
- `tests/smoke/verify_resource_feasibility_conclusions.py`：结论互斥与超时未知测试。

## 6. F16端到端接入验证

精确资源候选已进一步接入完整 `dispatch-case` 流程验证，结果位于 `paper/experiments/dispatch_exact_resource_f16_end_to_end/`：

- 第二级启发式资源可行种子为0，精确层成功触发并返回 `feasible_verified`；
- 可行性结论为 `heuristic_search_missed_feasible_solution`；
- 精确运行图与5种虚拟储能预设组合后，5个候选均完成完整稳健评价且均通过核心门禁；
- 最终方案的追踪间隔、信号、资源、流连续性、电气约束和8重+8空服务完整性均通过；
- 三个核心场景均为0资源冲突、0约束违反；两个±300秒非核心压力场景仍失败；
- SOC物理范围保持在0至20000 kWh，但终端SOC仍有7126.289 kWh软偏差，已计入目标与成本惩罚。

专项报告见 `paper/experiments/dispatch_exact_resource_f16_end_to_end/F16_EXACT_END_TO_END_VERIFICATION.md`，机器验收结果见同目录 `f16_exact_end_to_end_verification.json`。

## 7. 偏移质量优化

纯可行性目标可能返回偏离原运行图很远的任意解。当前正式集成已改为词典序质量求解：

1. 在总求解时限内扩展可行上界，并通过单调二分证明最小的最大单车偏移；
2. 固定该最小边界，再最小化全部列车的总绝对偏移；
3. 两级结果都必须通过完整资源检查器，超时只能报告已有可行解，不能伪称质量最优。

正式集成直接以相位840秒的原F16运行图为参照。结果为：366秒上限被证明不可行，367秒可行；在367秒边界内，总绝对偏移3000秒达到最优。相较纯可行解，最大偏移由4013秒降至367秒，总偏移由33973秒降至3000秒，分别改善90.855%和91.169%。

质量解完成端到端复验后，5个候选仍全部通过三个核心场景完整评价；三个核心场景的终端SOC偏差均为0。完整报告见 `paper/experiments/dispatch_exact_resource_f16_quality/F16_EXACT_QUALITY_REPORT.md`。
