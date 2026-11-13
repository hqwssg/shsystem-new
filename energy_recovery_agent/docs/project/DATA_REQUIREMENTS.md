# 甲方数据需求说明书

> 本文档面向甲方，说明本项目运行所需的真实数据项、格式及用途。

---

## 一、项目简介

本项目为重载铁路能量管理与列车调度仿真优化系统。系统通过列车运行能耗估算辅助逻辑、多车能量结算、信号安全校验、车站/区间资源冲突检测、NSGA-II 多目标时刻表优化以及 MPC 滚动优化等核心算法，实现以下目标：

- 模拟重载列车在实际线路上的牵引/制动运行过程
- 计算多列车协同运行下的再生制动能量回收与储能系统利用效率
- 优化重载/空载列车发车时刻表，兼顾运营成本与运行秩序
- 校验列车运行计划是否满足信号安全与车站/区间通过能力约束

**所有算法均依赖甲方提供的真实线路与运营数据**，虚拟默认值仅用于系统演示，不能替代现场实际参数。

本项目数据需求只服务于运输组织侧的运行图/重空列协同优化算法。技术方案中涉及的单列车再生制动能量平稳回收控制算法，例如 RHONN、NSMC、EKF/UKF、DC-DC 变换器动态控制等，不纳入本项目数据表和实现范围。

## 一、当前数据接入状态（2026-08-27）

当前默认运行目录是 `data/real_shuohuang`，不是每次运行都重新生成。该目录是“已审查线路资料 + 自动生成派生表 + 必要占位/启发式参数 + 规划假设”的混合数据集；`data/real_partial` 仅保留为历史/兼容数据集。

当前已可用的数据：

- 朔黄线 34 个站点、里程、站型和股道数量。
- 建模边界：神池南 K0+00 至黄骅港 K583+003。
- 2 万吨 C80 代表重车质量 21600 t 和按换长换算的长度 2.6136 km。
- 神池南至 K76+293 的 75 km/h 限速。
- 朔黄线普通货物、万吨、2 万吨追踪间隔，其中 2 万吨 15 min 已接入最小发车间隔。
- 部分站场技术作业时间，当前通过 `station_operation_assignments.csv` 控制应用范围。

仍需甲方补充或确认的数据：

- 逐段坡度、曲线半径、长大下坡真实边界。
- 完整限速表，特别是道岔号到具体里程/股道的映射。
- 真实闭塞分区、咽喉能力、进路锁闭、站场拓扑。
- 牵引/制动曲线、Davis 阻力系数、黏着参数、空车/轻载/混编质量范围。
- 真实运行图、列车任务、作业线、车型辆数与技术作业时间对应关系。
- 柔性供电、供电臂、再生制动效率和储能规划/实施参数。

因此，下文仍列出完整工程化数据需求。若字段已由当前审核资料覆盖，可先采用 `data/real_shuohuang` 中的数据；若字段仍为占位或启发式，后续应以甲方正式数据替换。关于人工输入、低频配置、自动生成数据和运行输出的系统说明，见 [`../current_project_status_and_io.md`](../current_project_status_and_io.md)。

---

## 二、数据文件总览

| 序号 | 文件名 | 格式 | 必需/可选 | 对应算法模块 |
|------|--------|------|-----------|-------------|
| 1 | `route_metadata.json` | JSON | **必需** | 运动学仿真、信号校验、优化器 |
| 2 | `stations.csv` | CSV | **必需** | 运动学仿真、资源冲突检测 |
| 3 | `segments.csv` | CSV | **必需** | 运动学仿真（核心输入） |
| 4 | `trains.csv` | CSV | **必需** | 运动学仿真（核心输入） |
| 5 | `battery.json` | JSON | **必需** | 能量结算、成本优化 |
| 6 | `energy_transfer_zones.csv` | CSV | 可选（强烈建议） | 能量结算（协同利用率） |
| 7 | `signaling_blocks.csv` | CSV | 可选 | 信号安全校验 |
| 8 | `station_resources.csv` | CSV | 可选 | 资源冲突硬约束检测 |
| 9 | `operating_conditions.json` | JSON | 可选 | 运动学仿真（黏着/限速/天气） |
| 10 | `resource_config.json` | JSON | 可选 | 资源模型参数微调 |
| 11 | `headway_constraints.csv` | CSV | 可选（已由 PDF 部分提供） | 调度追踪间隔 |
| 12 | `technical_operation_times.csv` | CSV | 可选（已由 PDF 部分提供） | 站场技术作业占用 |
| 13 | `station_operation_assignments.csv` | CSV | 可选 | 技术作业时间应用规则 |

