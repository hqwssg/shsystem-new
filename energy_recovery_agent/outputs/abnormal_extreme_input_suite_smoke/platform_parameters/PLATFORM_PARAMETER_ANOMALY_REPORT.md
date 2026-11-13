# 平台任务参数异常测试报告

- 案例数：49
- 通过：49
- 失败：0
- 案例指纹：`eda0343c4843ba7d0db2bb06940c8aedb5c05f3ab5be76dadcbb83b528deb6f1`

| 案例 | 类别 | 任务 | 输入 | 预期 | 实际 | 结果 |
| --- | --- | --- | --- | --- | --- | --- |
| `PP-V01` | 有效边界 | `dispatch` | 最小dispatch请求 | accept | accept | PASS |
| `PP-V02` | 有效边界 | `timetable_audit` | 运行图审查请求 | accept | accept | PASS |
| `PP-V03` | 有效边界 | `timetable_optimization` | 运行图优化请求 | accept | accept | PASS |
| `PP-V04` | 有效边界 | `rolling_rescheduling` | 最小滚动请求 | accept | accept | PASS |
| `PP-V05` | 有效边界 | `joint_parameter_robustness` | 联合稳健请求 | accept | accept | PASS |
| `PP-V06` | 有效边界 | `timetable_optimization` | 概率闭区间下界 | accept | accept | PASS |
| `PP-V07` | 有效边界 | `timetable_optimization` | 概率闭区间上界 | accept | accept | PASS |
| `PP-V08` | 有效边界 | `dispatch` | 零值非负整数 | accept | accept | PASS |
| `PP-V09` | 有效边界 | `rolling_rescheduling` | 设备停运零功率 | accept | accept | PASS |
| `PP-F01` | 结构与白名单 | `dispatch` | 任务参数不是对象 | reject | reject | PASS |
| `PP-F02` | 结构与白名单 | `unknown` | 未知任务类型 | reject | reject | PASS |
| `PP-F03` | 结构与白名单 | `dispatch` | 白名单外字段 | reject | reject | PASS |
| `PP-F04` | 结构与白名单 | `dispatch` | 数值字段使用布尔值 | reject | reject | PASS |
| `PP-F05` | 结构与白名单 | `dispatch` | 布尔字段使用字符串 | reject | reject | PASS |
| `PP-N01` | 数值与枚举 | `dispatch` | 正整数为零 | reject | reject | PASS |
| `PP-N02` | 数值与枚举 | `dispatch` | 非负整数为负 | reject | reject | PASS |
| `PP-N03` | 数值与枚举 | `dispatch` | 整数参数为小数 | reject | reject | PASS |
| `PP-N04` | 数值与枚举 | `dispatch` | 整数秒为小数 | reject | reject | PASS |
| `PP-N05` | 数值与枚举 | `dispatch` | NaN | reject | reject | PASS |
| `PP-N06` | 数值与枚举 | `dispatch` | 正无穷 | reject | reject | PASS |
| `PP-N07` | 数值与枚举 | `timetable_optimization` | 负无穷 | reject | reject | PASS |
| `PP-N08` | 数值与枚举 | `timetable_optimization` | 概率低于零 | reject | reject | PASS |
| `PP-N09` | 数值与枚举 | `timetable_optimization` | 概率高于一 | reject | reject | PASS |
| `PP-N10` | 数值与枚举 | `dispatch` | 非法目标模式 | reject | reject | PASS |
| `PP-N11` | 数值与枚举 | `dispatch` | 非法搜索方法 | reject | reject | PASS |
| `PP-P01` | 快照路径 | `timetable_audit` | 审查缺少运行图路径 | reject | reject | PASS |
| `PP-P02` | 快照路径 | `timetable_optimization` | 优化运行图路径为空 | reject | reject | PASS |
| `PP-P03` | 快照路径 | `timetable_audit` | 运行图绝对路径 | reject | reject | PASS |
| `PP-P04` | 快照路径 | `timetable_audit` | 运行图目录穿越 | reject | reject | PASS |
| `PP-P05` | 快照路径 | `timetable_optimization` | 混合分隔符目录穿越 | reject | reject | PASS |
| `PP-P06` | 快照路径 | `timetable_audit` | 运行图路径不是字符串 | reject | reject | PASS |
| `PP-P07` | 快照路径 | `rolling_rescheduling` | 扰动路径为空 | reject | reject | PASS |
| `PP-P08` | 快照路径 | `rolling_rescheduling` | 扰动路径越界 | reject | reject | PASS |
| `PP-P09` | 快照路径 | `joint_parameter_robustness` | 联合区间路径缺失 | reject | reject | PASS |
| `PP-P10` | 快照路径 | `joint_parameter_robustness` | 联合区间绝对路径 | reject | reject | PASS |
| `PP-P11` | 快照路径 | `timetable_audit` | 逻辑路径过长 | reject | reject | PASS |
| `PP-S01` | 设备状态 | `rolling_rescheduling` | 设备数组为空 | reject | reject | PASS |
| `PP-S02` | 设备状态 | `rolling_rescheduling` | 设备值不是数组 | reject | reject | PASS |
| `PP-S03` | 设备状态 | `rolling_rescheduling` | 设备行不是对象 | reject | reject | PASS |
| `PP-S04` | 设备状态 | `rolling_rescheduling` | 设备缺少SOC | reject | reject | PASS |
| `PP-S05` | 设备状态 | `rolling_rescheduling` | 设备ID为空 | reject | reject | PASS |
| `PP-S06` | 设备状态 | `rolling_rescheduling` | 设备ID重复 | reject | reject | PASS |
| `PP-S07` | 设备状态 | `rolling_rescheduling` | SOC为负 | reject | reject | PASS |
| `PP-S08` | 设备状态 | `rolling_rescheduling` | SOC为无穷 | reject | reject | PASS |
| `PP-S09` | 设备状态 | `rolling_rescheduling` | 可用状态不是布尔值 | reject | reject | PASS |
| `PP-S10` | 设备状态 | `rolling_rescheduling` | 运行功率为负 | reject | reject | PASS |
| `PP-S11` | 设备状态 | `rolling_rescheduling` | 设备含未批准字段 | reject | reject | PASS |
| `PP-S12` | 设备状态 | `rolling_rescheduling` | 设备ID过长 | reject | reject | PASS |
| `PP-S13` | 设备状态 | `rolling_rescheduling` | 回放与设备状态同时提供 | reject | reject | PASS |

通过只表示任务参数在入队前得到确定性校验，不替代数据库权限、并发、租约或现场接口测试。
