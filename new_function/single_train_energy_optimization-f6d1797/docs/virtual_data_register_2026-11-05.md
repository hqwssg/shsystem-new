# 参数字段溯源与虚拟值登记表（2026-11-06）

> 本文件由脚本生成，不要手工编辑。重新生成：
>
> ```bash
> python tools/audit_virtual_data.py --out docs --name virtual_data_register_2026-11-05
> ```

生成时间：2026-11-06 22:06

## 0 用途与换数流程

甲方资料未到位的字段，本项目一律用**取值合理、可追溯的虚拟值**填充，保证算法完整可跑；本表就是这些字段的清单，也是资料到位后逐条替换的工作单。

替换一个字段要同时改三处，缺一处会被 `tests/test_virtual_data_register.py` 拦下：

1. `data/single_train/<文件>.json` 里的数值；
2. 同文件 `field_data_status` 里的溯源等级（`official / real / derived / calibrated / assumed / placeholder`）；
3. 同文件 `provenance` 里的依据出处（写清「谁给的、哪份文件、哪一页/哪张表」）。

改完重新生成本表，并跑一次全量回归。

## 1 汇总

| 参数文件 | 字段数 | official | real | derived | calibrated | assumed | placeholder | synthetic | unknown | 虚拟字段 | 虚拟占比 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 列车参数 | 19 | 4 | 7 | 3 | 1 | 4 | 0 | 0 | 0 | 4 | 21% |
| 电机参数 | 13 | 0 | 0 | 0 | 0 | 10 | 3 | 0 | 0 | 13 | 100% |
| 变流器参数 | 20 | 3 | 0 | 1 | 0 | 4 | 12 | 0 | 0 | 16 | 80% |
| 储能参数 | 12 | 0 | 3 | 3 | 0 | 4 | 2 | 0 | 0 | 6 | 50% |
| **合计** | **64** | **7** | **10** | **7** | **1** | **22** | **17** | **0** | **0** | **39** | **61%** |

口径：`assumed` / `placeholder` / `synthetic` / `unknown` 记为虚拟数据；`real` / `official` / `derived` / `calibrated` 由真实资料或真实数据推算得到，不计入虚拟。

## 2 虚拟字段明细（甲方资料到位后逐条替换）

### 列车参数（4 项）

| 字段 | 中文名 | 取值 | 单位 | 等级 | 依据 |
| --- | --- | ---: | --- | --- | --- |
| `longitudinal_segments` | 纵向离散段数 | 20 | 段 | assumed | 纵向离散段数 20：把列车长度切分为若干段的预留参数，供沿车长坡度加权使用；当前计算取线路区间坡度，未消费该字段 |
| `regen_fraction_cap` | 再生制动占比上限 | 0.85 | — | assumed | 可再生比例上限 0.85：限制再生制动力最多占所需制动力的 85%，其余由摩擦承担；工程预设 |
| `ambient.rolling_multiplier` | 滚动阻力环境修正系数 | 1 | — | assumed | 环境修正系数（滚动 1.0、气动 1.0）：天气与轨面条件接口，与共享项目 operating_conditions.json 的空 weather_conditions 一致；乘 1.0 即不修正 |
| `ambient.aerodynamic_multiplier` | 气动阻力环境修正系数 | 1 | — | assumed | 环境修正系数（滚动 1.0、气动 1.0）：天气与轨面条件接口，与共享项目 operating_conditions.json 的空 weather_conditions 一致；乘 1.0 即不修正 |

### 电机参数（13 项）