---

## 三、详细数据需求说明

### 1. route_metadata.json（线路元数据）

**甲方需提供**：线路整体技术参数。

| 字段 | 数据类型 | 单位 | 是否必需 | 取值约束 | 用途说明 |
|------|---------|------|---------|---------|---------|
| `route.total_length_km` | 浮点数 | km | 是 | ≥ 0.1 | 线路运营总长度，决定仿真边界 |
| `route.max_speed_kmh` | 浮点数 | km/h | 是 | ≥ 1.0 | 线路最高允许速度，列车运行速度上限 |
| `route.long_downhill_range_km` | 数组 [start, end] | km | 是 | end > start，且在 [0, total_length_km] 内 | 重载列车长下坡区间，影响再生制动能量计算 |
| `route.signaling_system.mode` | 字符串 | - | 是 | fixed / moving / hybrid | 信号系统模式：固定闭塞、移动闭塞或混合 |
| `route.signaling_system.fixed_block_length_km` | 浮点数 | km | 否 | > 0 | 固定闭塞分区长度，默认 2.0 km |
| `route.signaling_system.fixed_block_protection_blocks` | 整数 | 个 | 否 | ≥ 0 | 固定闭塞防护闭塞数，默认 2 |
| `route.signaling_system.moving_block_base_buffer_m` | 浮点数 | m | 否 | > 0 | 移动闭塞基础安全距离，默认 500 m |
| `route.signaling_system.moving_block_reaction_time_s` | 浮点数 | s | 否 | > 0 | 司机/系统反应时间，默认 30 s |
| `route.signaling_system.moving_block_follower_service_decel_mps2` | 浮点数 | m/s² | 否 | > 0 | 后车常用制动减速度，默认 0.28 |
| `route.signaling_system.moving_block_lead_emergency_decel_mps2` | 浮点数 | m/s² | 否 | > 0 | 前车紧急制动减速度，默认 0.50 |
| `route.signaling_system.check_step_s` | 整数 | s | 否 | ≥ 1 | 信号安全检查时域步长，默认 5 s |
| `route.operating_conditions` | 对象 | - | 否 | - | 可在此嵌套运营条件，或与独立文件二选一 |

**示例**：
```json
{
  "schema_version": "1.0",
  "line_name": "shuohuang_main_line",
  "data_status": "official",
  "route": {
    "total_length_km": 583.003,
    "max_speed_kmh": 120.0,
    "long_downhill_range_km": [0.0, 0.001],
    "signaling_system": {
      "mode": "hybrid",
      "fixed_block_length_km": 2.0,
      "fixed_block_protection_blocks": 2,
      "moving_block_base_buffer_m": 500.0,
      "moving_block_reaction_time_s": 30.0,
      "moving_block_follower_service_decel_mps2": 0.28,
      "moving_block_lead_emergency_decel_mps2": 0.50,
      "check_step_s": 5
    }
  }
}
```

---

### 2. stations.csv（车站列表）

**甲方需提供**：全线所有车站（含会让站、中间站、区段站、编组站/港口站）。

| 字段 | 数据类型 | 单位 | 是否必需 | 取值约束 | 用途说明 |
|------|---------|------|---------|---------|---------|
| `name` | 字符串 | - | 是 | 非空，全表唯一 | 车站标准名称，用于资源冲突报表输出 |
| `position_km` | 浮点数 | km | 是 | ≥ 0，严格递增 | 车站中心里程，用于计算列车到发时刻与位置 |

