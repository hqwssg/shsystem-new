# 分储能设备 SOC 与运行状态驱动的滚动调度

更新时间：2026-09-08

## 1. 完成范围

滚动调度现已按 `storage_section_id` 接收每台储能设备的实时状态，并将该状态用于候选运行图的能量结算。每台设备独立维护 SOC、在线/停运状态、当前可用充电功率和当前可用放电功率，不再把储能总 SOC 在设备间重新均分。

静态额定容量、额定充放电功率、充放电效率、初始SOC和SOC上下限来自版本化数据库 `simulation_storage_device`；实时状态只描述本次滚动窗口起点的观测值和临时可用能力，不能扩大静态额定能力。完整绑定流程见 `database_storage_device_algorithm_binding.md`。

## 2. 输入结构

```json
{
  "storage_devices": [
    {
      "storage_section_id": "storage_section_1:K145-K164",
      "soc_kwh": 2500.0,
      "available": true,
      "max_charge_power_kw": 5000.0,
      "max_discharge_power_kw": 5000.0
    },
    {
      "storage_section_id": "storage_section_2:K164-K200.7",
      "soc_kwh": 2500.0,
      "available": false,
      "max_charge_power_kw": 0.0,
      "max_discharge_power_kw": 0.0
    }
  ]
}
```

- `storage_section_id`、`soc_kwh` 必填；
- `available` 省略时默认为 `true`；
- 临时功率上限省略时使用该设备在当前聚合配置中的额定分配值；
- `available=false` 时设备保留 SOC，但有效充放电功率强制为零；
- 显式设备状态必须完整覆盖当前储能预设中的设备，不能缺项或包含未知设备；
- SOC 不得超过设备容量，临时功率不得超过静态额定分配；
- 新设备接口与旧 `storage_soc_kwh` 汇总接口不能同时提供。

## 3. 跨轮状态语义

每轮滚动优化按以下顺序处理：

1. 接收当前设备状态快照；
2. 使用逐设备 SOC 和可用功率评价所有候选；
3. 只有通过核心稳健提交门禁的运行图进入执行期结算；
4. 执行期结算产生逐设备终端 SOC；
5. 下一轮可以使用该终端状态，也可以由现场新快照覆盖；
6. 设备故障、恢复或降额会改变观测与请求指纹，不会错误复用旧求解结果。

旧的 `storage_soc_kwh` 仍保留用于历史调用。使用旧接口时，总 SOC 按既有规则分配；生产平台应使用设备级接口。

## 4. 输出与诊断

结算结果新增：

- `initial_soc_by_storage_kwh`；
- `final_soc_by_storage_kwh`；
- `battery_charge_by_storage_kwh`；
- `battery_discharge_by_storage_kwh`；
- `wasted_by_storage_kwh`。

滚动结果的 `rolling_energy_state.state_mode` 为 `per_device`、`aggregate_legacy` 或 `static_configuration`。`rolling_cycles.csv` 和 `benchmark_summary.json` 同时保存每轮设备输入状态、`storage_parameters_by_id`、逐设备初始/终端 SOC 及逐设备充放电量。

## 5. 数据库与命令入口

平台将设备数组保存在 `simulation_run_parameter.parameters_json.storage_devices`。该内容属于任务不可变参数，会进入 `request_sha256`，因此重复任务与设备状态变化可以被正确区分。示例见 `database/examples/rolling_rescheduling_parameters.json`。

```powershell
python -m database.cli create-run `
  --project-code shuohuang-energy `
  --version-code planning-2026-09 `
  --run-type rolling_rescheduling `
  --parameters-file database/examples/rolling_rescheduling_parameters.json `
  --idempotency-key rolling-state-0001
```

直接运行时也可使用 `benchmark-rolling-rescheduling --storage-devices-json '<JSON数组>'`。

## 6. 验证结论

- `tests/smoke/verify_rolling_storage_device_state.py` 验证不均衡 SOC、设备停运、充放电降额、字段冲突和状态指纹；
- `tests/smoke/verify_synthetic_rolling_rescheduling.py` 验证设备在线、停运、恢复状态逐轮进入优化器；
- `paper/experiments/E15_storage_device_runtime_state/` 完成两设备四轮 SOC 连续性基准；
- `paper/experiments/E15_storage_device_outage/` 完成第二台设备全程停运的真实组件基准。

两组真实组件基准均为 4/4 轮核心稳健可行并通过全部门禁。停运场景中第二台设备 SOC 始终为 2500 kWh；正式参数和历史状态到位后仍需重跑，当前数值不作为现场节能结论。

两组结果也已通过 `check-results` 质量审计，审计覆盖逐设备字段完整性、数值范围、总量汇总、跨轮连续性和停运设备零充放电约束。