| 字段 | 中文名 | 取值 | 单位 | 等级 | 依据 |
| --- | --- | ---: | --- | --- | --- |
| `max_regen_power_w` | 最大再生电功率 | 14400000 | W | assumed | 全列再生功率上限 14400 kW = trains.csv 的 Heavy.max_power_kW（单机持续功率 14400 kW）× 机车台数 1。装配时由共享数据重算并校验；控制侧（本字段）与结算侧（dc_dc.power_rating_w）共用同一来源，不得各维护一份常数。**本字段登记的是 1 台口径**（14.4 MW），台数 ≠ 1 时由装配重算、不校验本值 |
| `max_regen_force_n` | 最大再生制动力 | 691500 | N | assumed | 单台机车电制动力峰值 691.5 kN（10–20 km/h），来自 locomotive_curves.json 的 SHENHUA_12.brake_curve；装配时按台数折算到全列。该值只描述单台电机+变流器的电制动能力，与全列 6200 kN 制动总量不是同一口径 |
| `min_regen_speed_m_per_s` | 最低可再生速度 | 1 | m/s | assumed | 最低可再生速度 1.0 m/s（约 3.6 km/h）：低于该速度再生包络归零，制动力全部转由摩擦承担；工程预设 |
| `regen_efficiency.peak` | 电机峰值效率 | 0.9 | — | assumed | 文献量级的工程预设（重载机车再生制动电效率峰值约 0.90，低速段下降），非实测 |
| `regen_efficiency.peak_load_ratio` | 峰值负载归一化点 | 1 | — | assumed | 文献量级的工程预设（重载机车再生制动电效率峰值约 0.90，低速段下降），非实测 |
| `regen_efficiency.low_load_penalty` | 轻载效率惩罚 | 0.35 | — | assumed | 文献量级的工程预设（重载机车再生制动电效率峰值约 0.90，低速段下降），非实测 |
| `regen_efficiency.low_speed_penalty` | 低速效率惩罚 | 0.25 | — | assumed | 文献量级的工程预设（重载机车再生制动电效率峰值约 0.90，低速段下降），非实测 |
| `regen_efficiency.low_speed_reference_m_per_s` | 低速惩罚参考速度 | 5 | m/s | assumed | 文献量级的工程预设（重载机车再生制动电效率峰值约 0.90，低速段下降），非实测 |
| `dc_link_voltage_window.nominal_v` | 直流母线额定电压 | 1500 | V | placeholder | 工程预设，待正式牵引传动系统资料（网压、中间直流电压、变流器额定）确认 |
| `dc_link_voltage_window.min_v` | 直流母线电压下限 | 1200 | V | placeholder | 工程预设，待正式牵引传动系统资料（网压、中间直流电压、变流器额定）确认 |
| `dc_link_voltage_window.max_v` | 直流母线电压上限 | 1800 | V | placeholder | 工程预设，待正式牵引传动系统资料（网压、中间直流电压、变流器额定）确认 |
| `overvoltage_derate_start_v` | 过压降额起始电压 | 1530 | V | assumed | 过压降额起点 1530 V（约 1.02 倍额定网压）：超过后再生能力随母线电压线性衰减；工程预设 |
| `overvoltage_derate_end_v` | 过压降额终止电压 | 1800 | V | assumed | 过压降额终点 1800 V：到达该电压再生能力降为零并退出，与 dc_dc_parameters.json 的母线窗口上界 1800 V 配套；工程预设 |

### 变流器参数（16 项）