**说明**：
- 至少提供 **2 个车站**（起点站与终点站）。
- `position_km` 必须按线路方向严格递增，不得重复。
- 建议提供全部会让站与中间站，缺失的车站会导致区间资源模型不完整。

**示例**：
```csv
name,position_km
Shenchi South,0.0
Yinshanzhuang,118.0
Dongye,145.0
Diliudeng,164.0
Xiaojue,200.7
Suning North,362.0
Huanghua Port,583.003
```

---

### 3. segments.csv（线路区间）

**甲方需提供**：线路纵断面（坡度）及平面（曲线）数据，按区间分段。

| 字段 | 数据类型 | 单位 | 是否必需 | 取值约束 | 用途说明 |
|------|---------|------|---------|---------|---------|
| `start_km` | 浮点数 | km | 是 | ≥ 0 | 区间起点里程 |
| `end_km` | 浮点数 | km | 是 | > start_km | 区间终点里程 |
| `gradient_per_mille` | 浮点数 | ‰ | 是 | - | 该段坡度，上坡为正、下坡为负 |
| `curve_radius_m` | 浮点数 | m | 否 | > 0（若存在） | 该段最小曲线半径，用于计算曲线附加阻力 |
| `terrain` | 字符串 | - | 否 | plain / hill / mountain | 地形分类，用于模型校验 |
| `speed_limit_kmh` | 浮点数 | km/h | 否 | > 0（若存在） | 该段静态限速，若低于线路最高速则生效 |

**说明**：
- 区间必须从 **0 km 开始**，**无间隙、无重叠**地连续覆盖至 `total_length_km`。
- 坡度单位是 **‰（千分之）**，而非百分比。
- 若某段无曲线，可将 `curve_radius_m` 留空。
- 若坡度绝对值异常大（如超过 35‰），系统会发出警告请甲方确认。

**示例**：
```csv
start_km,end_km,gradient_per_mille,curve_radius_m,terrain,speed_limit_kmh
0.0,1.0,2.5,800.0,mountain,
1.0,2.0,-3.0,,mountain,
2.0,3.0,1.2,1200.0,hill,100.0
```

---

### 4. trains.csv（列车参数）

**甲方需提供**：至少两种典型列车——重载列车（Loaded/Heavy）与空载列车（Empty）。

| 字段 | 数据类型 | 单位 | 是否必需 | 取值约束 | 用途说明 |
|------|---------|------|---------|---------|---------|
| `name` | 字符串 | - | 是 | 非空，全表唯一，**必须包含 "Heavy" 和 "Empty"** | 列车类别标识 |
| `mass_tons` | 浮点数 | 吨 | 是 | ≥ 1.0 | 列车总重/牵引质量 |
| `max_traction_kN` | 浮点数 | kN | 是 | > 0 | 最大牵引力；可运行列车不能为零 |
| `max_brake_kN` | 浮点数 | kN | 是 | > 0 | 最大制动力；可运行列车不能为零 |
| `rotational_mass_factor` | 浮点数 | - | 是 | ≥ 1.0 | 回转质量系数（考虑轮对等旋转部件） |
| `davis_a` | 浮点数 | - | 是 | ≥ 0 | Davis 方程滚动阻力常数项 |
| `davis_b` | 浮点数 | - | 是 | ≥ 0 | Davis 方程滚动阻力一次项系数 |
| `davis_c` | 浮点数 | - | 是 | ≥ 0 | Davis 方程空气阻力二次项系数 |
| `length_km` | 浮点数 | km | 是 | ≥ 0 | 列车编组后全长 |
| `longitudinal_segments` | 整数 | 段 | 是 | ≥ 1 | 沿列车长度方向的离散采样段数 |
| `direction` | 字符串 | - | 是 | forward / reverse | 运行方向：重载通常为 forward，空载为 reverse |
| `traction_adhesion_weight_fraction` | 浮点数 | - | 是 | [0, 1] | 参与牵引黏着的轴重比例 |
| `brake_adhesion_weight_fraction` | 浮点数 | - | 是 | [0, 1] | 参与制动黏着的轴重比例 |

