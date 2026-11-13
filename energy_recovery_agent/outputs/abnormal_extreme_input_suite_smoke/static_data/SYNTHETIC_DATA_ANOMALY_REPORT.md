# 合成输入数据异常覆盖报告

本报告验证异常数据在进入仿真、优化和数据库任务执行前能够被统一数据校验入口识别。

- 有效母本：通过
- 异常案例：29
- 通过：29
- 失败：0
- 母本完整性：未改变
- 案例集合指纹：`886c4899517585dfab2aa122411d2d0d28dd8697492513b9d7278c7833dc8096`

| 案例 | 类别 | 注入异常 | 目标文件 | 预期错误码 | 实际错误码 | 结果 |
| --- | --- | --- | --- | --- | --- | --- |
| `SD-F01` | 文件与模式 | 缺少必需文件 | `route_metadata.json` | `missing_file` | `missing_field,missing_file` | PASS |
| `SD-F02` | 文件与模式 | JSON语法损坏 | `battery.json` | `invalid_json` | `invalid_json,missing_field` | PASS |
| `SD-F03` | 文件与模式 | CSV缺少必需列 | `trains.csv` | `missing_column` | `missing_column,missing_value` | PASS |
| `SD-F04` | 文件与模式 | 非法信号制式 | `route_metadata.json` | `invalid_signaling_mode` | `invalid_signaling_mode` | PASS |
| `SD-R01` | 线路与拓扑 | 线路总长为零 | `route_metadata.json` | `number_too_small` | `number_too_small,range_outside_route,segment_coverage_gap,station_outside_route` | PASS |
| `SD-R02` | 线路与拓扑 | 车站名称重复 | `stations.csv` | `duplicate_station` | `duplicate_station,unknown_station` | PASS |
| `SD-R03` | 线路与拓扑 | 车站超出线路 | `stations.csv` | `station_outside_route` | `station_outside_route` | PASS |
| `SD-R04` | 线路与拓扑 | 区段起点留有空隙 | `segments.csv` | `segment_coverage_gap` | `segment_coverage_gap` | PASS |
| `SD-R05` | 线路与拓扑 | 相邻区段重叠 | `segments.csv` | `segment_overlap` | `segment_overlap` | PASS |
| `SD-R06` | 线路与拓扑 | 区段终点不大于起点 | `segments.csv` | `invalid_range` | `invalid_range,segment_coverage_gap` | PASS |
| `SD-R07` | 线路与拓扑 | 坡度为非有限数 | `segments.csv` | `invalid_number` | `invalid_number` | PASS |
| `SD-R08` | 线路与拓扑 | 能量区效率越界 | `energy_transfer_zones.csv` | `invalid_efficiency` | `invalid_efficiency` | PASS |
| `SD-R09` | 线路与拓扑 | 能量区超出线路 | `energy_transfer_zones.csv` | `range_outside_route` | `range_outside_route` | PASS |
| `SD-R10` | 线路与拓扑 | 闭塞方向非法 | `signaling_blocks.csv` | `invalid_direction` | `invalid_direction` | PASS |
| `SD-T01` | 车辆物理 | 列车名称重复 | `trains.csv` | `duplicate_train` | `duplicate_train` | PASS |
| `SD-T02` | 车辆物理 | 牵引力为零 | `trains.csv` | `number_too_small` | `number_too_small` | PASS |
| `SD-T03` | 车辆物理 | 制动力为负 | `trains.csv` | `number_too_small` | `number_too_small` | PASS |
| `SD-T04` | 车辆物理 | 列车方向非法 | `trains.csv` | `invalid_direction` | `invalid_direction` | PASS |
| `SD-T05` | 车辆物理 | 黏着质量比例越界 | `trains.csv` | `number_too_large` | `number_too_large` | PASS |
| `SD-E01` | 储能与电气 | 储能容量为负 | `battery.json` | `number_too_small` | `number_too_small` | PASS |
| `SD-E02` | 储能与电气 | 往返效率大于一 | `battery.json` | `number_too_large` | `number_too_large` | PASS |
| `SD-E03` | 储能与电气 | 充电功率为负 | `battery.json` | `number_too_small` | `number_too_small` | PASS |
| `SD-E04` | 储能与电气 | 规划标记不是布尔值 | `battery.json` | `invalid_boolean` | `invalid_boolean` | PASS |
| `SD-E05` | 储能与电气 | 运行条件列表类型错误 | `operating_conditions.json` | `invalid_list` | `invalid_list` | PASS |
| `SD-C01` | 资源与跨表 | 站场资源引用未知车站 | `station_resources.csv` | `unknown_station` | `unknown_station` | PASS |
| `SD-C02` | 资源与跨表 | 站场股道容量为零 | `station_resources.csv` | `number_too_small` | `number_too_small` | PASS |
| `SD-C03` | 资源与跨表 | 追踪间隔为负 | `headway_constraints.csv` | `number_too_small` | `number_too_small` | PASS |
| `SD-C04` | 资源与跨表 | 作业分配引用未知车站 | `station_operation_assignments.csv` | `unknown_station` | `unknown_station` | PASS |
| `SD-C05` | 资源与跨表 | 作业分配列车类型非法 | `station_operation_assignments.csv` | `invalid_train_type` | `invalid_train_type` | PASS |

## 结论边界

通过表示当前校验器能拒绝这些已枚举的数据异常，不表示工程参数已正式标定，也不替代数据库约束、接口并发和现场系统联调。
