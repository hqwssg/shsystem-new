# 实时状态异常注入与恢复测试矩阵

结论：`PASS`；共 40 项，通过 40 项，失败 0 项。

| 类别 | 案例 | 通过 | 失败 |
| --- | ---: | ---: | ---: |
| 字段与时钟 | 16 | 16 | 0 |
| 顺序与位置 | 6 | 6 | 0 |
| 断流与恢复 | 9 | 9 | 0 |
| 设备状态 | 4 | 4 | 0 |
| 滚动恢复 | 5 | 5 | 0 |

## 逐项矩阵

| 编号 | 类别 | 异常注入 | 预期行为 | 实际行为 | 结果 |
| --- | --- | --- | --- | --- | --- |
| RT-F01 | 字段与时钟 | 有效基线 | 接受并使用快照 | use_accepted_snapshot | PASS |
| RT-F02 | 字段与时钟 | 缺少必填字段 | 拒绝；错误包含“缺少实时字段” | 缺少实时字段：['power_kW'] | PASS |
| RT-F03 | 字段与时钟 | 布尔时间戳 | 拒绝；错误包含“有限数值” | timestamp_s必须是有限数值 | PASS |
| RT-F04 | 字段与时钟 | 非有限功率 | 拒绝；错误包含“有限数值” | power_kW必须是有限数值 | PASS |
| RT-F05 | 字段与时钟 | 负时间戳 | 拒绝；错误包含“非负整数” | timestamp_s必须是非负整数 | PASS |
| RT-F06 | 字段与时钟 | 小数时间戳 | 拒绝；错误包含“非负整数” | timestamp_s必须是非负整数 | PASS |
| RT-F07 | 字段与时钟 | 空列车ID | 拒绝；错误包含“不能为空” | train_id不能为空 | PASS |
| RT-F08 | 字段与时钟 | 非法方向 | 拒绝；错误包含“direction” | direction必须是forward或reverse | PASS |
| RT-F09 | 字段与时钟 | 负位置 | 拒绝；错误包含“不能为负数” | position_km不能为负数 | PASS |
| RT-F10 | 字段与时钟 | 负速度 | 拒绝；错误包含“不能为负数” | speed_mps不能为负数 | PASS |
| RT-F11 | 字段与时钟 | 负SOC | 拒绝；错误包含“不能为负数” | soc_kwh不能为负数 | PASS |
| RT-F12 | 字段与时钟 | SOC超过容量 | 拒绝；错误包含“容量上限” | soc_kwh超过容量上限 | PASS |
| RT-C01 | 字段与时钟 | 新鲜度边界 | 接受并使用快照 | use_accepted_snapshot | PASS |
| RT-C02 | 字段与时钟 | 过期消息 | 拒绝；错误包含“最大新鲜度” | 消息已超过最大新鲜度 | PASS |
| RT-C03 | 字段与时钟 | 未来偏差边界 | 接受并使用快照 | use_accepted_snapshot | PASS |
| RT-C04 | 字段与时钟 | 未来时钟漂移 | 拒绝；错误包含“未来时钟偏差” | 消息时间超过允许的未来时钟偏差 | PASS |
| RT-S01 | 顺序与位置 | 完全重复消息 | 拒绝且不推进可信游标 | 重复消息 | PASS |
| RT-S02 | 顺序与位置 | 同车消息乱序 | 拒绝且不推进可信游标 | 同一列车消息乱序 | PASS |
| RT-S03 | 顺序与位置 | 正向位置倒退 | 拒绝且不推进可信游标 | 正向列车位置倒退 | PASS |
| RT-S04 | 顺序与位置 | 列车方向突变 | 拒绝且不推进可信游标 | 同一列车方向发生变化 | PASS |
| RT-S05 | 顺序与位置 | 多条坏消息后的有效消息 | 接受有效消息，游标从100推进到110 | healthy | PASS |
| RT-S06 | 顺序与位置 | 反向列车位置反向异常 | 拒绝且不推进可信游标 | 反向列车位置前进 | PASS |
| RT-O01 | 断流与恢复 | 启动后没有任何状态 | no_data_hold并等待快照 | no_data_hold | PASS |
| RT-O02 | 断流与恢复 | 收到首个有效状态 | 进入healthy | healthy | PASS |
| RT-O03 | 断流与恢复 | 超过30秒未收到有效消息 | 扣留新决策并保留最后可信状态 | stream_outage_hold | PASS |
| RT-O04 | 断流与恢复 | 断流后收到新鲜有效消息 | 标记recovered并恢复使用 | recovered | PASS |
| RT-O05 | 断流与恢复 | 未来时钟漂移后校正重发 | 漂移消息拒绝，校正消息接受 | rejected=1, corrected=1 | PASS |
| RT-O06 | 断流与恢复 | 期望两列车但只收到一列车 | 识别不完整流并扣留新决策 | incomplete_stream_hold | PASS |
| RT-O07 | 断流与恢复 | 缺失列车补齐 | 完整快照恢复为healthy | healthy | PASS |
| RT-O08 | 断流与恢复 | 一列车持续更新、另一列车断流 | 定位T002并扣留新决策 | stream_outage_hold | PASS |
| RT-O09 | 断流与恢复 | 期望集合之外的列车ID | 拒绝且不改变可信游标 | 列车ID不在期望状态集合中 | PASS |
| RT-D01 | 设备状态 | 重复储能设备ID | 输入启动求解前被拒绝 | Duplicate storage runtime state ID: 'S1' | PASS |
| RT-D02 | 设备状态 | 汇总SOC与设备SOC同时提供 | 输入启动求解前被拒绝 | storage_soc_kwh and storage_device_states cannot be supplied together | PASS |
| RT-D03 | 设备状态 | 设备SOC为负数 | 输入启动求解前被拒绝 | storage runtime 'S1' soc_kwh must be non-negative, got -1.0 | PASS |
| RT-D04 | 设备状态 | 设备在线状态不是布尔值 | 输入启动求解前被拒绝 | available must be a boolean | PASS |
| RT-R01 | 滚动恢复 | 完全相同状态重复提交 | 复用结果且不重复求解 | calls=1 | PASS |
| RT-R02 | 滚动恢复 | 不可行扣留后观测变化 | 不锁定坏方案并在新观测后恢复 | waiting_for_observation->recovered_after_observation | PASS |
| RT-R03 | 滚动恢复 | 首次求解不可行 | 一次有界增强重试后自动恢复 | recovered_automatically | PASS |
| RT-R04 | 滚动恢复 | 连续两轮不可行 | 从等待升级到人工处置，均扣留新发车 | waiting_for_observation->manual_intervention_required | PASS |
| RT-R05 | 滚动恢复 | 储能设备在线转停运 | 状态指纹变化并重新求解 | calls=2, changed=True | PASS |

## 生产动作边界

- 非法、过期、未来漂移、重复或乱序消息：拒绝该消息，保持最后可信游标。
- 数据断流：停止形成新的自动决策，保留最后可信状态等待新快照。
- 断流后新鲜有效消息：明确标记恢复，再允许状态进入求解。
- 核心稳健不可行方案：扣留新增发车；连续失败升级人工处置。
- 相同状态重复提交：幂等复用；观测或设备状态变化：重新求解。

## 边界

- 当前阈值是离线测试策略，不代表现场调度规章。
- 本矩阵不连接消息中间件、现场时钟或真实设备。
- 通过矩阵不代表正式数据已验收或可下发控制指令。