| 字段 | 中文名 | 取值 | 单位 | 等级 | 依据 |
| --- | --- | ---: | --- | --- | --- |
| `inductance_h` | 滤波电感 | 0.0005 | H | placeholder | 滤波电感 0.5 mH：决定电感电流纹波与电流环增益（∂i_L/∂d1 ∝ 1/L），并进入 B_target 解析式；工程预设，待变流器硬件资料确认 |
| `inductor_resistance_ohm` | 电感等效电阻 | 0.002 | Ω | assumed | 电感绕阻直流电阻 0.002 Ω，用于电感铜损 P = i_L²·R 的核算；工程预设，非器件手册值 |
| `input_capacitance_f` | 母线侧输入电容 | 0.02 | F | placeholder | 母线侧输入电容 0.02 F，与源阻抗共同决定母线电压在功率突变时的动态过程；工程预设 |
| `output_capacitance_f` | 储能侧输出电容 | 0.02 | F | placeholder | 储能侧输出电容 0.02 F，同时进入控制通道增益先验 B_target 的分母（∂v_out/∂d2 ∝ 1/C_out）；工程预设 |
| `switching_frequency_hz` | 开关频率 | 5000 | Hz | placeholder | 开关频率 5 kHz：平均模型不显式使用（B_target 与闭环结果对 fs 不敏感），用于纹波核算与器件选型口径；工程预设 |
| `dc_bus_source.open_circuit_voltage_v` | 母线源开路电压 | 1500 | V | placeholder | 母线按「刚性电压源 + 源阻抗 + 输入电容」建模：开路电压 1500 V 取额定网压量级，源阻抗 0.01 Ω 承担母线电压偏差下的功率交换，是再生能量经母线回馈牵引网的物理通道；工程预设 |
| `dc_bus_source.resistance_ohm` | 母线源内阻 | 0.01 | Ω | placeholder | 母线按「刚性电压源 + 源阻抗 + 输入电容」建模：开路电压 1500 V 取额定网压量级，源阻抗 0.01 Ω 承担母线电压偏差下的功率交换，是再生能量经母线回馈牵引网的物理通道；工程预设 |
| `converter_efficiency` | 变流器效率 | 0.97 | — | assumed | 工程预设 0.97（非实测） |
| `power_rating_w` | 变流器额定功率 | 14400000 | W | assumed | 变流器额定 14400 kW，与电机再生功率上限同源：trains.csv 的 Heavy.max_power_kW（单机持续功率）× 机车台数。装配时由共享数据重算并校验，禁止在此另立常数。**本字段登记的是 1 台口径**（14.4 MW），台数 ≠ 1 时由装配重算、不校验本值 |
| `max_output_current_a` | 最大输出电流 | 3000 | A | assumed | 储能侧输出电流上限 3000 A，同时作为 NSMC 的电感电流硬上限 i_L,max；工程预设 |
| `input_voltage_window.min_v` | 母线电压窗口下限 | 1200 | V | placeholder | 母线电压窗口 1200 / 1500 / 1800 V：用于 PWM 安全边界与数值可信度校验，越出 3 倍窗口即抛数值错误；工程预设 |
| `input_voltage_window.nominal_v` | 母线电压窗口额定值 | 1500 | V | placeholder | 母线电压窗口 1200 / 1500 / 1800 V：用于 PWM 安全边界与数值可信度校验，越出 3 倍窗口即抛数值错误；工程预设 |
| `input_voltage_window.max_v` | 母线电压窗口上限 | 1800 | V | placeholder | 母线电压窗口 1200 / 1500 / 1800 V：用于 PWM 安全边界与数值可信度校验，越出 3 倍窗口即抛数值错误；工程预设 |
| `output_voltage_window.min_v` | 储能侧电压窗口下限 | 600 | V | placeholder | 储能侧电压窗口 600 / 1100 / 1500 V：既是物理边界，也是闭环参考电压 v_ref 的上下界来源；工程预设 |
| `output_voltage_window.nominal_v` | 储能侧电压窗口额定值 | 1100 | V | placeholder | 储能侧电压窗口 600 / 1100 / 1500 V：既是物理边界，也是闭环参考电压 v_ref 的上下界来源；工程预设 |
| `output_voltage_window.max_v` | 储能侧电压窗口上限 | 1500 | V | placeholder | 储能侧电压窗口 600 / 1100 / 1500 V：既是物理边界，也是闭环参考电压 v_ref 的上下界来源；工程预设 |

### 储能参数（6 项）

