# 数据库逐储能设备参数与算法绑定

更新时间：2026-09-08

## 1. 目的

`energy_recovery.simulation_storage_device` 是平台模式下储能设备静态物理参数的权威来源。算法工作进程在领取任务后读取指定数据版本的全部设备行，生成 `storage_devices.json`，并与原始文件共同冻结到本次运行快照。算法随后从该快照加载设备参数，不再使用 `battery.json` 中的聚合容量、功率或效率代替逐设备值。

## 2. 绑定字段

| 数据库字段 | 算法作用 |
|---|---|
| `storage_code` | 对应 `storage_section_id`，关联供电臂、实时状态和输出 |
| `capacity_kwh` | 设备物理容量上限 |
| `max_charge_power_kw` | 每个结算窗口的额定充电功率限制 |
| `max_discharge_power_kw` | 每个结算窗口的额定放电功率限制 |
| `charge_efficiency` | 充电输入转化为内部 SOC 的效率 |
| `discharge_efficiency` | 内部 SOC 转化为牵引侧输出能量的效率 |
| `initial_soc_kwh` | 未提供滚动实时状态时的设备初始 SOC |
| `min_soc_kwh` | 放电后不可突破的 SOC 下限 |
| `max_soc_kwh` | 充电后不可突破的 SOC 上限 |
| `available` | 数据版本中的静态投运状态 |

SOC 递推采用：

```text
充电后SOC = 充电前SOC + 充电输入电量 × charge_efficiency
放电后SOC = 放电前SOC - 牵引侧输出电量 ÷ discharge_efficiency
min_soc_kwh <= SOC <= max_soc_kwh <= capacity_kwh
```

## 3. 数据流

```text
simulation_storage_device
    -> 工作进程按version_id读取并排序
    -> 生成storage_devices.json
    -> 与原始输入一起计算哈希并冻结运行快照
    -> load_real_data_bundle加载为StorageDeviceParameters
    -> 重空调度、滚动调度、运行图审查和运行图优化使用
    -> 输出storage_parameters_by_id和逐设备SOC/能量账本
```

工作进程在数据库设备表为空时直接拒绝任务，不能静默回退到聚合占位参数。`storage_devices.json` 即使存在于原始文件中，也会被本次数据版本的数据库设备行覆盖，从而保证关系表是平台运行时的权威来源。

## 4. 与滚动实时状态的关系

数据库表中的设备行描述静态额定能力；`simulation_run_parameter.parameters_json.storage_devices` 描述本轮观测状态。实时状态只能提供 SOC、在线/停运状态和临时功率上限：

- 实时 SOC 必须位于数据库 `min_soc_kwh` 与 `max_soc_kwh` 之间；
- 临时充放电功率不得超过数据库额定功率；
- 数据库静态停运或实时停运任一成立，设备均不能充放电；
- 实时状态不能修改容量、效率和 SOC 边界。

## 5. 聚合旧数据兼容

文件模式只有 `battery.json` 和多个 `energy_transfer_zones.csv` 区段时，数据库发布投影会把聚合容量和功率按设备数等分，效率按往返效率平方根拆为充电与放电效率，避免每台设备重复获得整套聚合能力。该路径仅用于当前占位数据兼容；正式设备数据应直接提供逐设备值。

数据库设备参数存在时，重空调度自动关闭虚拟储能预设搜索。数据库任务白名单不接受聚合容量、功率和效率覆盖参数，算法文件入口也会拒绝对已绑定设备进行此类覆盖，防止运行时绕过正式设备数据。

## 6. 验证

- `tests/smoke/verify_database_storage_device_binding.py`：验证异构容量、功率、双向效率、SOC上下限、静态停运、实时越界、快照适配和预设禁用；
- `tests/smoke/verify_database_integration.py`：验证数据库投影总量不放大、工作进程读取设备行并冻结到输入快照；
- `tests/smoke/verify_acceptance_and_result_quality.py`：验证滚动结果中的额定参数、SOC边界和停运零能量流门禁；
- E15正常与单设备停运基准均通过结果质量审计。

本地 PostgreSQL 16测试实例已完成迁移、逐设备参数查询、冻结快照和五类算法任务端到端验收。目标平台数据库中的登录账号、TLS和正式设备数据仍需在部署环境重新验收。
