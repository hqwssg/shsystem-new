# 最小正式数据包设计

更新时间：2026-09-02

本文针对当前算法范围设计最小正式数据包。目标不是一次收齐全部铁路生产资料，而是让甲方分阶段提供数据，尽快完成一轮可审计的正式能量回收与列车调度验证。

## 1. 适用范围

本数据包只服务于：

- 再生制动能量回收能力分析；
- 重车/空车列车调度和运行图优化；
- 供电臂、储能、运输能力和资源约束校验；
- 基线与优化方案的可复现比较。

不要求本数据包包含监测硬件、实时接口、碳排放平台、预测模型或三维可视化数据。

## 2. 分阶段交付策略

### 阶段 A：最小可运行正式包

阶段 A 到位后，可以开始正式线路、车辆、运行图和能量回收的第一轮验证，但结果仍需标注“阶段 A 正式参数结果”，不能替代完整信号安全验收。

| 顺序 | 数据包 | 最小内容 | 作用 |
| --- | --- | --- | --- |
| A1 | 正式运行图 | 典型评价窗口内的重车/空车运行图，至少包含列车 ID、方向、起终点、站点到发时刻、质量/编组引用 | 复现基线调度并比较候选方案 |
| A2 | 车辆动力学 | Heavy 和 Empty 两类车辆的质量、长度、牵引/制动关键曲线、Davis 参数、黏着口径 | 生成正式功率序列和再生能量 |
| A3 | 供电臂边界 | 供电臂起止公里标、方向、储能/回馈规则和真实牵引/再生能力 | 计算供电可接纳能力和电气瓶颈 |
| A4 | 储能参数 | 容量、充放电功率、效率、SOC 边界、接入区段和可用状态 | 计算储能可吸收能力 |

阶段 A 的最小结果：能量账本、回收率、弃电、储能 SOC、基线/优化调度、资源和电气限制报告。

### 阶段 B：完整工程约束包

阶段 B 用于把“正式算法验证”推进到更完整的运输组织和安全能力验证。

| 数据包 | 最小内容 | 作用 |
| --- | --- | --- |
| B1 闭塞/信号 | block_id、方向、起止公里标、闭塞方式、最小追踪/通过能力 | 替换启发式信号资源模型 |
| B2 站场和区间资源 | 股道、咽喉、进路锁闭、区间能力、作业占用时间 | 完善站场/区间冲突检查 |
| B3 初始车流库存 | 各起点/站点/方向的重车、空车和车底库存 | 完整验证车流连续性与车底周转 |
| B4 实测校准样本 | 带车次、时间、位置、方向、功率/电能的可匹配样本 | 校验车辆能耗和再生能量模型 |

## 3. 阶段 A 文件清单

建议投递目录：

```text
data/official_inbox/minimal_package_v1/
  README.md
  manifest.csv
  timetable/
    official_timetable.xlsx
  vehicle_dynamics/
    vehicle_dynamics.xlsx
  power_arm_electrical/
    power_arm_electrical.xlsx
  storage/
    storage.xlsx
  metadata/
    field_mapping.xlsx
    source_confirmation.xlsx
```

甲方也可以提供原生正式文件，不必强行改成模板格式，但必须同时提供字段映射表。

## 4. 阶段 A 必需字段

### 4.1 正式运行图

必须包含：

- `train_id`
- `train_type`：Heavy / Empty 或映射说明
- `direction`
- `origin`、`destination`
- `mass_tons` 或可追溯的编组/车辆引用
- 每个运行站点的 `arrival_time`、`departure_time`
- 评价窗口起止时间和时区

运行图中的列车 ID 必须唯一；同一列车的站点顺序、公里标方向和到发时刻必须单调。

### 4.2 车辆动力学

至少提供：

- `mass_tons`
- `length_km`
- `max_traction_kN`
- `max_brake_kN`
- `rotational_mass_factor`
- `davis_a`、`davis_b`、`davis_c`
- 牵引力—速度离散点或明确的牵引力计算公式
- 制动力—速度离散点或明确的制动力计算公式
- 再生制动启用条件、功率上限和效率口径
- Heavy/Empty 编组和方向映射