**说明**：
- `name` 字段必须严格包含 `"Heavy"` 和 `"Empty"` 两行，系统靠这两个关键字识别重载与空载列车。
- `direction` 定义了列车在里程坐标中的前进方向：`forward` 为里程递增方向，`reverse` 为里程递减方向。
- `length_km=0` 表示点质点简化场景，单车仿真和优化器缓存均支持；正式车辆数据仍应提供实际编组长度。
- Davis 系数请提供本单位实际标定值或设计值。

**示例**：
```csv
name,mass_tons,max_traction_kN,max_brake_kN,rotational_mass_factor,davis_a,davis_b,davis_c,length_km,longitudinal_segments,direction,traction_adhesion_weight_fraction,brake_adhesion_weight_fraction
Heavy,10000.0,6000.0,7000.0,1.08,6.5,0.12,0.003,2.7,20,forward,0.22,1.0
Empty,2000.0,3000.0,3500.0,1.05,5.0,0.10,0.0025,2.7,20,reverse,0.55,1.0
```

---

### 5. battery.json（储能系统参数）

**甲方需提供**：地面储能装置（或拟配置储能）的技术经济参数。

| 字段 | 数据类型 | 单位 | 是否必需 | 取值约束 | 用途说明 |
|------|---------|------|---------|---------|---------|
| `capacity_kwh` | 浮点数 | kWh | 是 | ≥ 0 | 储能系统额定容量 |
| `round_trip_efficiency` | 浮点数 | - | 是 | [0, 1] | 充放电往返效率，如 0.90 表示 90% |
| `depreciation_cost_per_kwh` | 浮点数 | 元/kWh | 是 | ≥ 0 | 每吞吐 1 kWh 的电池折旧成本 |
| `grid_price_per_kwh` | 浮点数 | 元/kWh | 是 | ≥ 0 | 当前牵引供电或工业用电电价 |
| `max_charge_power_kW` | 浮点数 | kW | 否 | ≥ 0（若存在） | 储能系统最大充电功率限制 |
| `max_discharge_power_kW` | 浮点数 | kW | 否 | ≥ 0（若存在） | 储能系统最大放电功率限制 |

**说明**：
- 若甲方尚未配置储能但计划配置，请提供设计值或规划值。
- 若 `capacity_kwh` 或 `round_trip_efficiency` 为 0，系统会发出警告。

**示例**：
```json
{
  "capacity_kwh": 20000.0,
  "round_trip_efficiency": 0.9,
  "depreciation_cost_per_kwh": 0.15,
  "grid_price_per_kwh": 0.55,
  "max_charge_power_kW": 20000.0,
  "max_discharge_power_kW": 20000.0
}
```

---

### 6. energy_transfer_zones.csv（能量协同区间）

**甲方需提供**：若已实施或规划柔性牵引供电/再生制动能量协同利用，请提供具体区间。

| 字段 | 数据类型 | 单位 | 是否必需 | 取值约束 | 用途说明 |
|------|---------|------|---------|---------|---------|
| `start_km` | 浮点数 | km | 是（若提供文件） | ≥ 0 | 能量协同区间起点 |
| `end_km` | 浮点数 | km | 是（若提供文件） | > start_km | 能量协同区间终点 |
| `max_transfer_power_kW` | 浮点数 | kW | 否 | > 0（若存在） | 区段变流装置间最大可传输功率 |
| `efficiency` | 浮点数 | - | 否 | (0, 1] | 跨区间能量传输效率 |

**说明**：
- 范围必须在 `[0, total_length_km]` 内。
- 若未提供此文件，系统会使用虚拟默认值，但再生制动协同利用率计算将与现场实际有偏差。

