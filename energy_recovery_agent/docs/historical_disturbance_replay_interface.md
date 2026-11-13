# 历史扰动回放接口

## 1. 用途

该接口把已经发生并经过确认的重空列车晚点状态，按原时间顺序重新送入滚动重调度算法。主要用途是复现历史运行条件、检验恢复策略、比较不同算法版本，并为论文提供可追溯实验记录。

当前算法的调度对象是重车和空车发车序列。接口接收每个滚动周期的重车/空车汇总晚点、按 `H001/E001` 稳定编号的逐列车晚点，以及可选的逐储能设备状态。逐列车晚点直接进入稳健评价和执行计划；同方向汇总晚点与逐车晚点不能同时提供，晚点也不能改写锁定历史或造成列车越序。

临时限速会按里程、时间窗和运行方向进入列车物理仿真并重建轨迹缓存；逐储能设备事件在完整覆盖全部设备后直接成为周期权威状态。取消、加开、资源封锁和供电臂动态限值从 `1.2` 起进入算法执行；`1.3` 新增方向专用限速执行，限速只作用于匹配方向的列车，不会污染反方向轨迹。

## 2. 数据库存储和调用

回放JSON作为版本化输入文件写入 `energy_recovery.simulation_dataset_file`。建议逻辑路径为：

```text
platform/historical_disturbance_replay_<回放编号>.json
```

平台创建 `rolling_rescheduling` 任务时，在 `simulation_run_parameter.parameters_json` 中提供：

```json
{
  "population_size": 2,
  "generations": 1,
  "seed": 20260908,
  "disturbance_history_relative_path": "platform/historical_disturbance_replay_case_001.json"
}
```

工作进程会确认文件位于冻结快照内，再将其传给算法。路径越界、文件不存在、内容摘要变化或合同校验失败都会使任务失败。回放参数与独立的 `storage_devices` 运行时参数互斥，避免两个来源同时声明SOC。

文件模式也可直接运行：

```powershell
.\.venv\Scripts\python.exe run_project.py benchmark-rolling-rescheduling `
  --disturbance-history data_templates\historical_disturbance_replay_template.json `
  --output-dir outputs\historical_disturbance_replay
```

## 3. 输入合同

模板见 `data_templates/historical_disturbance_replay_template.json`。

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `schema_version` | 是 | 当前版本为 `1.3`；兼容 `1.0/1.1/1.2`。`1.1` 中动态扩展事件、`1.2` 中方向专用限速仍保持原有阻断语义。 |
| `replay_code` | 是 | 回放业务编号。 |
| `data_status` | 是 | `official`、`derived_from_official`、`planning_placeholder` 或 `synthetic`。 |
| `execute_window_s` | 是 | 固定滚动执行窗口，单位秒且大于0。 |
| `source_system` | 否 | 历史记录来源系统。 |
| `source_note` | 否 | 数据口径及清洗说明。 |
| `cycles` | 是 | 至少两个按时间排序的周期状态。 |

每个周期必须包含连续且从0开始的 `cycle_index`、与窗口严格对齐的 `current_time_s`、非负整数 `observed_heavy_delay_s` 和 `observed_empty_delay_s`，以及至少一个全局唯一的 `source_record_ids`。`observed_at`用于追溯真实时间，不参与算法秒轴计算。

`storage_devices`为可选的权威现场状态。一旦某周期提供，就必须完整覆盖模型配置的全部储能设备，并接受SOC、可用状态及临时功率上限校验；未提供时使用上一执行窗口结算得到的状态。

每个周期还可提供 `events` 数组。事件公共字段为 `event_id`、`event_type`、`entity_id` 和 `payload`。`1.3` 直接执行逐车晚点、双向或单方向临时限速、完整设备状态、取消、加车、资源封锁和供电臂动态限值。取消只能作用于未执行且未锁定列车；加车ID必须与重空类型一致且发车时刻不得早于当前周期；资源和供电约束采用半开绝对时间窗 `[start_time_s, end_time_s)`。

| `event_type` | 关键载荷 | 当前处理 |
| --- | --- | --- |
| `train_delay` | `entity_id=H001/E001`、`delay_s` | 直接作用到未来未锁定列车。 |
| `storage_device_state` | 设备ID、SOC、可用状态、可选临时功率 | 同周期完整覆盖设备后直接应用。 |
| `temporary_speed_restriction` | 起止里程、限速、起止时间、方向 | `both/all`作用于双向；`forward/down/heavy`只作用于里程递增重车方向；`reverse/up/empty`只作用于里程递减空车方向。 |
| `train_cancelled` | 列车ID、原因 | 从当前周期未锁定候选中删除；禁止取消历史或锁定列车。 |
| `train_added` | 列车ID、类型、发车秒 | 作为固定新增服务参与后续候选的资源、能量和提交门禁；动力学采用对应Heavy/Empty车型。 |
| `resource_unavailable` | 资源ID、资源类型、起止时间 | 与列车资源占用相交时生成阻断冲突；可调列车移出封锁窗，锁定列车冲突升级人工处置。 |
| `power_arm_limit` | 供电臂ID、至少一个功率限值、起止时间 | 与指定窗口相交的结算时间桶采用静态值与全部动态值中的最严上限，并计入牵引/再生电气超限。 |

## 4. 输出结果

- `benchmark_summary.json`：增加 `input_mode=historical_disturbance_replay`、完整回放来源摘要、逐轮稳定列车ID和 `dynamic_events_reach_execution` 自动门禁。
- `disturbance_replay_manifest.json`：记录回放编号、数据状态、源路径、SHA-256、周期数和源记录数，用于证明结果对应哪份历史输入。
- `disturbance_replay_cycles.csv`：逐周期关联源记录ID、晚点观测、取消/加车ID、资源封锁ID、动态供电限值ID、储能观测、核心稳健可行性、提交状态和安全状态，供平台界面和人工复核。
- `rolling_cycles.csv`：保留完整求解、冲突、恢复、执行结算及SOC明细，并投影到 `simulation_rolling_control_event`。
- `HISTORICAL_DISTURBANCE_REPLAY_REPORT.md`：给出回放结论、逐轮结果、自动门禁和适用边界。

## 5. 当前边界

接口已经建立到数据库快照、命令行、算法观测和结果工件层。它不会把“有历史数据”自动等同于“实验有效”：车辆、线路、信号、电气和储能参数仍须分别通过正式数据门禁。列车ID会随运行图传递到资源网络，不因取消后列表压缩而重编号。当前取消采用“当前快照执行一次”的保守语义；加车保留到其发车时刻，临时限速、资源封锁和动态供电限值保留到时间窗失效。方向在解析时统一为 `forward/reverse/both` 并进入轨迹缓存指纹；旧 `1.2` 单方向事件继续阻断，必须显式升级文件版本才能执行。当前 `signaling_block/segment` 封锁必须使用算法资源模型可识别的 `section:<序号>` ID；正式闭塞分区接入后再使用设备级ID。运输任务补偿、车底分配、封锁人工授权和多来源动态限值来源优先级仍由平台/调度规章负责；算法只取静态值与所有生效动态值中的最严上限，不会自行放宽约束。