如果暂时没有完整曲线，阶段 A 可接受不少于 5 个关键速度点的离散曲线，但必须标注“离散试验点/设计点/等效拟合点”。

### 4.3 供电臂电气能力

至少提供：

- `power_arm_id`
- `start_km`、`end_km`
- `direction`
- `max_traction_supply_kw`
- `max_regen_absorption_kw`
- `max_grid_feedback_kw`
- 上下行供电规则
- 回馈、吸收和跨区段传输规则
- 参数适用日期和设备状态

不能继续使用无限大或“大默认值”作为阶段 A 的正式电气能力。

### 4.4 储能参数

至少提供：

- `storage_id`
- `capacity_kwh`
- `max_charge_power_kW`
- `max_discharge_power_kW`
- 充电效率、放电效率或往返效率
- 初始 SOC 和允许 SOC 范围
- 起止公里标或所属供电臂
- 设备可用/退出状态
- 额定值和降额值的适用条件

如果储能尚未建设，必须明确标注为“规划设计值”，不能在报告中称为现场正式设备结论。

## 5. 每个文件必须附带的元数据

除业务数据外，甲方每个文件至少提供：

| 元数据 | 要求 |
| --- | --- |
| 来源单位/系统 | 明确部门、系统或设备来源 |
| 文件责任人 | 可确认字段含义和版本的人 |
| 数据版本 | 版本号或生效日期 |
| 采集/试验时间 | 尤其是运行图、功率和设备参数 |
| 单位说明 | km、m、kN、kW、kWh、t、s 等 |
| 方向编码 | 上行/下行与 forward/reverse 的映射 |
| 字段映射 | 原字段到内部字段的对应关系 |
| 适用范围 | 车型、编组、线路、设备和工况 |
| 数据状态 | official / derived_from_official / planning_placeholder |
| SHA-256 | 文件交付时的完整性摘要 |

## 6. 阶段 A 验收标准

### 文件层

- 文件数量、大小和 SHA-256 与 `manifest.csv` 一致；
- 原始文件不覆盖历史输入；
- 所有文件有来源、版本、责任人和单位说明；
- 字段映射和方向编码已确认。

### 物理层

- 车辆牵引力、制动力和阻力参数通过范围校验；
- 运行图站点和到发时刻完整；
- 供电臂区间连续且无明显重叠/倒置；
- 储能容量、功率、效率和 SOC 范围合法；
- 关键参数没有未声明的虚拟默认值。

### 算法层

- `validate-data` 无错误；
- `check-ingestion` 通过；
- 基线运行图可以复现；
- 能量发电侧和用电侧守恒；
- SOC 不越界；
- 资源和电气冲突有分类报告；
- 结果包含输入快照、代码快照和输出清单。

## 7. 甲方最简交付方式

如果甲方无法一次完成完整模板，最低可以先交付以下 4 个确认包：

1. 一份真实运行图电子文件；
2. 一份 Heavy/Empty 车辆动力学参数和曲线文件；
3. 一份供电臂边界及牵引/再生能力文件；
4. 一份储能规格和位置文件。

每个文件附一页字段说明、版本、生效日期和责任人信息即可启动阶段 A 接入。闭塞、站场资源、库存和校准样本随后作为阶段 B 补交。

## 8. 当前项目对应模板

- `data_templates/official_intake/vehicle_dynamics_intake.xlsx`
- `data_templates/official_intake/power_arm_electrical_intake.xlsx`
- `data_templates/official_intake/storage_intake.xlsx`
- `data_templates/official_intake/signaling_blocks_intake.xlsx`
- `data_templates/official_intake/initial_inventory_intake.xlsx`
- `data_templates/running_diagram_template.xlsx`

正式数据到位后，仍需执行 `accept-official-data`、`simulate`、`check-results` 和固定种子重复验证；本数据包设计降低的是交付门槛，不降低正式结论的验收标准。