**示例**：
```csv
start_km,end_km,max_transfer_power_kW,efficiency
145.0,164.0,15000.0,0.95
164.0,200.7,15000.0,0.95
```

---

### 7. signaling_blocks.csv（闭塞分区）

**甲方需提供**：实际闭塞分区划分（如有别于按固定长度自动生成）。

| 字段 | 数据类型 | 单位 | 是否必需 | 取值约束 | 用途说明 |
|------|---------|------|---------|---------|---------|
| `block_id` | 字符串 | - | 否 | - | 闭塞分区编号，如 B0001 |
| `start_km` | 浮点数 | km | 是（若提供文件） | ≥ 0 | 分区起点里程 |
| `end_km` | 浮点数 | km | 是（若提供文件） | > start_km | 分区终点里程 |
| `direction` | 字符串 | - | 否 | forward / reverse / both / shared | 适用方向，默认 both |
| `block_type` | 字符串 | - | 否 | fixed / moving | 闭塞类型，默认 fixed |
| `is_single_line` | 布尔值 | - | 否 | true / false | 是否为单线（会让）区段 |

**说明**：
- 若未提供，系统将按照 `route_metadata.json` 中的 `fixed_block_length_km` 自动生成等长闭塞分区。
- 同一方向的分区不允许重叠。

**示例**：
```csv
block_id,start_km,end_km,direction,block_type,is_single_line
B0001,0.0,2.0,both,fixed,false
B0002,2.0,4.0,both,fixed,false
B0003,4.0,6.0,both,fixed,true
```

---

### 8. station_resources.csv（车站资源能力）

**甲方需提供**：主要车站的到发线与咽喉区通过能力（如有实际数据）。

| 字段 | 数据类型 | 单位 | 是否必需 | 取值约束 | 用途说明 |
|------|---------|------|---------|---------|---------|
| `station_name` | 字符串 | - | 是（若提供文件） | 非空，须存在于 stations.csv | 车站名称 |
| `track_capacity` | 整数 | 条 | 是（若提供文件） | ≥ 1 | 到发线股道数 |
| `throat_capacity` | 整数 | 条 | 是（若提供文件） | ≥ 1 | 咽喉区同时可办理进路数 |
| `is_terminal` | 布尔值 | - | 否 | true / false | 是否为端点站/编组站 |

**说明**：
- 若未提供，系统默认：中间站 2 股道、端点站 4 股道、咽喉 1 条进路。
- `station_name` 必须与 `stations.csv` 中的站名严格一致。

**示例**：
```csv
station_name,track_capacity,throat_capacity,is_terminal
Shenchi South,4,1,true
Dongye,2,1,false
Diliudeng,2,1,false
Huanghua Port,4,1,true
```

---

### 9. operating_conditions.json（运营条件）

**甲方需提供**：影响牵引与制动的外部运营条件（如雨季、冬季、临时施工限速等）。