| 字段 | 中文名 | 取值 | 单位 | 等级 | 依据 |
| --- | --- | ---: | --- | --- | --- |
| `soc_min` | SOC 下限 | 0.1 | — | assumed | 荷电状态下限 0.10：到达后充电功率上限被压至 0，不再接受制动能量；工程预设，非实测 |
| `soc_max` | SOC 上限 | 0.9 | — | assumed | 荷电状态上限 0.90：到达后同样拒绝继续充电；上下限共同构成可用能量窗口；工程预设，非实测 |
| `soc_initial` | 初始 SOC | 0.5 | — | assumed | 初始荷电状态 0.5，取可用区间 0.10–0.90 的中点作为统一初态；工程预设。所有控制器必须使用同一初态，回收能量才可横向比较 |
| `max_discharge_power_w` | 最大放电功率 | 2000000 | W | assumed | battery.json -> max_discharge_power_kW = 0.0（missing_conservative_zero）；规划值 planning_max_discharge_power_assumption_kW = 2000.0，本文件采用规划值并标注 assumed |
| `nominal_voltage_v` | 储能额定电压 | 1100 | V | placeholder | 工程预设：待储能系统电气资料替换 |
| `internal_resistance_ohm` | 储能内阻 | 0.02 | Ω | placeholder | 储能等效内阻 0.02 Ω：进入储能侧二参数电压模型，决定参考电压 v_ref 的斜率（结构稳健、幅值敏感）；工程预设 |

## 3 非虚拟字段（已有真实来源）

| 参数文件 | 字段 | 中文名 | 取值 | 单位 | 等级 |
| --- | --- | --- | ---: | --- | --- |
| 列车参数 | `vehicle_mass_tons` | 车辆总重（不含机车） | 21600 | t | real |
| 列车参数 | `basic_resistance.a_n_per_kn` | 基本阻力常数项 | 0.92 | N/kN | official |
| 列车参数 | `basic_resistance.b_n_per_kn_per_kmh` | 基本阻力速度一次项 | 0.0048 | N/(kN·km/h) | official |
| 列车参数 | `basic_resistance.c_n_per_kn_per_kmh2` | 基本阻力速度二次项 | 0.000125 | N/(kN·km/h²) | official |
| 列车参数 | `basic_resistance.curve_equivalent_per_mille_numerator` | 曲线附加阻力等效分子 | 600 | ‰ | official |
| 列车参数 | `mass_kg` | 列车质量 | 21900000 | kg | derived |
| 列车参数 | `locomotive_count` | 机车台数 | 1 | 个 | derived |
| 列车参数 | `electrical_level` | 电制动投入级位 | 0.48 | — | calibrated |
| 列车参数 | `train_length_m` | 列车长度 | 2613.6 | m | real |
| 列车参数 | `rotational_mass_factor` | 旋转质量系数 | 1.06 | — | real |
| 列车参数 | `max_brake_force_n` | 最大制动力 | 6200000 | N | real |
| 列车参数 | `max_regen_force_n` | 最大再生制动力 | 691500 | N | derived |
| 列车参数 | `adhesion.coefficient` | 黏着系数 | 0.28 | — | real |
| 列车参数 | `adhesion.braking_safety_factor` | 制动黏着安全系数 | 0.65 | — | real |
| 列车参数 | `gravity_m_per_s2` | 重力加速度 | 9.81 | m/s² | real |
| 变流器参数 | `duty_limit.u0_max` | 占空比上限 | 0.9 | — | official |
| 变流器参数 | `duty_limit.min` | 占空比下限 | 0 | — | official |
| 变流器参数 | `duty_limit.max` | 占空比物理上限 | 1 | — | official |
| 变流器参数 | `max_input_current_a` | 最大输入电流 | 9600 | A | derived |
| 储能参数 | `capacity_j` | 储能容量（焦耳） | 522000000 | J | derived |
| 储能参数 | `capacity_kwh` | 储能容量 | 145 | kWh | real |
| 储能参数 | `round_trip_efficiency` | 往返效率 | 0.9 | — | real |
| 储能参数 | `charge_efficiency` | 充电效率 | 0.9486832980505138 | — | derived |
| 储能参数 | `discharge_efficiency` | 放电效率 | 0.9486832980505138 | — | derived |
| 储能参数 | `max_charge_power_w` | 最大充电功率 | 2000000 | W | real |