| 字段 | 数据类型 | 单位 | 是否必需 | 取值约束 | 用途说明 |
|------|---------|------|---------|---------|---------|
| `default_adhesion_coefficient` | 浮点数 | - | 否 | ≥ 0.03 | 正常干燥条件下的轮轨黏着系数 |
| `traction_adhesion_safety_factor` | 浮点数 | - | 否 | > 0 | 牵引黏着安全系数，默认 0.85 |
| `braking_adhesion_safety_factor` | 浮点数 | - | 否 | > 0 | 制动黏着安全系数，默认 0.65 |
| `weather_conditions` | 数组 | - | 否 | - | 天气规则列表 |
| `weather_conditions[].name` | 字符串 | - | 是（在数组内） | 非空 | 天气规则名称 |
| `weather_conditions[].start_time_s` | 整数 | s | 否 | ≥ 0 | 规则生效起始时间（距 0 点的秒数） |
| `weather_conditions[].end_time_s` | 整数 | s | 否 | ≥ start_time_s | 规则失效时间 |
| `weather_conditions[].affected_ranges_km` | 数组 | km | 否 | 多组 [start, end] | 受影响区间列表 |
| `weather_conditions[].adhesion_multiplier` | 浮点数 | - | 否 | > 0 | 黏着系数折扣倍率 |
| `weather_conditions[].rolling_resistance_multiplier` | 浮点数 | - | 否 | > 0 | 滚动阻力增加倍率 |
| `weather_conditions[].aerodynamic_resistance_multiplier` | 浮点数 | - | 否 | > 0 | 空气阻力增加倍率 |
| `weather_conditions[].speed_limit_kmh` | 浮点数 | km/h | 否 | > 0 | 天气导致的限速 |
| `adhesion_zones` | 数组 | - | 否 | - | 低黏着区段列表 |
| `adhesion_zones[].name` | 字符串 | - | 是（在数组内） | 非空 | 低黏着区名称 |
| `adhesion_zones[].start_km` | 浮点数 | km | 是（在数组内） | ≥ 0 | 区段起点 |
| `adhesion_zones[].end_km` | 浮点数 | km | 是（在数组内） | > start_km | 区段终点 |
| `adhesion_zones[].start_time_s` | 整数 | s | 否 | ≥ 0 | 生效时间 |
| `adhesion_zones[].end_time_s` | 整数 | s | 否 | ≥ start_time_s | 失效时间 |
| `adhesion_zones[].adhesion_coefficient` | 浮点数 | - | 否 | > 0 | 该区段黏着系数 |
| `speed_restrictions` | 数组 | - | 否 | - | 临时限速（TSR）列表 |
| `speed_restrictions[].name` | 字符串 | - | 是（在数组内） | 非空 | 限速名称 |
| `speed_restrictions[].start_km` | 浮点数 | km | 是（在数组内） | ≥ 0 | 限速区间起点 |
| `speed_restrictions[].end_km` | 浮点数 | km | 是（在数组内） | > start_km | 限速区间终点 |
| `speed_restrictions[].speed_limit_kmh` | 浮点数 | km/h | 是（在数组内） | > 0 | 限速值 |
| `speed_restrictions[].start_time_s` | 整数 | s | 否 | ≥ 0 | 生效时间 |
| `speed_restrictions[].end_time_s` | 整数 | s | 否 | ≥ start_time_s | 失效时间 |
| `speed_restrictions[].reason` | 字符串 | - | 否 | - | 限速原因 |
| `speed_restrictions[].direction` | 字符串 | - | 否 | forward / reverse / both；兼容 down / up / all | 适用运行方向，默认 both |

**说明**：
- 若未提供，系统采用干燥良好天气的默认参数（黏着系数 0.28）。
- 所有里程范围必须在 `[0, total_length_km]` 内。
- `weather_conditions`、`adhesion_zones`、`speed_restrictions` 均必须为数组类型。

**示例**：
```json
{
  "default_adhesion_coefficient": 0.28,
  "traction_adhesion_safety_factor": 0.85,
  "braking_adhesion_safety_factor": 0.65,
  "weather_conditions": [
    {
      "name": "rain_mountain_section",
      "start_time_s": 0,
      "end_time_s": 18000,
      "affected_ranges_km": [[62.0, 302.0]],
      "adhesion_multiplier": 0.70,
      "rolling_resistance_multiplier": 1.04,
      "aerodynamic_resistance_multiplier": 1.02,
      "speed_limit_kmh": 110.0
    }
  ],
  "adhesion_zones": [
    {
      "name": "wet_flexible_power_zone",
      "start_km": 145.0,
      "end_km": 200.7,
      "start_time_s": 0,
      "end_time_s": 18000,
      "adhesion_coefficient": 0.08
    }
  ],
  "speed_restrictions": [
    {
      "name": "maintenance_limit",
      "start_km": 164.0,
      "end_km": 200.7,
      "speed_limit_kmh": 80.0,
      "start_time_s": 1800,
      "end_time_s": 18000,
      "reason": "track maintenance"
    }
  ]
}
```

---

### 10. resource_config.json（资源配置覆盖）

**甲方需提供**：若对默认行车资源模型有调整需求，可提供以下覆盖项。通常无需单独提供。

| 字段 | 数据类型 | 单位 | 是否必需 | 取值约束 | 默认值 | 用途说明 |
|------|---------|------|---------|---------|--------|---------|
| `station_track_capacity` | 整数 | 条 | 否 | > 0 | 2 | 默认中间站股道数 |
| `terminal_track_capacity` | 整数 | 条 | 否 | > 0 | 4 | 默认端点站股道数 |
| `throat_capacity` | 整数 | 条 | 否 | > 0 | 1 | 默认咽喉容量 |
| `station_occupancy_s` | 整数 | s | 否 | > 0 | 180 | 车站占用时长 |
| `throat_occupancy_s` | 整数 | s | 否 | > 0 | 90 | 咽喉占用时长 |
| `section_release_margin_s` | 整数 | s | 否 | > 0 | 30 | 区间释放裕量 |
| `section_capacity_spacing_km` | 浮点数 | km | 否 | > 0 | 8.0 | 区间追踪间隔 |
| `single_line_ranges_km` | 数组 | km | 否 | 多组 [start, end] | [] | 单线区段范围列表 |
| `min_overlap_s` | 整数 | s | 否 | > 0 | 1 | 冲突判定最小重叠时间 |
| `conflict_limit` | 整数 | 条 | 否 | > 0 | 50 | 最大冲突报告条数 |

**说明**：若 `station_resources.csv` 已提供具体车站数据，本文件的默认值将被覆盖。

**示例**：
```json
{
  "station_track_capacity": 2,
  "terminal_track_capacity": 4,
  "throat_capacity": 1,
  "station_occupancy_s": 180,
  "throat_occupancy_s": 90,
  "section_release_margin_s": 30,
  "section_capacity_spacing_km": 8.0,
  "single_line_ranges_km": [],
  "min_overlap_s": 1,
  "conflict_limit": 50
}
```

---

## 四、数据优先级建议

甲方建议按以下优先级准备数据：

| 优先级 | 数据文件 | 原因 |
|--------|---------|------|
| **P0** | `route_metadata.json` | 定义仿真边界与信号模式 |
| **P0** | `stations.csv` | 定义线路节点与资源检测基准 |
| **P0** | `segments.csv` | **核心物理输入**，直接影响列车牵引/制动计算 |
| **P0** | `trains.csv` | **核心物理输入**，直接影响列车动力学模型 |
| **P0** | `battery.json` | **核心经济输入**，决定能量结算与成本优化 |
| **P1** | `energy_transfer_zones.csv` | 决定再生制动能量协同利用率 |
| **P1** | `signaling_blocks.csv` | 决定信号安全校验精度 |
| **P1** | `station_resources.csv` | 决定资源冲突检测真实性 |
| **P2** | `operating_conditions.json` | 提升不同天气/季节下的仿真精度 |
| **P2** | `resource_config.json` | 仅当默认值与现场实际不符时提供 |

---

## 五、数据质量与验证

系统内置严格的数据校验模块，将对甲方提供的数据进行以下检查：

1. **完整性检查**：必填字段不得缺失，必需文件不得缺失。
2. **数值范围检查**：如里程、质量、功率、效率等必须在合理范围内。
3. **逻辑一致性检查**：
   - 车站里程必须严格递增
   - 线路区间必须连续无重叠覆盖全线
   - 闭塞分区同一方向不得重叠
   - 车站资源中的站名必须存在于车站列表中
4. **业务合理性警告**：
   - 坡度绝对值过大（> 35‰）将提示确认单位
   - 黏着系数过高（> 0.45）将提示异常
   - 电池容量或效率为 0 将提示警告

**建议甲方在提供数据前，先自行检查车站里程顺序、区间连续性和列车参数合理性，以减少往返修改。**

---

## 六、联系方式

如甲方在数据准备过程中对字段含义、单位或格式有疑问，请及时沟通确认。
