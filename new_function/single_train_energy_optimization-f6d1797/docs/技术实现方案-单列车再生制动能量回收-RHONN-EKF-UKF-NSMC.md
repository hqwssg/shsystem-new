# 单列车再生制动能量回收算法（RHONN-EKF/UKF-NSMC）技术实现方案

| 项目 | 内容 |
| --- | --- |
| 方案依据 | 《技术方案——列车再生制动回收方案》§4.2.1.3 控制链、公式 (34)(35)(36)(37)；本项目物理模型、控制律与验证记录 |
| 方案用途 | 作为后续生成应用程序的**唯一技术依据**，实现"运行剖面输入 → 闭环能量回收 → 能量核算 → 验证裁定 → 报告导出"全流程 |
| 方法框架 | 递归高阶神经网络（RHONN）+ 扩展/无迹卡尔曼滤波（EKF/UKF）在线权重训练 + 可解释模式切换 + 神经滑模控制（NSMC） |
| 被控对象 | 单列车牵引电机再生电能 → 双向 DC-DC（T1/T2 占空比）→ 车载/沿线储能（SOC 约束） |
| 适用工况 | 平直道常规制动、长大下坡持续再生制动、真实线路区段制动；非开关级仿真 |
| 方案版本 | **V1.0，2026-10-22** |

> **结论属性（贯穿全方案）**：本方案的输出为**离线数字仿真结果**，用于控制链正确性验证、方法对比与参数敏感性分析。
> 仿真结论的适用范围以 9.1 的参数溯源等级与 9.2 的假设清单为界：凡标记为设计取值的参数，
> 其幅值结论不直接外推为线路节能率、设备选型或合同考核依据。
> 参数取值变更后，必须重跑第 8 章全部用例并重新裁定资格。

---

## 1 目标与范围

### 1.1 目标

将技术方案 §4.2.1.3 规定的控制链固化为可运行、可审计、可复现的应用程序，实现：

1. 在电压、电流、SOC 三重约束下，把单列车制动产生的再生电能平稳送入储能，输出两路 PWM 占空比；
2. 用**在线辨识**（RHONN）替代固定参数模型，用 **EKF/UKF** 在线更新网络权重，用**可解释判据**在两种滤波器之间切换；
3. 用 **NSMC** 计算控制量，控制律的每一个符号、每一个量纲、每一个限幅方向都可追溯到公式或物理模型；
4. 建立**严格闭合**的能量台账，把机械制动能量分解为再生、摩擦、各项损耗、回网、回吸、弃能与净存入，做到"一分能量一分去处"；
5. 建立**场景 × 控制器**验证矩阵与**硬门禁 + 性能门禁**两级裁定，输出可复算的对比表与报告；
6. 保留完整审计链：参数溯源等级、参考量装配路径、滤波器模式与切换原因、缺测与拒充计数、源码与参数散列。

### 1.2 范围

| 在范围内 | 说明 |
| --- | --- |
| 单列车再生制动能量回收控制 | 一套控制器驱动一套双向 DC-DC 与一套储能 |
| 牵引电机—变换器—储能动态关联 | 平均模型（averaged model），含电机包络/效率/过压降额 |
| 直流侧高频动态 | 三阶状态方程（`i_L`、`v_in`、`v_out`），RK4 积分 |
| 储能 SOC 约束与拒充退出 | 同拍 BMS 充电许可，许可为 0 时两路占空比归零 |
| 观测量扰动与缺测 | 噪声、偏置、延迟、丢样、连续缺测，均为显式可复现注入 |
| 能量核算与验证 | 台账闭合、波动/跟踪/控制代价指标、14 档场景矩阵、资格裁定 |
| 报告与跨项目导出 | Markdown/Word 报告、1 s 时间桶 CSV/JSON（只含基础事实） |

### 1.3 不在本方案范围

- 重空协同调度（属 `heavy_empty_train_coordination`）；
- 储能站选址定容（规划层）；
- 开关级（switching-level）仿真、器件损耗与电磁兼容；
- 最优速度曲线优化（属 `eco_driving/`，独立问题）；
- 硬件在环、实车试验、牵引网潮流与多车耦合；
- 碳核算、碳交易与节能证书业务功能。

### 1.4 三条不可协商的实现前提

| 编号 | 前提 | 理由与约束 |
| --- | --- | --- |
| P1 | **主算法必须保持 RHONN + EKF/UKF + NSMC 链路** | 允许增加 PI/PID/传统 SMC/理想上界作为对照，**不允许**把主算法替换为纯 PID、纯 MPC、纯强化学习或与本方案无关的结构 |
| P2 | **参数必须分级标注溯源等级** | 每个字段标 `official / real / derived / assumed`；不得把设计取值写成工程定值，不得静默用默认值填充缺失字段 |
| P3 | **禁止静默降级** | 越界、不可达、缺测、参数缺失、装配路径不完整一律**报错或显式标记**；不得钳位后继续、不得用默认分/均值填充、不得把"跑通"当作"有效" |

**P2 与 P3 的落地方式（缺失数据怎么处理）**：甲方资料尚未到位的字段，按「取值合理、可追溯」的虚拟值填充，保证算法链路完整可运行；但每个虚拟值必须同时满足三条——① 在同一参数文件的 `field_data_status` 里标出等级（`assumed` / `placeholder`），② 在 `provenance` 里写清依据（工程惯例、标准表格、或"待正式资料"），③ 进入登记表 `docs/virtual_data_register_<日期>.md`（由 `tools/audit_virtual_data.py` 生成，缺等级或缺溯源即失败）。

虚拟值只承诺**链路完整**，不承诺**幅值正确**：更换为正式资料的字段会改变回收能量与峰值电压，`tests/test_virtual_data_register.py` 与依赖登记（如 `control_channel_gain_prior_dependency`）会在换数时提示是否需要重跑标定。

### 1.5 控制链的三个关键取舍（重要前提）

方案原文只给定控制链骨架（RHONN 状态方程、滑模面、控制律 (34)(35)、EKF/UKF 权重更新），
但其中三处**存在多种可行读法**，且不同读法会导向完全不同的闭环行为。本方案在此固定取舍，
后续第 5 章只给最终式，不再重复论证。

| 取舍点 | 被否决的读法 | 本方案选择 | 否决理由（结构性，非精度差异） |
| --- | --- | --- | --- |
| 参考电压 `v_ref` | 窗口内就地保持 `v_ref = clip(v_out)` | 由 `P_abs` 反解的吸收匹配式 | 就地保持把 `i_sink` 钉死，多余 `i_L` 只能经 `d2` 旁路，实际回收功率远低于可吸收功率；吸收匹配式使 `i_L,ref = P_abs / v_out`，**效率恰好相消**，不含经验系数 |
| 滤波器分工 | 宣称 UKF 精度优于 EKF，按精度择一 | 两者并存，按可解释判据切换 | RHONN 对可调权重是**仿射**的，无迹变换对仿射函数精确，故权重训练上 UKF 与 EKF 逐项恒等；宣称 UKF 更准不成立，并存价值在数值路径冗余与突变工况的鲁棒性 |
| 控制律饱和 | 越界时用 `sign()` 做 bang-bang | 盒约束最小二乘 + 保方向饱和（DPS） | `sign()` 不连续，在离散拍上会激励抖振正反馈；盒最小二乘在可达域边界与无约束解逐位一致且对状态连续 |

**由此确定的三条设计原则**：

1. **不引入无推导的经验系数**——参考量构造中原有的吸收比例系数已删除，改由 `P_abs` 四项取小与 buck 稳态联立给出；
2. **稳定项不得被饱和吃掉**——`u_n` 必须标幺化（否则范数远大于 `u0`，分支恒触发、控制器退化为 bang-bang），且饱和时分支条件与缩放方向必须取同一向量；
3. **不宣称未经证明的优越性**——UKF 与 EKF 的等价性如实写入报告；三档步长一致只是敏感性筛查，不作为误差上界。

> 取舍的代价同样记录在案：`v_ref` 幅值对 `V_oc`、`R_int` 敏感（结构与方向稳健、幅值敏感），
> 故这两个字段的溯源等级变化必须触发参考量敏感性重跑（见 9.4）。

### 1.6 符号与单位

| 符号 | 含义 | 单位 | 说明 |
| --- | --- | --- | --- |
| `m` | 列车总质量 | kg | 含机车、车辆、载荷 |
| `m_eff` | 等效质量 | kg | `m · k_rot`，`k_rot = 1.06` |
| `v` | 速度 | m/s | 外部 km/h 需除以 3.6 |
| `i` | 坡度 | ‰ | 上坡为正、下坡为负 |
| `R` | 曲线半径 | m | 直线段可缺省 |
| `F_brake` | 实际制动力 | N | 受车辆上限与黏着上限双重限制 |
| `P_mech` | 轮周机械制动功率 | W | `F_brake · v` |
| `P_regen` | 轮端可再生机械功率 | W | 受电机包络与再生比例上限限制 |
| `η` | 电机再生效率 | — | 解析模型，不依赖效率云图插值 |
| `d1`,`d2` | T1/T2 占空比 | — | `[0, 0.9]`（`u0 = 0.9` 为方案值） |
| `i_L` | 电感电流 | A | 变流器原生状态量，物理非负 |
| `v_in`,`v_out` | 母线侧/储能侧电压 | V | 窗口 1200–1800 V / 600–1500 V |
| `SOC` | 荷电状态 | — | `[0.10, 0.90]` |
| `V_oc`,`R_int` | 储能开路电压/内阻 | V, Ω | 由额定电压与 SOC 确定 |
| `ω` | RHONN 可调权重 | — | 20 维（2 输出 × (4 并联 + 6 串联)） |
| `P` | 权重协方差 | — | 20×20，半正定 |
| `s` | 滑模面 | — | `s = λ_k (x̂ − x_ref)` |
| `u_eq`,`u_n` | 等效控制/稳定项 | — | 无量纲，与 `u0` 同尺度 |
| `E_*` | 各类能量 | J（输出 kWh） | 1 kWh = 3.6×10⁶ J |

---

## 2 总体流程

### 2.1 五阶段流程

| 阶段 | 名称 | 技术路径 | 对应模块 |
| --- | --- | --- | --- |
| S1 | 准备阶段 | 参数装配 + 运行剖面上线 + 溯源等级核验 | M1、M2 |
| S2 | 对象仿真阶段 | 列车/电机/变流器/储能四段模型按拍推进，RK4 积分 | M3 |
| S3 | 辨识与控制阶段 | 观测处理 → 参考状态 → RHONN 预测 → EKF/UKF 权重更新 → NSMC 输出占空比 | M4–M9 |
| S4 | 计量与核算阶段 | 逐步能量台账 + 场景指标 + 闭合校验 | M10 |
| S5 | 验证与交付阶段 | 场景矩阵 → 硬门禁/性能门禁 → 裁定 → 报告与导出 | M11、M12 |

### 2.2 单步时序（第 k 拍，`Ts` 为控制周期）

```
1. 仿真器按 k−1 拍末状态构造观测量 x_k（电气量、SOC、功率请求、本拍 BMS 许可、有效性标志）
2. 观测处理层：因果滤波（可选）→ 缺测判定
3. 参考状态模块由 x_k 计算 x_ref,k（电压分量 + 电感电流分量）
4. NSMC 用 x̂_k（k−1 拍 RHONN 的一步预测）与 x_ref,k 计算 u_k
5. 辨识器消费 (x_k, u_k)：计算创新 → EKF/UKF 更新权重 → 产生 x̂_{k+1}
6. 仿真器施加 u_k：变流器 RK4 推进 → 储能更新 SOC → 台账累加
```

> **时序纪律**：控制先于辨识（用上一拍预测做本拍决策），辨识消费**实际已施加**的 `u_k`。
> 采样间若 BMS 关闭充电，执行器以零指令同步给控制器与辨识器，**不额外做一次权重校正**。

### 2.3 闭环数据流

```
运行剖面 (t, v, i, R, 限速, 制动指令)
        │
        ▼
列车制动模型 ──► P_mech, P_regen_wheel, P_friction
        │
        ▼
电机再生模型 ──► P_electrical, η, 过压降额
        │
        ▼
双向 DC-DC 平均模型 ◄──── u = (d1, d2) ──── NSMC
        │                                   ▲
        ▼                                   │ x̂, x_ref
储能模型 ──► SOC, 许可 ──► 观测量 ──► RHONN ──► EKF/UKF
        │                                   ▲
        ▼                                   │
能量台账 ──► 指标 ──► 验证矩阵 ──► 裁定 ──► 报告/导出
```

---

## 3 系统级输入 / 输出定义（核心契约）

### 3.1 系统输入

| 编号 | 输入项 | 内容说明 | 格式 | 必填 |
| --- | --- | --- | --- | --- |
| I1 | 列车参数 | 质量、编组、旋转质量系数、最大制动力、再生力上限、再生比例上限、基本阻力系数、黏着 | JSON | 是 |
| I2 | 电机参数 | 最大再生功率/制动力、最低再生速度、效率模型参数、直流母线窗口、过压降额拐点 | JSON | 是 |
| I3 | 变流器参数 | 电感、输入/输出电容、电感电阻、开关频率、效率、额定功率、输入/输出电流上限、占空比限值、母线源、电压窗口 | JSON | 是 |
| I4 | 储能参数 | 容量、往返效率、充/放电效率、SOC 上下限与初值、最大充/放电功率、额定电压、内阻 | JSON | 是 |
| I5 | 运行剖面 | 时间、速度、加速度、坡度、曲线半径、限速、制动指令；或由场景构造器生成 | JSON / 内存序列 | 是 |
| I6 | 仿真配置 | 积分步长 `h`、控制周期 `Ts`、记录抽样间隔、`u0` 开关、最大步数 | JSON | 否（有默认） |
| I7 | 控制器与辨识配置 | profile 名、参考策略、RHONN 结构、EKF/UKF 参数、模式切换阈值、NSMC 参数 | JSON / 数据类 | 否（有默认） |
| I8 | 观测扰动与故障配置 | 相对/绝对噪声、AR(1) 相关、电压/电流偏置、延迟拍数、丢样概率、连续缺测长度、种子 | JSON | 否 |
| I9 | 验证矩阵计划 | 任务名、分组、种子、时长、步长、对照候选清单、期望标签与次数 | JSON 数组 | 否 |
| I10 | 共享线路数据 | 坡度、曲线、限速、站间距、列车与储能基础资料 | 只读 CSV/JSON | 路由场景必填 |

### 3.2 参数文件字段明细

**I1 列车参数（`data/single_train/train_parameters.json`）**

| 字段 | 类型 | 单位 | 取值 | 溯源等级 | 用途 |
| --- | --- | ---: | ---: | --- | --- |
| `mass_kg` | number | kg | 22100000 | derived | 阻力、惯性、黏着（= 车辆总重 21600 t + 12 轴 300 t + 8 轴 200 t） |
| `vehicle_mass_tons` | number | t | 21600 | real | 车辆总重（不含机车） |
| `locomotive_type` | string | — | `SHENHUA_12` | real | 首型机型（取共享曲线）；**整列编组见共享 `locomotive_consist`** |
| `locomotive_count` | integer | 台 | 1 | derived | 机车台数（1 / 2 两套情景） |
| `electrical_level` | number | — | 0.48 | calibrated | 电制动投入级位（只改电/空分摊） |
| `train_length_m` | number | m | 2613.6 | real | 里程定位与分段 |
| `longitudinal_segments` | int | — | 20 | assumed | 纵向分段数（离散设置，当前取线路区间坡度、未消费该字段） |
| `rotational_mass_factor` | number | — | 1.06 | assumed | 等效质量 |
| `max_brake_force_n` | number | N | 6200000 | real | 总制动力上限（空气 + 电制动，**不作再生能力**） |
| `max_regen_force_n` | number | N | 691500 | derived | 单台机车曲线峰值，装配时按台数折算 |
| `regen_fraction_cap` | number | — | 0.85 | assumed | 再生占制动力比例上限 |
| `basic_resistance.a_n_per_kn` | number | N/kN | 0.92 | assumed | 基本阻力常数项 |
| `basic_resistance.b_n_per_kn_per_kmh` | number | N/kN/(km/h) | 0.0048 | assumed | 一次项 |
| `basic_resistance.c_n_per_kn_per_kmh2` | number | N/kN/(km/h)² | 0.000125 | assumed | 二次项 |
| `basic_resistance.curve_equivalent_per_mille_numerator` | number | m·‰ | 600.0 | assumed | 曲线等效坡度 `600/R` |
| `adhesion.coefficient` | number | — | 0.28 | real | 黏着系数 |
| `adhesion.braking_safety_factor` | number | — | 0.65 | real | 制动黏着安全系数 |
| `gravity_m_per_s2` | number | m/s² | 9.81 | real | 重力加速度 |

**I2 电机参数（`motor_parameters.json`）**

| 字段 | 类型 | 单位 | 取值 | 溯源等级 | 用途 |
| --- | --- | ---: | ---: | --- | --- |
| `max_regen_power_w` | number | W | 14400000 | derived | 恒功率区上限（单机持续功率 × 台数） |
| `max_regen_force_n` | number | N | 691500 | derived | 恒转矩区上限（单台曲线峰值 × 台数） |
| `base_speed_m_per_s` | number/null | m/s | null | derived | 拐点，缺省由 `P/F` 推导 |
| `min_regen_speed_m_per_s` | number | m/s | 1.0 | assumed | 低于此速度再生失效 |
| `regen_efficiency.peak` | number | — | 0.90 | assumed | 峰值效率 |
| `regen_efficiency.peak_load_ratio` | number | — | 1.0 | assumed | 峰值负载点（标定入口） |
| `regen_efficiency.low_load_penalty` | number | — | 0.35 | assumed | 轻载惩罚 |
| `regen_efficiency.low_speed_penalty` | number | — | 0.25 | assumed | 低速惩罚 |
| `regen_efficiency.low_speed_reference_m_per_s` | number | m/s | 5.0 | assumed | 低速参考 |
| `overvoltage_derate_start_v` | number | V | 1530.0 | assumed | 降额起点 |
| `overvoltage_derate_end_v` | number | V | 1800.0 | assumed | 完全退出点 |

**I3 变流器参数（`dc_dc_parameters.json`）**

| 字段 | 类型 | 单位 | 取值 | 溯源等级 | 用途 |
| --- | --- | ---: | ---: | --- | --- |
| `inductance_h` | number | H | 0.0005 | assumed | 动态与 `B` 增益 |
| `inductor_resistance_ohm` | number | Ω | 0.002 | assumed | 电感损耗 |
| `input_capacitance_f` | number | F | 0.02 | assumed | 母线动态 |
| `output_capacitance_f` | number | F | 0.02 | assumed | 输出动态与 `B` 增益 |
| `switching_frequency_hz` | number | Hz | 5000 | assumed | 只记录，平均模型不使用 |
| `converter_efficiency` | number | — | 0.97 | assumed | 变流器损耗 |
| `power_rating_w` | number | W | 14400000 | derived | 越额定**只报告不截断**（与电机功率上限同源） |
| `max_input_current_a` | number | A | 9600 | derived | 越限只报告（= 额定 14.4 MW ÷ 母线 1500 V） |
| `max_output_current_a` | number | A | 3000 | assumed | 电感电流参考上限 |
| `duty_limit.u0_max` | number | — | 0.9 | **official** | 方案 §4.2.1.3 PWM 上限 |
| `duty_limit.min/max` | number | — | 0 / 1 | official | PWM 物理硬边界 |
| `dc_bus_source.open_circuit_voltage_v` | number | V | 1500 | assumed | 牵引网刚性源 |
| `dc_bus_source.resistance_ohm` | number | Ω | 0.01 | assumed | 源阻抗、回网通道 |
| `input_voltage_window` | object | V | 1200 / 1500 / 1800 | assumed | 母线窗口 |
| `output_voltage_window` | object | V | 600 / 1100 / 1500 | assumed | 储能侧窗口 |

**I4 储能参数（`storage_parameters.json`）**

| 字段 | 类型 | 单位 | 取值 | 溯源等级 | 用途 |
| --- | --- | ---: | ---: | --- | --- |
| `capacity_kwh` | number | kWh | 145.0 | real | 飞轮 45 + 钛酸锂 100 |
| `capacity_j` | number | J | 5.22×10⁸ | derived | 内部积分 |
| `round_trip_efficiency` | number | — | 0.90 | real | 往返效率 |
| `charge_efficiency` / `discharge_efficiency` | number | — | 0.94868 | derived | 对称分配 `sqrt(0.9)` |
| `soc_min` / `soc_max` | number | — | 0.10 / 0.90 | assumed | SOC 边界 |
| `soc_initial` | number | — | 0.50 | assumed | 初态 |
| `max_charge_power_w` | number | W | 2000000 | real | 充电功率上限 |
| `max_discharge_power_w` | number | W | 2000000 | assumed | 规划容量，本方案仅使用充电通道 |
| `nominal_voltage_v` | number | V | 1100 | assumed | 开路电压 |
| `internal_resistance_ohm` | number | Ω | 0.02 | assumed | 内阻 |

### 3.3 系统输出

| 编号 | 输出项 | 内容说明 | 格式 |
| --- | --- | --- | --- |
| O1 | 控制指令 | 每拍 `duty_cycle_T1`、`duty_cycle_T2`，附 `note`（含拍号与状态） | 内存对象 |
| O2 | 时序记录 | 时间、速度、六类功率、两路占空比、三路电压、四路电流、SOC、效率、降额、参考功率、BMS 许可、控制更新标志 | NPZ / CSV |
| O3 | 能量台账 | 机械制动、轮端再生、摩擦、电机、变流器、电感、储能端口/净存入/损耗、弃能、回网、回吸、源阻抗、无功变化、闭合残差 | JSON / CSV |
| O4 | 场景指标 | 能量类、效率类、波动类、跟踪类、控制代价类、SOC 类、闭合类、越限比例 | JSON / CSV |
| O5 | 审计记录 | controller/profile、参考装配路径、`u_eq` 状态、`x_ref` 状态、辨识健康、模式切换次数与原因、缺测/拒充/负占空比计数、增益先验、源码与参数散列 | JSON |
| O6 | 验证汇总与裁定 | 矩阵逐行指标、四个硬门禁记录、性能门禁逐条判定、失败清单、最终 `decision` | JSON / CSV |
| O7 | 图表与报告 | 电压/电流/SOC/功率曲线、能量结构、对比柱状图、门禁表、结论段落 | PNG / Markdown / Word |
| O8 | 跨项目导出 | 1 s 桶：时间范围、覆盖时长、距离、速度、SOC、机械/再生/吸收/弃能/回网/回吸能量 | CSV / JSON |

### 3.4 输出 JSON 契约（示例）

**O3 + O4（单场景，默认 profile，`Ts = h = 1e-4 s`，`s1_flat_braking`）**

```json
{
  "scenario": "s1_flat_braking[nominal]",
  "controller": "rhonn_nsmc",
  "controller_profile": "default",
  "numerics": {"dt_s": 0.0001, "control_period_s": 0.0001, "record_stride": 10, "steps": 80000},
  "energy_ledger_kwh": {
    "mechanical_braking_energy": 109.356504147,
    "regen_wheel_energy": 47.266404,
    "friction_braking_energy": 62.090100475,
    "motor_electrical_energy": 41.408813124,
    "converter_input_energy": 41.408813124,
    "converter_loss_energy": 1.242264394,
    "converter_inductor_loss_energy": 0.013799422,
    "storage_accepted_energy": 4.370983414,
    "storage_energy_delta": 4.146678961,
    "storage_loss_energy": 0.224304453,
    "grid_export_energy": 33.531913986,
    "grid_import_energy": 0.0,
    "grid_source_loss_energy": 2.248782573,
    "curtailed_energy": 0.0,
    "reactive_energy_delta": 0.001297218,
    "closure_residual_kwh": -0.000227882,
    "closure_relative_residual": 2.084e-06,
    "soc_start": 0.5,
    "soc_end": 0.528598
  },
  "metrics": {
    "capture_ratio": 0.039970036,
    "regenerative_efficiency": 0.105556839,
    "storage_net_of_grid_import_energy": 4.146678961,
    "storage_net_of_grid_import_ratio": 0.037918906,
    "physical_dissipation_energy": 71.676841865,
    "regenerative_chain_loss_energy": 9.586741390,
    "output_voltage_peak_v": 1134.681,
    "inductor_current_peak_a": 1988.4,
    "control_effort_tv": 0.713714,
    "duty_saturation_ratio": 0.000125,
    "voltage_relative_ripple": 3.642e-04
  }
}
```

> 契约要点：
> ① `storage_accepted_energy` 是**端口**吸收电能，`storage_energy_delta` 是**内部净存入**，两者相差储能损耗，不可混用；
> ② `storage_net_of_grid_import_energy = storage_energy_delta − grid_import_energy` 是保守收益口径，可为负；
> ③ `closure_residual` 由 5.12 的闭合式直接算出，是数值正确性的第一判据；
> ④ 本示例中 `capture_ratio` 仅 4.0%、`regenerative_efficiency` 仅 10.6% 并非算法失效——8 s 窗口内 2 MW 充电上限对应的理论吸收上限约 4.44 kWh，本例复算 4.147 kWh 已接近该上限，见 5.4 说明。

**O5（审计摘要）**

```json
{
  "controller": "rhonn_nsmc",
  "controller_profile": "default",
  "u_eq_status": "scheme_authored",
  "x_ref_status": "scheme_authored",
  "reference_strategy": "storage_matched",
  "x_ref_assembly_path": "converter_and_storage",
  "reachability_fallback": "box_least_squares",
  "saturation_norm": "box",
  "control_channel_gain_prior": {
    "sample_time_s": 0.0001,
    "target_b": [[0.75, -9.94], [300.0, 226.8]],
    "data_status": "derived",
    "warm_start_residual": 2.16e-16
  },
  "identification": {
    "filter_mode": "ekf",
    "switch_count": 0,
    "final_mode": "ekf",
    "update_count": 80000,
    "covariance_min_eigenvalue": 3.1e-09,
    "normalised_innovation_p95": 0.031
  },
  "rejected_electrical_measurements": 0,
  "measurement_reanchors": 0,
  "storage_charge_exit_steps": 0,
  "negative_pwm_request_steps": 0,
  "missing_measurement_policy": "两路占空比归零，冻结权重与协方差；下一有效拍重建 RHONN 递归上下文",
  "parameter_data_status": {
    "train": "derived",
    "motor": "assumed",
    "converter": "assumed",
    "storage": "derived"
  },
  "result_kind": "simulation_result_not_engineering_conclusion"
}
```

> `target_b` 的数值随 `Ts`、`v_in`、`i_L` 变化，示例仅示结构；实际值必须由 5.10.3 的解析式按当前工作点重算并写入审计。

---

## 4 功能模块与模块级输入 / 输出

### M1 参数与场景装配模块（S1）

- **职责**：读取四个参数 JSON 与路径配置，校验字段完整性、正负号、上下界与单位一致性；装配 `ComponentBundle`；运行剖面上线前做可达减速度与再生门限校验。
- **输入**：I1–I5、I10。
- **输出**：规范化参数对象；`ProfileSeries`；参数溯源等级字典。
- **关键规则**：
  - 参数文件缺失或字段类型错误 → 抛 `DataLoadError`，不猜默认值；
  - 剖面减速度超过可达上限 → 抛 `ProfileError`，**不静默把减速度改小**；
  - 剖面最低速度低于再生门限 `1.0 m/s` 的 `1.5` 倍 → 抛 `ProfileError`（否则整段退化为"无再生"却仍"跑通"）；
  - 共享线路数据目录**只读**，写入保护在装配层兜底。

### M2 工况剖面生成模块（S1）

- **职责**：生成四类剖面——等减速度制动、减速+恒速保持、真实线路前向积分、分段阶跃制动；统一输出 `time_s / speed_mps / acceleration_mps2 / gradient_per_mille / curve_radius_m / speed_limit_mps / brake_command`。
- **输入**：I1、I5、I10、场景参数。
- **输出**：`ProfileSeries`（含时长、步数、摘要）。
- **关键规则**：构造前调用可达减速度校验；线路场景按公里标只读插值，缺数据时**显式跳过**该族，不生成空剖面。

### M3 物理对象仿真引擎（S2）

- **职责**：按拍推进列车制动、电机再生、双向 DC-DC、储能四段模型；每拍把 `BrakingPowerBreakdown → MotorRegenResult → StorageBusRequest → ControllerCommand → DCConverterStepResult → StorageStepResult → EnergyLedger` 串成闭环。
- **输入**：I1–I4、I5、I6、O1（控制器输出）。
- **输出**：O1 对应的实际施加量、O2 时序数组、O3 台账。
- **关键规则**：
  - 控制周期 `Ts` 必须是积分步长 `h` 的正整数倍，否则报错；
  - 变流器越额定、越电流窗口**只报告不截断**（超出部分经源阻抗回网，是真实物理去向；钳位会使台账无法闭合）；
  - 电压越出 3× 窗口上限 → 抛 `ConverterNumericalError`；
  - 每次 `run()` 开头显式复位被控对象，禁止实例复用继承上一次末态。

### M4 控制器注册与基线目录（S2）

- **职责**：提供统一 `RegenController` 协议（`reset()` / `compute(observation) -> ControllerCommand`），把主算法与 8 项基线装配到同一入口，保证对比口径一致。
- **输入**：`ComponentBundle`、采样步长、profile。
- **输出**：可运行控制器实例 + 目录元数据（label、描述、是否主算法、溯源等级、备注）。
- **基线清单**：无控制（零占空比）、固定 `d1=0.75`、固定 `d1=0.85`、PI、PID、传统 SMC、理想上界、无储能（仅回网）；主算法 `rhonn_nsmc`；族 7 另加固定 EKF / 固定 UKF 两条对照。
- **关键规则**：`ControllerCommand.validate()` 对越界**抛错**，不静默限幅；同一 label 只允许一条装配路径。
- **生命周期约束（重要）**：`reset()` 复位递归与滤波器协方差，但**主算法保留在线学到的权重**（热启动设计，用于连续工况不丢辨识结果）。因此**一个控制器实例只能服务一次 `run()`**：生产路径（基线工厂、验证套件、数据库 CLI、`run_project.py`）每次运行新建实例；若调用方复用实例，第二个场景的前若干拍沿用上一场景权重，读数依赖运行顺序（实测长剖面约 0.085%，几秒级小剖面可使整段不充电）。仿真器检测到 `reset()` 次数 `> 1` 时，会把「控制器实例第 N 次运行」写入 `extra_notes`，供调用方自检。
- **量测预滤波（`default` profile 默认启用）**：控制入口前对**输入电压与输出电压两个通道**做一阶因果 IIR，**时间常数 1.9 ms**（截止 84 Hz）。强度以 `measurement_filter_time_constant_s` 给出，装配时按当次步长折算 α = 1 − exp(−Ts/τ)——若把每拍系数当常数抄到别的步长，滤波带宽会被静默改写。**电流不进入滤波集合**：电感电流是内环快速反馈，1.9 ms 滞后会把峰值推出额定（实测 i_L 峰值 2595→4032 A，额定 3000 A）。τ 由母线物理带宽定窗口：`L = 0.5 mH`、`C = 20 mF` 给出 LC 谐振 50.3 Hz，截止频率必须高于它且远低于 5 kHz 开关频率，1.9 ms 落在窗口内最靠近谐振的一端。功率请求、时间、SOC、BMS 许可与缺测标志保持当拍；缺测/拒充/时间缺口清记忆并在下一有效拍重锚。标定与取舍见 `docs/measurement_prefilter_2026-11-07.md`：交付步长（`dt = 1e-4`）上 1% 噪声达成率 82.9%→96.9%、5% 噪声 66.6%→78.5%、其余 12 场景代价 −0.01%~−0.04%（5% 噪声要上 90% 需状态观测器，不在本轮范围）。

- **储能内阻在线辨识（`default` profile 默认启用）**：参考电压的「储能吸收匹配」式 `v_ref = (V_oc + √(V_oc² + 4·P_abs·R))/2` 中的 `R` 原先取装配值，而对象的真实吸收电流是 `(v_out − V_oc)/R_真`，两者不相等时回收量 **∝ R_装配/R_真**——实测内阻 1.5/2/3 倍时净再生 4.03 → 2.71/2.04/1.36 kWh。R 可由同拍量测反解，故在线估计 `R̂ = (v_out − V_oc)/i_out`，一阶低通（时间常数 0.2 s）后夹紧到 `[0.25, 4] × R_参考`，在 `nsmc.compute` **之前**注入参考；`i_out < 0.1 × max_output_current_a` 时不更新（比值病态），未就绪前继续用装配值。估计值在 1×/2×/3× 下精确收敛到 0.02/0.04/0.06 Ω，s6 内阻 ×2 的达成率 52.1% → 101.5%，其余 11 场景代价 −0.00%~−0.02%。`V_oc` 仍取登记的名义电压（无 SOC-OCV 曲线），故本方法与 `internal_resistance_ohm` / `nominal_voltage_v` 两个 placeholder 的替换进度绑定。标定与取舍见 `docs/storage_resistance_identification_2026-11-07.md`。

### M5 参考状态生成模块（S3）

- **职责**：由观测量与硬件参数生成 `x_ref = (v_ref, i_L,ref)`，作为滑模面的唯一外部指令来源；同时输出参考功率 `P_abs` 供跟踪指标使用。
- **输入**：O2 观测量、I3、I4、参考策略、保护内阻倍率。
- **输出**：`x_ref`、`P_abs`、四项可吸收功率明细、装配路径标识。
- **关键规则**：
  - 正式策略 `storage_matched`：电压分量由"储能吸收该功率所需电压"反解，不用"窗口内就地保持"；
  - `P_abs = min(P_req, P_avail, P_conv, P_storage)`，其中 `P_storage` 取"额定充电功率"与"同拍 BMS 许可"的较小者；
  - `P_req` 是**已过电机包络与效率的直流侧电功率**，`P_avail` 是**轮端机械包络**，两者侧别不同，不得互相替代；
  - 参考量**不钳位真实状态**，只作为控制目标。

### M6 RHONN 辨识模块（S3）

- **职责**：以串联-并联双路径递归高阶神经网络预测下一拍状态 `(v_out, i_L)`；提供对控制量的雅可比 `∂x̂/∂u`。
- **输入**：实际状态 `x_k`、上一拍估计 `x̂_k`、控制量 `u_k`、权重 `ω`。
- **输出**：`state_estimate`、`prediction_error`、`voltage/current_estimate`、权重。
- **关键规则**：基函数只用 `tanh`；并联路径用实际状态，串联路径用估计值（递归项必须存在）；两项加权和不得合并为单层；可调权重 20 维，串联路径权重必须可训练。

### M7 EKF/UKF 权重训练与模式切换（S3）

- **职责**：以辨识误差为创新，在线更新 RHONN 权重与协方差；按六类可解释判据在 EKF 与 UKF 之间切换，输出切换原因。
- **输入**：M6 的预测与雅可比、实际状态、I7 配置。
- **输出**：`filter_mode`、`innovation`、`covariance`、`parameter_update`、`switch_reason`。
- **关键规则**：
  - EKF 协方差用与 `η` 自洽的 Joseph 形式，全程半正定；
  - UKF 状态维取权重维 `L = 20`（非量测维 2），sigma 点 `2L+1 = 41`；
  - 模式切换必须有 `switch_reason`，不允许无理由随机切换；进入/退出阈值形成迟滞带；
  - 缺测拍**冻结**权重与协方差，不把陈旧量测重复当作新创新。

### M8 NSMC 控制模块（S3）

- **职责**：计算滑模面、等效控制、稳定项，经保方向饱和输出两路占空比；处理拒充退出与负占空比审计。
- **输入**：M5 参考、M6 状态估计、M7 权重、观测、I7 配置。
- **输出**：O1 控制指令、可达性标志、`u_eq` 来源、饱和计数。
- **关键规则**：
  - `u_n` 必须无量纲（用状态标幺基准），否则会被 `u0` 饱和分支完全吞掉；
  - 饱和律的分支条件与缩放方向必须是**同一个向量** `u_eq + u_n`；
  - `u0 = 0.9` 是**逐通道**上限，可行域是盒（∞ 范数），不是 2 球；
  - 拒充（许可 = 0）时两路归零并**绕过指令平滑**；辨识器仍消费实际零指令。

### M9 观测处理与安全退出模块（S3）

- **输入**：原始观测、I8 配置、有效性标志。
- **输出**：处理后观测、拒测计数、重锚计数、滤波审计。
- **关键规则**：
  - 只处理四个电气通道（`v_in`、`v_out`、`i_L`、`i_out`），时间/功率请求/SOC/BMS 许可保持当前拍；
  - 有效性标志为 `False` → 两路归零、冻结权重与 `P`、清参考记忆；
  - 首个有效拍只重建 RHONN 递归上下文，不重置权重与全程统计；
  - 该标志来自采集接口或故障注入，**不宣称控制器能诊断未标记的偏置或延迟**。

### M10 能量台账与指标模块（S4）

- **职责**：逐步累加全部能量项；计算场景级能量、效率、波动、跟踪、控制代价、SOC 与闭合指标。
- **输入**：每拍功率、状态、占空比、时间。
- **输出**：O3、O4。
- **关键规则**：闭合式必须包含源阻抗损耗与**电网回吸**（见 5.12）；指标分母必须同侧同口径（跟踪参考取储能侧可吸收功率，不取轮端功率）。

### M11 验证矩阵与资格裁定模块（S5）

- **职责**：构造 10 族 / 14 档场景 × 控制器矩阵；检查四项硬门禁；逐条比较性能门禁；输出裁定与失败清单。
- **输入**：O3、O4、O5、I9。
- **输出**：O6（`summary.csv`、`comparisons.csv`、`acceptance_checks.csv`、`manifest.json`、`decision`）。
- **关键规则**：门禁失败**必须保留**、不得删除任务、不得放宽阈值；统计进程返回 0 不等于资格通过，资格只读 `decision` 字段。

### M12 报告、归档与导出模块（S5）

- **职责**：生成图表与报告；归档全分辨率 NPZ、源码快照、参数、逐阶段台账与运行日志；按白名单导出跨项目时间桶。
- **输入**：O1–O6、I1–I4。
- **输出**：O7、O8、归档目录。
- **关键规则**：导出字段走**白名单**（多一个键即报错，不静默丢弃）；禁止导出权重、协方差、滑模面、占空比、模式切换原因；不得写入共享数据根或协同项目目录。

---

## 5 核心算法与公式

### 5.1 列车制动与再生功率分解

**基本阻力（Davis 形式，`v` 取 km/h）**

```
w0 = a + b·v + c·v²                     [N/kN]
F0 = (w0 / 1000) · m · g                [N]
```

**坡道与曲线附加阻力**

```
Fg = m · g · i / 1000                   i 为坡度 ‰，上坡为正
Fc = m · g · (600 / R) / 1000           R 为曲线半径 m
F_res = F0 + Fg + Fc
```

**需求力与制动力**

```
F_i   = m_eff · a                       m_eff = m · k_rot
F_req = F_i + F_res

F_req < 0  →  F_brake_demand = −F_req · brake_command
F_req ≥ 0  →  F_traction = F_req，制动力为 0
```

**制动力三重限制与再生/摩擦拆分**

```
F_brake_ceiling = min(F_brake_max, μ · m · g · k_adh)
F_brake         = min(F_brake_demand, F_brake_ceiling)
F_regen_wheel   = min(F_brake, F_regen_cap_vehicle, F_loco(v), cap_regen · F_brake)
F_friction      = F_brake − F_regen_wheel

P_mech        = F_brake · v
P_regen_wheel = F_regen_wheel · v
P_friction    = F_friction · v
```

**电制动力曲线 `F_loco(v)`（决定可回收能力的那一项）**

```
F_loco(v) = interp(B_d(km/h), v·3.6) · 1000 · n_loco · level
```

- `B_d(km/h)`：全列等效电制动力曲线，由编组内**各机型曲线按台数逐点求和**得到（神华号 12 轴
  0 km/h → 0 kN、10–20 km/h → 691.5 kN、120 km/h → 432 kN；神华号 8 轴峰值 461.0 kN；
  两万吨 1+1 编组合成峰值 **1 152.5 kN**）。求和取所有机型速度点的并集——分片线性函数之
  和仍是分片线性，在并集节点上逐点求和后再插值，与真实之和**处处相等**，不是拟合；
- `n_loco`：编组内机车总台数（两万吨 1+1 = 2 台）；注意等效曲线已含台数，
  `ElectricalBrakeCurve.locomotive_count` 恒为 1，再乘一次会把补机算两遍；
- `level`：电制动投入级位，取 `0.48`——它**只改电制动与空气制动的分摊，不改总制动力**，
  因此速度轨迹逐位不变，可离线标定。

> 关键口径：`F_brake_max = 6200 kN` 是全列**空气 + 电制动总量**，不是可回收的再生能力。
> 用它当再生上限会把可回收电量高估约一个数量级；真正的瓶颈是 `F_loco(v)`。
> 本方案取值下 10 km/h 处 `F_loco = 331.9 kN`，仅为 `F_brake_max` 的 5.4%。

> 列车层负责 `F_loco(v)` 与再生比例上限；随速度变化的电机包络、效率与过压降额
> 在 5.2 的电机模型中施加，两层职责不重叠。

**可达减速度（构造剖面时必须校验）**

```
decel_max = (F_brake_ceiling + F_res) / m_eff
```

- 下坡 `F_res < 0`：重力占用制动力预算，同样减速度需要更大力，可达上限**更低**；
- 上坡 `F_res > 0`：阻力参与减速，可达上限**更高**；
- 超限直接报错，不静默改小减速度。

> 本方案取值下 `F_brake_ceiling = 6.2×10⁶ N`（车辆上限起作用，黏着上限
> `0.28 × 2.19×10⁷ × 9.81 × 0.65 ≈ 3.91×10⁷ N`），平直道 60 km/h 处可达减速度约 `0.27 m/s²`，
> −9‰ 下坡约 `0.20 m/s²`。

### 5.2 电机再生包络、效率与过压降额

**包络（恒转矩 + 恒功率 + 低速失效）**

```
v_base = P_regen_max / F_regen_max

F_regen_max(v) = F_regen_max           v < v_base
               = P_regen_max / v       v ≥ v_base
               = 0                     v < v_min_regen
```

本方案取值：`v_base = 24.0 MW / 1152.5 kN = 20.82 m/s ≈ 75 km/h`，`v_min_regen = 1.0 m/s`。
（1 台口径下 14.4 MW / 691.5 kN 也是 20.82 m/s——两型机车的功率比与制动力比同为 1.5，
故编组翻倍后 `v_base` 不变，这是可预期的而不是巧合。）
注意 `F_regen_max` 取的是**单台曲线峰值 × 台数**，不含投入级位——级位属于运行策略，
在 5.1 的 `F_loco(v)` 里施加；两处取 min 后由级位起作用。

**直流母线过压降额**

```
derating = 1.0                               v ≤ 1530 V
         = (1800 − v) / (1800 − 1530)        1530 < v < 1800 V
         = 0.0                               v ≥ 1800 V
```

**包络与降额后的实际轮端功率**

```
P_limit = F_regen_max(v) · v · derating
P_wheel = min( P_regen_request, P_limit )
```

**解析效率模型（负载率按实际轮端功率归一）**

```
load_ratio = P_wheel / P_regen_max
r  = min(load_ratio, peak_load_ratio) / peak_load_ratio
η  = peak − low_load_penalty · (1 − r)²
        − low_speed_penalty · max(0, (v_ref − v) / v_ref)²
η  ← clamp(η, 0.05, peak)
```

**电机侧电功率与摩擦拆分**

```
P_electrical = P_wheel · η
P_friction   = P_mech − P_wheel
```

> 关键口径：**降额作用在轮端功率上，不重复乘在效率上**。被包络、低速或过压削减的能量
> 全部计入 `P_friction`，因此「机械制动总功率 = 再生 + 摩擦」在任何工况下恒成立，
> 被削减的能量不会消失。

### 5.3 双向 DC-DC 平均模型

**三阶状态方程**

```
L      di_L/dt   = d1 · v_in − (1 − d2) · v_out − R_L · i_L
C_in   dv_in/dt  = η_conv · i_src + i_grid − d1 · i_L
C_out  dv_out/dt = (1 − d2) · i_L − i_sink
```

**端口电流**

```
i_src  = P_source / max(v_in, V_floor)              电机侧按功率源建模
i_grid = (V_oc_bus − v_in) / R_src                  牵引网：刚性源 + 源阻抗
i_sink = max(0, (v_out − V_oc_st) / R_int)          regen 模式：储能只吸不放
```

**续流二极管单向性**

```
i_L,coupled = max(0, i_L)        P_source ≥ 0（制动）
            = min(0, i_L)        P_source < 0（牵引）
```

并在 `step()` 后对 `i_L` 做投影，保证 `i_L ≥ 0`；否则 `d1 = 0` 时电感电流会无界变负，把 `v_out` 拉到负压（非物理）。

**积分**：RK4，步长 `h`；控制量在 `Ts` 内零阶保持。

**效率实现**：以「输入侧等效电流损失 `(1 − η_conv) · i_src`」实现，保证节点 KCL 与能量守恒严格成立。

**功率口径（必须分清）**

| 字段 | 定义 |
| --- | --- |
| `grid_power_w` | 母线侧功率 `v_in · i_grid` |
| `grid_source_loss_w` | 源阻抗耗散 `i_grid² · R_src`，必须单独立项 |
| `grid_terminal_power_w` | 理想源端功率 `V_oc_bus · i_grid` |
| `grid_terminal_export_power_w` | 真正到达牵引网的功率 `max(0, −terminal)` |
| `grid_terminal_import_power_w` | 从牵引网反向抽取的功率 `max(0, terminal)` |

### 5.4 储能模型与同拍充电许可

**能量守恒**

```
充电：ΔE_stored = η_ch · ∫ P_charge_terminal dt
放电：ΔE_stored = −∫ P_discharge_terminal dt / η_dis
η_ch = η_dis = sqrt(η_round_trip)
```

**SOC 更新与边界**

```
SOC_new = clamp((E_stored + ΔE_stored) / capacity_j, soc_min, soc_max)
```

**可用充电功率（SOC 约束进入控制链的唯一通道）**

```
P_charge_avail(dt) = min( max_charge_power_w,
                          (soc_max − SOC) · capacity_j / dt )
```

**约束优先级（任一触发即削减并记录原因）**

```
1) 功率上限   max_charge_power_w
2) SOC 上限   soc_max → soc_max_limit
3) SOC 下限   soc_min → soc_min_limit
```

**拒充退出**：`P_charge_avail = 0` 时，NSMC 直接输出 `(0, 0)` 并绕过平滑；`v_out` 与能量状态**不做钳位**，由物理模型自然演化。

> **为什么 8 s 剖面只回收约 4.1 kWh**：`P_charge = 2 MW`，8 s 理论吸收上限
> `2 MW × 8 s = 16 MJ ≈ 4.44 kWh`。复算净存入 `4.147 kWh` 已达该上限的 93.4%。
> 因此 `capture_ratio ≈ 4%`、`regenerative_efficiency ≈ 10.6%` 是**储能功率受限**的结果，
> 不是控制律失效。报告必须同时给出「占储能窗口上限的比例」，不能只给回收率。

### 5.5 参考状态 `x_ref`

**可吸收功率（四项取小）**

```
P_req     = requested_regen_power_w          直流母线侧，已过包络与效率
P_avail   = available_regen_power_w          轮端机械包络（不含 SOC、不含变流器）
P_conv    = v_out · i_L,max · η_conv         变流器/电感电流容量
P_storage = min(max_charge_power_w, storage_charge_power_limit_w)   本拍 BMS 许可

P_abs = min(P_req, P_avail, P_conv, P_storage)
```

**电压分量（储能吸收匹配）**

储能侧稳态满足 `i_sink = (v_out − V_oc) / R_int`，要吸收 `P_abs` 需

```
v_out · (v_out − V_oc) / R_int = P_abs
⟹ v_ref = (V_oc + sqrt(V_oc² + 4 · P_abs · R_int)) / 2
v_ref ← clip(v_ref, V_out,min, V_out,max)
```

> **候选构造的取舍**：另一种构造是「窗口内就地保持」`v_ref = clip(v_out, …)`；它把 `i_sink` 钉死，
> 多余的 `i_L` 只能靠 `d2` 旁路，回收功率远小于 `P_abs`。故本方案采用吸收匹配式，`v_ref` 由 `P_abs` 反解。

**电流分量**

```
i_L,ref = clip(P_abs / v_ref, 0, i_L,max)
```

推导：buck 稳态 `v_out = d1 · v_in`；`i_src = P_abs / (η · v_in)`；电荷平衡 `d1 · i_L = η · i_src`。
三式联立得 `i_L = P_abs / v_out`——**效率恰好相消**，故该式不含任何经验标定系数。

**可选反馈策略（研究用，非默认）**

```
storage_current_feedback:
    v_ref = clip(v_meas + R_nom · (P_abs / v_meas − i_sink,meas), V_min, V_max)

storage_guarded_current_feedback:
    V_low  = V_match(P_abs, R_nom)
    V_high = V_match(P_abs, 2.5 · R_nom)
    v_ref  = clip(max(V_low, v_ref,fb), V_low, V_high)
```

两种反馈策略均标 `derived` 且 `reference_review_required = true`，默认不启用；`R_nom` 只是局部修正尺度，不代表真实内阻估计。

### 5.6 RHONN 状态方程

**方案原文结构（两项加权和，不得合并）**

```
x̂_{i,k+1} = ω_{i,k}ᵀ · φ_i(x_k) + ω̄_{i,k}ᵀ · φ_i(x_k, u_k)
```

**本实现基函数（`tanh`，输入先归一化）**

```
φ_par(x_k)       = tanh( α · P_par · (x_k ⊘ s_x) + β )                  ∈ R⁴
φ_ser(x̂_k, u_k)  = tanh( α · P_ser · ([x̂_k, u_k] ⊘ [s_x, s_u]) + β )    ∈ R⁶

P_par = [[1,0],[0,1],[1,1],[1,-1]]
P_ser = [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1],[1,0,1,0],[0,1,0,1]]
```

**参数**：`α = 1.0`、`β = 0.0`、`s_x = (1400 V, 1500 A)`、`s_u = (1, 1)`；可调权重 `2 × 10 = 20` 维，固定权重与可调权重在代码中分离。

**预测与误差**

```
x̂_{k+1} = W_par · φ_par(x_k) + W_ser · φ_ser(x̂_k, u_k)
e_k     = x_k − x̂_k
```

**对控制量的雅可比**

```
B = ∂x̂/∂u = W_ser · ∂φ_ser/∂u
∂φ_ser/∂u = α · (1 − φ_ser²) ⊙ (P_ser[:, 2:4] ⊘ s_u)
```

> **结构约束**：串联路径权重必须进入可调向量，否则 `B` 与可调权重无关、恒不可辨识；
> 并联与串联两段都必须存在，不得用普通 MLP 冒充 RHONN。

### 5.7 EKF 权重训练

**预测**

```
ω⁻ = ω⁺
P⁻ = P⁺ + Q
```

**创新与雅可比**

```
e = x_k − x̂_k
H = ∂x̂/∂ω        （对权重线性，故 H 与 ω 无关，可解析给出）
```

**增益与更新（标准 EKF 形式，`R` 为量测噪声协方差）**

```
S = H · P⁻ · Hᵀ + R
K = P⁻ · Hᵀ · S⁻¹
ω⁺ = ω⁻ + η · K · e
P⁺ = (I − η·K·H) · P⁻ · (I − η·K·H)ᵀ + η² · K · R · Kᵀ + Q
```

> 协方差必须用上式（Joseph 形式）而不是 `P⁺ = (I − KH)P⁻`：
> 当训练步长 `η ≠ 1` 时，后者与权重更新不同步，会让 `P` 失去半正定性。

**参数**：`η = 0.01`（方案值）、`Q = 10⁻⁸ I`、`P_0 = I`、`R = diag(σ_v², σ_i²)`，`σ_v = σ_i = 5`（±5 V / ±5 A 量级，按传感器量程 0.2% 取值，`assumed`）。

### 5.8 UKF 权重训练

**滤波器状态**：权重 `ω`，`L = n_w = 20`；sigma 点 `2L + 1 = 41`。

**采样参数（由方案给定 `η_j^c = 0.02` 反解）**

```
λ      = 1/(2·η_j^c) − L = 5
η_0^m  = λ/(L + λ) = 0.2
η_j^m  = η_j^c = 0.02            j ≥ 1
η_0^c  = η_0^m + (1 − α_ut² + β_ut) ，取 α_ut = 1、β_ut = 2
```

**无迹变换**

```
X_0 = ω⁻,  X_j = ω⁻ ± sqrt((L + λ) · P⁻)_j      j = 1..L
Y_j = h(X_j)                                      h 为 RHONN 预测
ŷ⁻  = Σ_j η_j^m · Y_j
P^yy = Σ_j η_j^c · (Y_j − ŷ⁻)(Y_j − ŷ⁻)ᵀ + R
P^xy = Σ_j η_j^c · (X_j − ω⁻)(Y_j − ŷ⁻)ᵀ
K    = P^xy · (P^yy)⁻¹
ω⁺   = ω⁻ + η · K · (x_k − ŷ⁻)
P⁺   = P⁻ − K · P^yy · Kᵀ + Q
```

**等价性说明（必须如实写入报告）**：RHONN 对可调权重是**仿射**的，无迹变换对仿射函数精确，故权重训练上 `P^yy = H P Hᵀ + R`、`P^xy = P Hᵀ`，UKF 与 EKF **逐项恒等**。两者并存的价值在**数值路径冗余与鲁棒性**，不在精度增益；不得宣称 UKF 比 EKF 更准。

### 5.9 模式切换判据

六类判据均取滑动均值（窗口 `W = 20` 拍），进入阈值与退出阈值按 `exit_ratio` 形成迟滞带：

| 判据 | 计算量 | 进入阈值 | 触发方向 |
| --- | --- | ---: | --- |
| 模型残差 | `‖e ⊘ s_x‖` 滑动均值 | 0.4 | 大 → UKF |
| 非线性指标 | 归一化残差二阶差分范数 | 1.0×10⁻³ | 大 → UKF |
| 工况 jerk | 速度变化率的导数 [m/s³] | 5.0 | 大 → UKF |
| 电流变化率 | `\|di_L/dt\|` [A/s] | 5.0×10⁴ | 大 → UKF |
| 坡度突变 | `\|Δi\|` [‰] | 2.0 | 大 → UKF |
| 功率突变 | `\|ΔP\| / P` | 0.5 | 大 → UKF |

**规则**：

- 最小驻留 `50` 拍（`default`），`balanced` / `robust` 取 `60` 拍，防止阈值附近反复切换；
- 每次切换必须写 `switch_reason`（判据名 + 当前值 + 阈值）；
- `state_scale` 必须与 `RHONNConfig.state_scale` 逐位一致（同源校验），否则阈值的物理含义被悄悄改写。

> **标定基线**：六类阈值在 `dt = 2e-4 s`、`W = 20` 拍下标定（`tools/calibrate_mode_selector.py`：稳态留 ≥2 倍裕度、突变段稳定触发）。
> 判据窗口 `W` 与最小驻留 `dwell` 均以拍计，其物理时长 `= W · Ts`、`dwell · Ts`。改变 `Ts` 或 `W` 时，
> 滑动窗口的物理时长与六类阈值同时失效，必须重新标定，**不得沿用**原阈值。

### 5.10 NSMC 控制律

#### 5.10.1 滑模面

```
s(x_k, k) = λ_k · ( x̂_k − x_ref,k )
λ_k       = 0.9 + 0.1 · e^(−0.1·k)          k 为采样步序号（0,1,2,…）
```

`λ_0 = 1.0`（初期满增益、快速跟踪）→ `λ_k ↓ 0.9`（后期降增益、精准维稳）。主算法与 baseline **共用**该定义，避免口径漂移。

> `k` 为采样步序号，`e^(−0.1k)` 的时间常数为 10 拍，其物理时长为 `10 · Ts`（`Ts = 1e-4 s` 时为 1 ms）。
> 该式按拍定义，跨步长比较须按 `t = k · Ts` 换算：`λ` 的收敛快慢与控制周期绑定，不作为「与步长无关」的性质引用。

#### 5.10.2 稳定项（必须无量纲）

```
u_n = −S_sc · (s ⊘ x_scale)
x_scale = (1100 V, 3000 A)        取变流器额定输出电压与最大输出电流
S_sc = diag(σ, σ),  σ = 0.7        方案区间 [0.6, 0.8] 的中点
```

> 若直接写 `u_n = −S_sc · s`，`u_n` 带 V/A 量纲，范数远大于 `u0 = 0.9`，
> 饱和分支恒触发、稳定项被完全丢弃，控制器退化为 bang-bang。必须用标幺基准。

#### 5.10.3 等效控制 `u_eq`

**一步预测模型**

```
x̂_{k+1} ≈ g(x_k, x̂_k, 0) + B · u_k
B = ∂g/∂u
```

**求解**：令 `s_{k+1} = 0`

```
u_eq* = B⁺ · ( x_ref − g(x_k, x̂_k, 0) )        B⁺ 为 Moore–Penrose 伪逆
```

**`B` 与零控制预测的来源（必须按当前工作点重算）**

```
B(v_out, i_L, v_in) =
  [[ (1 − d2)·v_in·dt² / (2·L·C_out),   −i_L·dt / C_out ],
   [ v_in·dt / L,                        v_out·dt / L   ]]

g(x,0) − x = [ −(v_out + R_L·i_L)·dt / L ,
               (i_L − i_sink)·dt / C_out ]
```

两点必须按此实现：

1. `B` 是**状态相关**的，只在一个标称点精确不够；必须用当前 `(v_out, i_L, v_in)` 逐拍重算，否则 `∂v_out/∂d2` 的符号会在 `i_L ≈ 0` 的起点翻转，导致 `u_eq` 方向错误、占空比被截为 0、控制通道无激励。
2. 零控制预测用**变流器解析增量**，不要用未收敛的辨识网络外推；后者在闭环起点会给出与物理不符的漂移。

#### 5.10.4 一步不可达时的处理

`u_eq*` 越出执行器盒 `[0, u0]²` 时，不采用 bang-bang（`sign()` 不连续，会引发抖振正反馈），而采用**盒约束最小二乘**：

```
u_eq = argmin_{u ∈ [0, u0]²} ‖ (x_ref − g(x,0)) − B·u ‖²
```

求解：令 `c = (u0/2, u0/2)`、`r = x_ref − g − B·c`，在 `‖v‖_∞ ≤ u0/2` 上解 `min ‖r − B·v‖²`，再令 `u = c + v`。该解在可达域边界与无约束解**逐位一致**，且对状态连续。

#### 5.10.5 保方向饱和（DPS）

```
‖u_eq + u_n‖_∞ < u0   →  u = u_eq + u_n
‖u_eq + u_n‖_∞ ≥ u0   →  u = u0 · (u_eq + u_n) / ‖u_eq + u_n‖_∞
```

**三条纪律**：

- 分支条件与缩放方向必须是**同一个向量**；若条件用 `u_eq + u_n`、缩放却用 `u_eq`，越限时 `u_n` 被完全剔除，稳定项失效；
- 范数统一取 ∞（盒）；`u0` 是逐通道上限，可行域是盒，2 球是其真子集，用 2 球会丢掉可用控制权限；
- 该式在 `‖u_eq + u_n‖_∞ = u0` 处连续。

#### 5.10.6 限幅与输出

```
d1 = clamp(u[0], 0, u0)
d2 = clamp(u[1], 0, u0)
```

负值（T2 反向通道请求）截断为 0 并计入 `negative_pwm_request_steps` 审计；输出必须通过 `ControllerCommand.validate()`，越界抛错。

### 5.11 观测处理与安全退出

**观测噪声模型（验证注入，非控制器内部）**

```
y_meas = y_true + relative_std · |y_true| · z1 + absolute_std · z2
z1, z2 ~ N(0, 1)，逐通道独立，种子固定可复现
```

**有色噪声（故障注入）**：AR(1)

```
n_k = ρ · n_{k−1} + sqrt(1 − ρ²) · σ · z_k
```

**偏置/延迟/丢样**：只作用于四个电气通道；时间、功率请求、SOC、BMS 许可保持当前拍。

**缺测策略（`safe_exit`，默认）**

```
electrical_measurement_valid = False
  → 两路占空比 = (0, 0)，绕过平滑
  → 冻结权重 ω 与协方差 P
  → 清空参考记忆
  → 首个有效拍仅重建 RHONN 递归上下文（不清权重、不清全程统计）
```

**边界**：该标志由采集接口或故障注入给出，**不代表**控制器能自动检测未标记的偏置或延迟；报告中不得声称具备该能力。

### 5.12 能量台账与闭合式

**逐步累加（单位 J，输出转 kWh）**

```
E_mech   += P_mech · dt
E_regen  += P_regen_wheel · dt
E_frict  += P_friction · dt
E_motor  += P_electrical · dt
E_conv   += P_conv,in · dt
E_ind    += i_L² · R_L · dt
E_acc    += P_accepted · dt
ΔE_st   += ΔE_stored
E_sloss  += storage_loss
E_curt   += max(0, P_curtailed) · dt
E_export += max(0, P_export) · dt
E_import += max(0, P_import) · dt
E_srcloss+= i_grid² · R_src · dt
```

**闭合式（必须逐项成立）**

```
E_mech = E_frict + E_motor_loss + E_conv_loss + E_ind_loss
       + E_src_loss + E_storage_loss + ΔE_stored
       + ΔE_reactive + E_curtailed + E_grid_net_export
```

其中 `E_motor_loss = E_regen − E_motor`、`E_grid_net_export = E_export − E_import`。

**两个必须入账、漏掉就会产生 0.5% 级残差的项**：

1. **源阻抗耗散** `i_grid² · R_src`：不能并入其他损耗，且 `grid_export` 必须按**理想源端**功率计，不能按母线侧 `v_in · i_grid` 计；
2. **电网侧反向抽取** `E_import`：制动尾段电感电流衰减与启动瞬态会从牵引网补入功率，必须抵扣；用 `max(0, ·)` 丢掉它会让台账凭空出现等量缺口。

**验收**：相对残差 `|residual| / max(E_mech, 1 J)` 在平滑激励下应达 `1e-6` 量级，门禁为 `< 1e-4`。

**派生量（不得混用）**

| 量 | 定义 | 用途 |
| --- | --- | --- |
| `captured_energy` | `E_acc` | 储能端口吸收 |
| `storage_energy` | `ΔE_stored` | 储能净存入（已含储能损耗） |
| `loss_energy` | `E_mech − ΔE_stored` | 未存入储能（含回网，**不是发热耗散**） |
| `storage_net_of_grid_import_energy` | `ΔE_stored − E_import` | 保守收益，可为负 |
| `physical_dissipation_energy` | 摩擦 + 电机 + 变流器 + 电感 + 源阻抗 + 储能损耗 | 真实耗散，不含回网/弃能/电抗 |
| `regenerative_efficiency` | `E_acc / E_motor` | 再生回收效率 |
| `capture_ratio` | `E_acc / E_mech` | 占机械制动能量比例 |

> `control_effort_tv` 是占空比总变差，只描述抖振，**不能**作为开关损耗或能量损失的证据；
> 平均模型与聚合储能效率不提供开关级损耗，也不得额外叠加 `R_int·I²` 重复计算储能损耗。

### 5.13 指标定义

| 类别 | 指标 |
| --- | --- |
| 能量 | 机械制动、轮端再生、摩擦、电机电、变流器输入/输出/损耗、电感损耗、储能吸收/净存入/损耗、弃能、回网/回吸/净回网、源阻抗损耗、无功变化、闭合残差 |
| 效率 | `regenerative_efficiency`、`capture_ratio`、`net_storage_capture_ratio` |
| 波动 | 电压/电流/功率的 `mean`、`std`、`peak_to_peak`、`rms`、`relative_ripple` |
| 跟踪 | `tracking_rmse`、`iae`、`ise`、`max_abs_error`、`final_abs_error`、`settling_time`、`overshoot` |
| 控制代价 | `control_effort_tv`、`control_effort_rate`、`duty_saturation_ratio` |
| 状态 | `soc_start/end/min_seen/max_seen`、`soc_variation` |
| 越限 | `converter_over_rating_ratio`、`converter_input_current_over_limit_ratio` |
| 交叉校核 | `regen_current_energy_kWh`、`regen_current_charge_a_s`、`regen_current_to_motor_ratio`、`regen_current_implied_efficiency`、`regen_current_check_passed`（见 5.13.1） |

**同侧同口径**：跟踪指标的比较基准取**储能侧可吸收功率** `P_abs`，计量取**储能端口接受功率**，两者同侧；不得用轮端再生功率作参考（跨整条变换链，会使全部控制器指标退化为同一量级、丧失分辨力）。

#### 5.13.1 再生电量的第二条口径（标准式 72 电流积分）

再生电量在本方案里有**两条互相独立的计算路径**，同时输出、互不替代：

| 路径 | 表达式 | 输入 | 用途 |
| --- | --- | --- | --- |
| 力-速度-效率 | `Q = ∫ F_regen·v·η(v, 载荷) dt` | 电制动力曲线 `B_d(v)`、电机效率图 | **结算口径**，进入能量台账与闭合式 |
| 标准式(72) | `Q_z = U_w·Σ(I_z(v)·λ·Δt)` | 再生电流表 `I_z(v)`、牵引网电压 `U_w` | **校核口径**，只报告、不入闭合 |

其中 `λ = F_regen / (B_d(v)·台数·级位) ∈ [0,1]` 是电制动曲线利用率：标准表给的是**满级位**电流，实际只用了几成力就折算几成电流（`P = U·I` 且 `P ∝ F·v`）。

三条硬约束：

1. **`U_w` 是接触网电压，不是直流母线电压。** `U_w` 取共享数据 `locomotive_curves.json: regen_energy_formula.U_w_kV`（实测中位 27.2 kV）；本仿真的变流器母线是 1500 V 级，两者差约 18 倍。用错母线电压会把 `Q_z` 算成真值的 5%，且与"没有再生"在结果上无法区分。
2. **两条路径必须能互相解释。** 输出比值 `Q_z / 电机侧电能量` 与其分解量 `Q_z / 轮周再生能量`（标准电流表隐含的轮→网效率）。二者相除即本模型的链上效率，因此总偏差可拆成"标准表自洽性"与"效率假设"两段，而不是一个说不清来源的差。
3. **不可用要显式标注。** 无电流表、无网压、未注入共享数据时，校核字段为空（`null`）而不是 0，并在 `parameter_status.regen_current_check` 写明原因。

> **网压取值（已定）**：`U_w` 统一取 **27.2 kV**（电表 `wy` 字段实测中位，`U_w_data_status = measured_from_smart_meter_wy`），不采用 25 kV 占位值，也不做「校核用 25 kV、结算用 27.2 kV」的双口径——两条路径必须用同一个网压才可比。
>
> **当前状态的定量说明（不构成代码缺陷）**：以交付场景 s1 为例，`Q_z / 电机侧电量 = 1.51`，偏离 1 约 51%。分解后：标准电流表隐含效率约 1.03（`I_z` 表按 25 kV 绘制，改用实测 27.2 kV 后 `Q ∝ U_w` 上浮 8.8%，隐含效率越过 1——该 >1 按本方案口径记录为**已知偏差**，不再作为待改项），本模型链上效率约 0.68（电机效率图为 `assumed`，部分载荷惩罚使 0.90 的峰值效率降到 0.66–0.70）。因此该比值目前是**诊断量**，不作验收门禁：把它当门禁等于用虚拟参数去否决实测数据。电机效率云图到位后，该判据应恢复为 ±10% 硬门禁。

### 5.14 验证门禁与资格判定

**四项硬门禁（每次运行、每个控制器都必须记录）**

| 编号 | 门禁 | 判据 | 失败处理 |
| --- | --- | --- | --- |
| G1 | 物理合规 | `0 ≤ i_L`、`0 ≤ d ≤ u0`、`v_out` 峰值 `< 1500 V`、无 `ConverterNumericalError` | 该运行标 `physical_violation`，保留 |
| G2 | 能量闭合 | `\|residual\| / max(E_mech, 1) < 1e-4` | 标 `closure_failure`，保留 |
| G3 | 辨识健康 | `P` 半正定、`min eig > 0`、创新与权重全为有限值、无 NaN | 标 `health_failure`，保留 |
| G4 | SOC 退出 | `soc_min ≤ SOC ≤ soc_max`；许可为 0 时两路占空比为 0 | 标 `soc_exit_failure`，保留 |

> 「记录通过」与「未记录」是两件事：门禁必须**显式写入**结果文件，缺记录不得当作通过。

**性能门禁（同对象、同初态、同剖面、同周期比较）**

| 编号 | 判据 | 阈值 |
| --- | --- | ---: |
| G5 | 噪声工况净存入对 `current` 严格非负 | `≥ 0` |
| G6 | 对 `smooth055` 严格非负 | `≥ 0` |
| G7 | 对上一轮合格策略严格非负 | `≥ 0` |
| G8 | 非噪声压力条件能量损失 | `< 0.01%` |
| G9 | T1 占空比总变差不高于 `qualified` | `TV ≤ TV_qualified`（含浮点容差） |

**资格判定**

```
全部 G1–G4 有记录且通过            → 基础安全资格成立
且全部 G5–G9 通过                   → qualified
任一性能门禁出现反例                → not_qualified（保留反例，不推广）
矩阵未执行完                        → 资格未完成，不得以局部通过替代
```

**裁定纪律**：

- 不得删除失败任务、不得放宽阈值、不得用均值收益掩盖单条负差额；
- 微小负差额按冻结规则记录为失败，**不因"数值小"放宽**，也不据此宣称工程损失；
- 局部试验资格不得扩大为全条件资格；
- 统计进程成功 ≠ 资格通过；资格只读 `summary.json` 的 `decision`。

### 5.15 数值可信度与步长

| 项 | 要求 |
| --- | --- |
| 时间步长 | 正式验证 `h = 1e-4 s`；数值可信度需三档 `h ∈ {1e-4, 5e-5, 2.5e-5}` |
| 控制周期 | `Ts = 1e-4 s`；`Ts/h` 必须为正整数 |
| 判据 | 最细步长能量相对变化 `≤ 1e-3`，或绝对差 `≤ 1e-5 kWh`；收益跨步长跨度在容差内 |
| 单档证据 | 只有一档 `h` 的种子标 `incomplete_step_grid`，**不授予**数值可信度 |
| 表述边界 | 三档一致只是**经验步长敏感性筛查**，不是严格误差上界、不是统计置信区间、不是全局最优证明 |

---

## 6 数据文件与接口格式

### 6.1 文件与目录

| 路径 | 内容 | 读写 |
| --- | --- | --- |
| `configs/data_paths.yaml` | 共享数据根、本项目数据根、实验输出根、只读开关 | 读 |
| `data/single_train/train_parameters.json` | 列车参数 | 读 |
| `data/single_train/motor_parameters.json` | 电机参数 | 读 |
| `data/single_train/dc_dc_parameters.json` | 变流器参数 | 读 |
| `data/single_train/storage_parameters.json` | 储能参数 | 读 |
| `data/data_manifest.yaml` | 数据清单与溯源登记 | 读 |
| `configs/*_jobs_*.json` | 验证矩阵计划（任务、分组、种子、候选、期望次数） | 读 |
| `configs/*_frozen_*.json` | 冻结选择与参数快照 | 读 |
| `data/experiments/<run_id>/summary.json` | 场景 × 控制器指标 + 免责声明 + 参数状态 | 写 |
| `data/experiments/<run_id>/summary.csv` | 同上，扁平表 | 写 |
| `data/experiments/<run_id>/manifest.json` | 运行元信息、场景族、闭合超差清单、主算法诊断 | 写 |
| `data/experiments/<run_id>/timeseries_*.csv` | 逐步记录（抽样） | 写 |
| `data/experiments/<run_id>/runs/*.npz` | 全分辨率时序、逐阶段台账、源码快照、参数 | 写 |
| `data/experiments/<run_id>/cross_project/*.csv/json` | 1 s 桶导出（白名单） | 写 |

### 6.2 命令行入口

```bash
# 物理底座 + 基线控制器（默认 Scenario 1/2 × 基线）
python run_project.py --dt 2e-4 --scenario 1 --scenario 2

# 真实线路区段（需要共享数据）
python run_project.py --scenario route --route-start-km 108 --route-v0-kmh 70

# 完整验证矩阵（14 档 × 8 基线 + 主算法）
python tools/run_validation_suite.py --dt 1e-4 --out data/experiments/<run_id>

# 观测故障与偏置专项
python tools/validate_observation_faults.py

# 长期连续运行与 SOC 压力
python tools/validate_long_term_operation.py

# 跨项目 1 s 桶导出
python tools/export_cross_project.py --run-id <run_id>

# 全量回归与静态检查
python -m pytest tests -q
python -m ruff check --select F,E7,E9,B006,B011,B023 .
python tools/lint_ast_probe.py $(git ls-files '*.py')

# 数据清单校验
python tools/check_data_manifest.py --strict

# 参数字段溯源与虚拟值登记表（缺等级/缺溯源即失败，退出码 1）
python tools/audit_virtual_data.py --out docs --name virtual_data_register_<日期> --csv
```

### 6.3 Python 接口清单（供应用程序调用）

| 接口 | 签名要点 | 返回 |
| --- | --- | --- |
| `load_project_paths()` | 无参 | `ProjectPaths`（含只读保护） |
| `load_component_bundle(paths)` | 路径对象 | `ComponentBundle`（四段模型 + 参数状态） |
| `build_simulator(bundle)` | 组件包 | `RegenerativeBrakingSimulator` |
| `build_simulator.run(series, controller, config)` | 剖面、控制器、`SimulationConfig` | `SimulationResult` |
| `build_validation_scenarios(bundle, dt, shared=None)` | 组件包、步长、共享数据 | `Tuple[ValidationScenario, ...]` |
| `baseline_catalog(profile="default")` | profile、参考策略 | `Tuple[ValidationBaseline, ...]` |
| `build_closed_loop_controller(...)` | 变流器 + 储能参数、步长、profile | `ClosedLoopController` |
| `build_reference_state(converter, storage, strategy)` | 参数对象、策略 | `RegenerativeReferenceState` |
| `run_validation_suite(...)` | 场景、步长、抽样、profile | `Tuple[SuiteRunRecord, ...]` |
| `write_suite_outputs(records, out_dir, ...)` | 记录、目录、元信息 | `summary.csv / manifest.json` |
| `build_comparison_rows(records, optimized_labels)` | 记录、主算法标签 | 对比行（`baseline / optimized / delta / delta_percent`） |
| `export_cross_project(run_dir, out_dir)` | 运行目录、输出目录 | 1 s 桶 CSV/JSON |

### 6.4 时序记录字段（NPZ / CSV）

| 字段 | 单位 | 说明 |
| --- | --- | --- |
| `time_s` | s | 时间 |
| `speed_mps` | m/s | 速度 |
| `mechanical_braking_power_w` | W | 轮周机械制动功率 |
| `regen_wheel_power_w` | W | 轮端可再生机械功率 |
| `friction_braking_power_w` | W | 转入摩擦的功率 |
| `motor_electrical_power_w` | W | 直流侧电机电功率 |
| `duty_cycle_T1` / `duty_cycle_T2` | — | 两路占空比 |
| `input_voltage_v` / `input_current_a` | V / A | 母线侧 |
| `inductor_current_a` | A | 电感电流 |
| `output_voltage_v` / `output_current_a` | V / A | 储能侧 |
| `output_power_w` | W | 储能端口功率 |
| `reference_power_w` | W | 储能侧可吸收功率（跟踪基准） |
| `accepted_power_w` / `curtailed_power_w` | W | 接受 / 削减 |
| `grid_export_power_w` / `grid_import_power_w` | W | 回网 / 回吸 |
| `grid_source_loss_w` | W | 源阻抗耗散 |
| `soc` | — | 荷电状态 |
| `motor_efficiency` / `dc_link_derating` | — | 效率 / 降额系数 |
| `storage_charge_power_limit_w` | W | 同拍 BMS 许可 |
| `control_update` / `charge_safety_override` | bool | 控制更新 / 采样间拒充 |

### 6.5 跨项目导出白名单

允许：`bucket_index`、`bucket_start_s`、`bucket_end_s`、`distance_m`、`mean_speed_mps`、`soc_start`、`soc_end`、`mechanical_braking_energy_kwh`、`available_regenerative_energy_kwh`、`storage_accepted_energy_kwh`、`curtailed_energy_kwh`、`grid_export_energy_kwh`、`grid_import_energy_kwh`、`source_controller`、`data_status`、`disclaimer`。

禁止：RHONN 权重、EKF/UKF 协方差、滑模面、模式切换原因、占空比、母线纹波、跟踪误差、参考量。

导出目录必须落在**本项目**实验根下；写入共享数据根或协同项目目录一律报错。

---

## 7 应用程序实现设计

### 7.1 技术栈建议

| 层 | 建议 | 理由 |
| --- | --- | --- |
| 计算内核 | Python 3.11+、NumPy 2.x、SciPy | 与现有实现同源，RK4/矩阵运算/滤波无需重写 |
| 数值后端（可选） | Numba 或 Cython | 主算法约 2200 步/s，长线路需加速时使用；先保证逐位一致再启用 |
| 服务层 | FastAPI + Pydantic v2 | 输入校验与 OpenAPI 契约天然对应第 3 章 I/O 定义 |
| 任务调度 | RQ / Celery + Redis | 单次矩阵可达数十分钟，需异步任务与进度回传 |
| 前端 | React + TypeScript + ECharts | 曲线、能量结构、门禁表可视化 |
| 单机替代 | PySide6 | 无服务端部署条件时的桌面版 |
| 存储 | SQLite（单机）/ PostgreSQL（多人） | 运行记录、指标、审计链 |
| 报告 | python-docx + matplotlib | Word 报告与 PNG 图表 |
| 测试与质量 | pytest、ruff、AST 扫描 | 与现有 980 项回归、静态检查口径一致 |

### 7.2 分层架构

```
接入层    CLI / REST API / 桌面 UI
  │
应用层    用例编排：装配 → 自检 → 运行 → 统计 → 裁定 → 报告
  │
领域层    仿真引擎 / 辨识 / 控制 / 计量 / 验证（纯 Python，无 UI 依赖）
  │
基础设施  参数与数据访问（只读保护）、实验归档、任务队列、日志
```

**硬性约束**：

- 领域层不得依赖 UI、数据库或网络；
- 控制器只能通过 `ControllerObservation` 获取信息，禁止旁路读取仿真真值；
- 同一物理量只允许一个来源（如电感电流上限只能来自变流器参数对象），禁止在多层各写一份。

### 7.3 界面流程（五步）

| 步骤 | 界面内容 | 必须展示 |
| --- | --- | --- |
| ① 参数与场景 | 四类参数上传/编辑、溯源等级标签、剖面上传或场景选择 | 每个字段的 `official/real/derived/assumed` 标签 |
| ② 对象自检 | 可达减速度、再生门限、SOC 余量、窗口合法性 | 自检通过/失败原因；失败禁止进入下一步 |
| ③ 控制配置与运行 | profile、参考策略、EKF/UKF、NSMC 参数、步长、种子 | 装配路径、`u0`、`Ts/h` 比值、预计步数 |
| ④ 结果与门禁 | 曲线、能量结构、指标表、四项硬门禁、性能门禁 | 峰值电压/电流、闭合残差、SOC 轨迹、失败条目 |
| ⑤ 报告与导出 | 报告预览、图表、1 s 桶导出 | 免责声明、参数状态、裁定结论 |

**界面纪律**：不得提供"一键美化结果"或"隐藏失败行"；失败项必须以红色常驻显示，导出文件同样保留。

### 7.4 校验与错误处理

| 场景 | 处理 | 禁止行为 |
| --- | --- | --- |
| 参数文件缺失 | 抛 `DataLoadError`，列出缺失文件名 | 用内置默认值补齐 |
| 字段类型/单位不符 | 抛错并指出字段与期望 | 静默转换 |
| 剖面减速度不可达 | 抛 `ProfileError` | 自动改小减速度 |
| 剖面速度低于再生门限 | 抛 `ProfileError` | 生成"无再生"空场景 |
| `Ts/h` 非整数 | 抛 `SimulationError` | 四舍五入 |
| 占空比越界 | 抛 `ControllerError` | 静默钳位 |
| 电压越 3× 窗口 | 抛 `ConverterNumericalError` | 继续积分 |
| 缺测 | 两路归零、冻结权重、记录计数 | 重复使用最后有效值继续校正 |
| 装配参数只给一半 | 抛 `ClosedLoopError` | 静默退化到不完整口径 |
| 矩阵任务未跑完 | 标 `资格未完成` | 用已完成部分宣布通过 |

### 7.5 性能基线

| 项 | 参考值 | 条件 |
| --- | --- | --- |
| 基线控制器单场景 | 2.18 s / 80 000 步 | `s1`，`h = 1e-4`，零占空比 |
| 主算法单场景 | 36.9–41.2 s / 80 000 步 | `s1`，`h = Ts = 1e-4`，约 2 200 步/s |
| 长大下坡单场景 | 30.9 s / 57 038 步 | `s2`，`h = Ts = 1e-4` |
| 完整矩阵 | 128 次 / 378 s | `dt = 2e-4`，14 档 × 9 控制器 |
| 收尾验收矩阵 | 135 次 / 270 个 NPZ | `Ts = h = 1e-4`，8 项任务 |
| 全量回归 | 980 passed / 265.9 s | `pytest tests -q`，2026-10-14 快照；用例数以实际运行计数为准 |
| 静态检查 | Ruff 通过；AST 178 文件 / 0 发现 | 受 Git 跟踪的 Python 源码 |

**容量建议**：单次运行内存与步数成正比（80 000 步约数十 MB）；全分辨率归档 270 个 NPZ 约数 GB，建议按任务分目录、按需清理中间产物，但**不得删除已裁定运行的归档**。

---

## 8 测试与验收用例

### 8.1 物理与对象模型（T1–T10）

| 编号 | 用例 | 输入构造 | 预期 |
| --- | --- | --- | --- |
| T1 | 制动力三重限制 | 制动剖面使需求制动力超车辆上限或黏着上限 | 逐拍 `F_brake ≤ min(需求, 6.2 MN, μ·m·g·k_adh)` |
| T2 | 再生/摩擦拆分守恒 | 任意制动拍，含包络削减段与过压降额段 | `F_regen + F_friction = F_brake`，误差 `≤1e-9 N` |
| T3 | 不可达减速度被拒绝 | 构造减速度超过可达上限的剖面 | 抛 `ProfileError`，**不得**静默改小 |
| T4 | 电机包络拐点 | 速度扫描跨 `v_base = 4.65 m/s`，并含 `v < 1.0 m/s` | `v < v_base` 恒转矩、`v ≥ v_base` 恒功率；`v < v_min` 包络为 0 |
| T5 | 效率模型有界 | `load_ratio` 由 0 扫到 1.2、`v` 由 1 扫到 30 m/s | `0.05 ≤ η ≤ peak`，轻载与低速方向单调下降 |
| T6 | 过压降额守恒 | 母线电压由 1500 V 升至 1800 V | 被削减的再生功率等量转入摩擦，`P_mech` 不变 |
| T7 | 变流器续流单向性 | regen 模式，`i_L` 取正初值后置 `d1 = 0` | `i_L` 衰减到 0 不反向 |
| T8 | 变流器数值边界 | 母线或输出侧电压越 3× 窗口 | 抛 `ConverterNumericalError` |
| T9 | 储能 SOC 边界 | 初值 0.50，持续充电至 0.90 后仍请求充电 | 全程 `soc_min ≤ SOC ≤ soc_max`，充满后充电功率削为 0 |
| T10 | 储能能量守恒 | 一段纯充电 + 一段纯放电 | 充电 `ΔE = η_ch ∫P`、放电 `ΔE = −∫P/η_dis`，误差 `≤1e-9` |

### 8.2 辨识与控制（T11–T20）

| 编号 | 用例 | 输入构造 | 预期 |
| --- | --- | --- | --- |
| T11 | RHONN 结构完整性 | 读取权重向量与基函数集合 | 并联 + 串联双路径、两项加权和、仅 `tanh`、可调权重 20 维 |
| T12 | 递归项存在 | 改变上一拍 `x̂_k` 后重算本拍预测 | 本拍预测随之改变（串联路径确实消费递归量） |
| T13 | EKF 协方差半正定 | `η = 0.01` 与 `η = 1` 两档，各跑完整剖面 | 全程 `min eig(P) > 0` |
| T14 | EKF 收敛性 | 平稳工况（恒速、恒坡度）长时运行 | 预测相对误差单调下降并收敛 |
| T15 | UKF sigma 点正确性 | 对仿射函数执行无迹变换 | `2L+1 = 41`，均值与协方差被精确复原 |
| T16 | UKF ≡ EKF（权重训练） | 同初值、同数据，两滤波器各跑一遍 | 权重更新逐项一致，容差 `1e-10` |
| T17 | 模式切换可解释 | 六类判据各构造一次超阈触发 | 每次切换写 `switch_reason`（判据名 + 当前值 + 阈值） |
| T18 | 迟滞有效 | 判据指标在阈值附近上下浮动 | 不出现连续反复切换；驻留步数达标 |
| T19 | 滑模面与 `λ_k` | 取 `k = 0`、`k = 10`、`k` 充分大三点 | `λ_0 = 1.0`、`λ_∞ → 0.9`；主算法与 baseline 调用同一函数 |
| T20 | `u_n` 无量纲 | 任取一步，给定 `s` 与 `x_scale` | `‖u_n‖` 与 `u0` 同量级，不得恒触发饱和分支 |

### 8.3 闭环与安全（T21–T30）

| 编号 | 用例 | 输入构造 | 预期 |
| --- | --- | --- | --- |
| T21 | 闭环能量非零 | `s1` 默认参数、默认 profile | 回收能量显著大于 0（不得为 0.0） |
| T22 | `B` 可辨识 | 取相邻拍 `B` 矩阵比较 | `max\|ΔB\| > 0`；`det(B) ≠ 0`、`rank = 2` |
| T23 | 增益先验缩放律 | `L × 0.5` 与 `C_out × 0.5` 各跑一次，其余不变 | `∂i_L/∂d1` 恰 2 倍；`∂v_out/∂d2` 恰 2 倍 |
| T24 | `u_eq` 可达时精确 | 分别构造可达与越界两种状态 | 未越界拍输出标准解；越界拍输出盒最小二乘解，边界连续 |
| T25 | 饱和律方向保持 | 放大滑模面使进入强饱和 | `u = u0·(u_eq+u_n)/‖·‖_∞`，方向不变、范数不超 `u0` |
| T26 | 占空比合法性 | 全剖面扫描控制输出 | 全部 `∈[0, 0.9]`；负请求截断并计数 |
| T27 | 拒充退出 | 同拍 BMS 充电许可置 0 | 当拍两路为 0，且不经过平滑 |
| T28 | 缺测安全退出 | 注入连续 5 拍电气量测缺失后恢复 | 无效拍两路为 0、权重与 `P` 冻结；恢复拍重锚计数 +1 |
| T29 | 参考装配唯一路径 | 只提供 `V_oc`、`R_int` 之一 | 抛错；两参数齐全时 `x_ref_assembly_path` 与策略一致 |
| T30 | 实例复用隔离 | 同一仿真器连续跑两次同一剖面 | **被控对象**复位后与新建实例逐位一致（基线控制器）；**主算法控制器**因 `reset()` 保留在线权重，复用实例即热启动，读数会漂移，故生产路径每次新建，复用发生时结果 `extra_notes` 显式标注「控制器实例第 N 次运行」 |

### 8.4 计量、验证与工程（T31–T40）

| 编号 | 用例 | 输入构造 | 预期 |
| --- | --- | --- | --- |
| T31 | 台账闭合 | `s1`、`s2` 默认参数全剖面 | 相对残差 `< 1e-4`；平滑激励下约 `2e-6` |
| T32 | 回吸入账 | 制动尾段电感电流衰减与启动瞬态 | `grid_import > 0` 且闭合仍成立 |
| T33 | 源阻抗单独立项 | 同 T32 工况 | `grid_source_loss > 0` 且不被并入其他损耗 |
| T34 | 指标同侧 | 取 `reference_power_w` 与储能端口接受功率比较 | 两者同侧（储能侧），不得取轮端功率 |
| T35 | 场景族完整性 | 有共享数据 / 无共享数据两种情况各跑一次 | 10 族 / 14 档全部存在；缺共享数据时族 R 显式缺席 |
| T36 | 再生门限防护 | 构造最低速度 `< 1.5 × 1.0 m/s` 的剖面 | 构造失败（抛 `ProfileError`） |
| T37 | 四项硬门禁有记录 | 任一运行结束后读结果文件 | 四个字段均写入，缺记录即失败 |
| T38 | 性能门禁逐条 | 全部候选的完整验证矩阵 | 逐条判定；反例保留在 `acceptance_checks.csv`，不得删除或合并 |
| T39 | 跨项目白名单 | 导出时多写一个字段，或命中内部状态键名黑名单 | 报错 |
| T40 | 输出可复现 | 同种子、同步长、同参数跑两次 | NPZ 散列相同，逐位一致 |

### 8.5 参考读数（回归对照，默认 profile，`Ts = h = 1e-4 s`）

| 场景 | 机械制动 kWh | 端口吸收 kWh | 净存入 kWh | 回网 kWh | 输出峰值 V | 电感峰值 A | 相对闭合 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `s1_flat_braking` | 109.3565 | 4.3710 | 4.146679 | 33.5319 | 1134.681 | 1988.4 | 2.08e-06 |
| `s2_long_downhill` | 29.0529 | 3.1162 | 2.956285 | 16.0696 | 1134.696 | 1988.5 | 1.83e-06 |

> 上表是默认 profile（`default`）在基准运行环境下 `Ts = h = 1e-4 s` 的读数，用于回归对照。
> 全矩阵验收（135 次）覆盖全部五种固定装配，输出峰值 `1414.825 V`、最大相对闭合 `1.3985e-05`；
> 27 条性能门禁候选中 26 条通过，1 条在 5% 量测噪声下出现能量反例，按 T38 保留反例记录并判 `not_qualified`，
> 该候选不纳入默认装配。引用任何能量数字必须同时写明**步长、装配与口径**。

### 8.6 验收汇总

| 判定项 | 结果 | 判据 | 结论 |
| --- | --- | --- | --- |
| 用例集 T1–T40 | 由 `python -m pytest tests -q` 覆盖 | 见 8.1–8.4 逐条输入与预期 | 通过（1091 passed / 5 skipped） |
| 台账相对闭合 | 矩阵最大 `1.3985e-05` | `< 1e-4` | 通过 |
| 输出峰值电压 | 矩阵最大 `1414.825 V` | `< 1500 V` | 通过 |
| 性能门禁 | 27 条候选 26 条通过 | 逐条无能量反例 | 1 条反例保留，该候选不纳入默认装配 |
| 静态检查 | Ruff 通过；AST 178 文件 / 0 发现 | 零告警 | 通过 |
| 再生电量交叉校核（§5.13.1） | s1：`Q_z` 6.811325 kWh，`Q_z/电机侧` 1.5076 | 诊断量，判据见 5.13.1 | 记录在案；效率图为 `assumed` 期间不作门禁 |

> 裁定规则：四项硬门禁（物理、闭合、辨识健康、SOC 退出）任一失败即判不可用；性能门禁出现反例即不授予该候选资格，
> 反例记录不得删除或合并。交付状态为**主算法链路可运行、可复算、可审计**；
> 结论幅值的适用边界见 9.1 溯源等级与 9.2 假设清单。

---

## 9 实现级假设与可配置项清单

原方案未固定、需由本方案具体化并以配置项形式暴露的内容如下。每一项都标注溯源等级与引用约束，
允许项目方按实际资料覆盖；覆盖后的必做动作见 9.4，按改动性质分类见 9.5。

### 9.1 参数溯源等级

参数按溯源等级分级标注。等级描述取值的**来源类别**，与工程进度无关：同一份参数集中可以同时存在多级，
每一级都在报告与导出中显式携带，不允许把设计取值当作定值引用。

| 等级 | 定义 | 引用约束 |
| --- | --- | --- |
| `official` | 技术方案原文给定 | 可直接作为约束 |
| `real` | 有明确资料来源 | 可用于报告，须注明来源 |
| `derived` | 由已知量推导 | 可复算，须给出推导式 |
| `assumed` | 按工程设计经验取值，未经专项标定 | 幅值结论限于仿真研究，不外推为工程定值 |

> 参数文件（`data/single_train/*.json`）在文件级 `data_status` 与字段级 `field_data_status` 两层记录等级，
> 枚举取值为 `official / real / derived / assumed / placeholder`；其中 `placeholder` 表示**结构性标称值**
> （按典型工程设计给定的量级，用于链路贯通与灵敏度分析），在溯源语义上归入 `assumed` 类呈现。
> 每个字段的具体出处由 `provenance` 记录，报告与导出必须原样携带，不得在传递中丢失等级或降级使用。

### 9.2 假设清单

| 编号 | 假设 | 影响 | 依据出处 |
| --- | --- | --- | --- |
| A1 | 整备质量 22 100 t = 车辆总重 21 600 t（216 辆 × 100 t）+ 12 轴 300 t + 8 轴 200 t（两万吨 **1+1 两台**） | 制动力、惯性、能量预算 | 编组模式文档「1+1（交+交）」、运行图技术资料 p7「12 轴 + 8 轴」，并经能量守恒校核（单机违反物理下界 36%） |
| A2 | 最大制动力 6.2 MN 取共享 `trains.csv:max_brake_kN`（空气 + 电制动总量） | 制动能力上限（**不作再生能力**） | 车辆制动特性资料 |
| A3 | 旋转质量系数 1.06 | 等效质量 | 车辆惯量资料 |
| A4 | 基本阻力采用 `per_kN_speed_kmh` 形式 | 阻力与下坡可达减速度 | 线路阻力试验资料 |
| A5 | 黏着系数 0.28、制动安全系数 0.65 | 黏着上限 | 轮轨黏着试验资料 |
| A6 | 电机峰值效率 0.90、轻载/低速惩罚 0.35/0.25 | 再生电功率 | 电机效率云图 |
| A7 | 过压降额 1530→1800 V 线性 | 高母线电压下的再生能力 | 牵引传动过压保护定值 |
| A8 | 电感 0.5 mH、电容 20 mF、开关频率 5 kHz | 动态、`B` 增益、回收能量幅值 | 变流器硬件资料 |
| A9 | 变流器效率 0.97、额定 14.4 MW（单机持续功率 × 台数）、输出电流上限 3000 A | 损耗与容量约束 | 器件资料 |
| A10 | 储能 145 kWh、往返效率 0.90、充电 2 MW | SOC 与功率上限 | 储能系统资料 |
| A11 | SOC 边界 0.10/0.90、初值 0.50 | 可用能量窗口 | BMS 定值 |
| A12 | 储能开路电压 1100 V、内阻 0.02 Ω | 参考电压幅值（结构稳健、幅值敏感） | 储能电气资料 |
| A13 | EKF/UKF 量测噪声 `σ_v = σ_i = 5` | 权重收敛速度 | 传感器精度资料 |
| A14 | 模式切换六类阈值为标定值 | 切换频次 | 工况标定记录 |
| A15 | RHONN 状态/控制归一化尺度 `(1400, 1500)`、`(1, 1)` | 基函数分辨力 | 工况范围标定记录 |
| A16 | 观测故障注入参数（噪声、偏置、延迟、丢样）按第 8 章用例定义 | 鲁棒性结论 | 现场故障统计 |
| A17 | 线路坡度/曲线/限速由线路数据包经只读接口装载 | 真实线路场景 | 线路基础数据包 |
| A18 | 储能开路电压按定值处理，不含 SOC-OCV 非线性 | 储能电压精度 | SOC-OCV 特性曲线 |

### 9.3 可配置项清单

| 编号 | 配置项 | 默认值 | 允许范围 | 变更影响 |
| --- | --- | --- | --- | --- |
| C1 | 积分步长 `h` | `1e-4 s` | `[2.5e-5, 4e-4]` | 精度、耗时、闭合残差 |
| C2 | 控制周期 `Ts` | `1e-4 s` | `h` 的正整数倍 | 控制频率、`B` 先验 |
| C3 | 记录抽样 `record_stride` | 10 | `≥1` | 输出体积 |
| C4 | `apply_u0_limit` | `true` | `true/false` | 占空比上限 0.9 |
| C5 | 控制器 profile | `default` | `default/balanced/robust` | 滤波步长、Schur 值、平滑 |
| C6 | 参考策略 | `storage_matched` | 三种（另两种为研究用） | `v_ref` 幅值与噪声敏感性 |
| C7 | 保护内阻上界倍率 | `2.5` | `≥1` | 反馈参考上限 |
| C8 | EKF/UKF 训练步长 `η` | `0.01` | `(0, 0.1]` | 收敛速度与稳定性 |
| C9 | `Q` / `P_0` | `1e-8` / `1.0` | 正数 | 权重漂移与收敛 |
| C10 | 量测噪声 `σ_v` / `σ_i` | `5 V` / `5 A` | 正数 | 增益与创新尺度 |
| C11 | UKF 采样权重 | `0.02` | `(0, 1/(2L))` | sigma 点分布 |
| C12 | NSMC `u0` | `0.9` | `(0, 1]` | 控制权限与安全 |
| C13 | Schur 特征值 | `0.7` | `[0.6, 0.8]` | 稳定项强度 |
| C14 | 状态标幺基准 | `(1100, 3000)` | 正数对 | `u_n` 量级 |
| C15 | 平滑系数 `command_smoothing_alpha` | `1.0`（robust 为 0.5） | `(0, 1]` | 抖振与跟踪 |
| C16 | 模式窗口 `metric_window` | `20` | `≥1` | 切换灵敏度 |
| C17 | 最小驻留 `min_dwell_steps` | `50`（balanced/robust 60） | `≥1` | 切换频次 |
| C18 | 闭合容差 | `1e-4` | 固定 | 合格判定 |
| C19 | 峰值电压门禁 | `1500 V` | 固定 | 物理合规 |
| C20 | 性能损失门限 | `0.01%` | 固定 | 资格判定 |

### 9.4 参数取值变更后的必做动作

1. 同步更新对应 JSON 的 `data_status`、`field_data_status` 与 `provenance`，不得只改数值不改等级；
2. 重跑 `tools/check_data_manifest.py --strict`，确认溯源登记与参数文件一致；
3. 重跑第 8 章全部用例与完整验证矩阵，重新裁定资格；
4. 若变更的是电感、电容、储能额定电压或内阻，必须重跑增益先验缩放律与参考量敏感性探针；
5. 在报告"其他需要说明的情况"中写明：变更了哪些字段、变更前后结论的一致性、以及因此失效的结论。

### 9.5 模型升级路径（数据到位后的三类改动）

算法的结构层与数值层分离：**控制链、参考量构造、控制律、台账与门禁属于结构层，不随参数变化**；
只有下列三类改动会在参数更新时发生。三类改动的工作量与风险等级不同，不得混为一谈。

**第一类：只换数值（结构不动）**

| 对象 | 可替换字段 | 改动方式 | 直接受影响 |
| --- | --- | --- | --- |
| 列车 | 质量、最大制动力、再生比例上限、基本阻力三系数、曲线等效系数、黏着 | 改 JSON | 全部能量幅值、可达减速度 |
| 电机 | 最大再生功率/力、最低再生速度、效率四参数、降额两拐点 | 改 JSON | 轮端再生功率、电功率 |
| 变流器 | `L`、`C_in`、`C_out`、`R_L`、`f_sw`、`η_conv`、额定与电流上限 | 改 JSON | 动态时间常数、`B` 增益、峰值电压电流 |
| 储能 | 容量、往返效率、充/放电功率、SOC 边界与初值、`V_oc`、`R_int` | 改 JSON | SOC 轨迹、端口电压、参考量幅值 |

改完仅需按 9.4 重跑用例；控制律、`x_ref` 构造式、NSMC 三条纪律均不需改动。

**第二类：换模型实现，接口不变**

| 模型 | 定型形式 | 数据到位后的形式 | 必须保持的接口 |
| --- | --- | --- | --- |
| 电机效率 | 解析式 `η(load_ratio, v)` | 效率云图二维插值 `η(T, ω)` | `efficiency(load_ratio, speed_mps) -> float`，调用侧不变 |
| 变流器效率 | 定值 `η_conv` | 效率-功率曲线 | 仍以「输入侧等效电流损失」实现，保证 KCL 与能量守恒 |
| 电机包络 | 恒转矩/恒功率解析式 | 特性曲线线性插值 | `F_regen_max(v)` 签名不变 |

第二类改动后，能量幅值与 `B` 先验都会变，必须重跑 8.5 的回归读数与增益先验缩放律（T23）。

**第三类：需扩展接口（代码改造 + 重新标定）**

| 项 | 原因 | 需同步修改 |
| --- | --- | --- |
| `V_oc` 改为 `V_oc(SOC)` | 5.5 的 `v_ref` 由二次方程解析求解；若 `V_oc` 随 SOC 变化，方程变为非线性，须迭代或分段求解 | `terminal_voltage_v` 增加 SOC 入参；`v_ref` 求解器；A18 闭环 |
| 引入效率云图后的功率-效率耦合 | `P_conv` 依赖效率、效率依赖功率，形成隐式方程 | 一次不动点迭代（两轮即收敛到 `1e-4`）或显式给出定值假设 |
| 变流器损耗改为开关级模型 | 平均模型不含开关纹波与器件损耗 | 超出本方案范围（1.3），不得在应用层私自替换 |

第三类的共同要求：**接口扩展必须在装配层显式声明，不得在控制律内部按工况分叉**；扩展后 `x_ref` 幅值敏感性探针与 `v_ref` 策略比较必须重跑，因为参考量的物理来源变了。

---

## 附录 A 与方案原文的公式映射

| 方案原文 | 本方案位置 | 落地说明 |
| --- | --- | --- |
| §4.2.1.3（1）RHONN 状态方程 | 5.6 | 两项加权和、串联-并联双路径；基函数用 `tanh` 并先归一化 |
| §4.2.1.3（2）滑模面 `s = x − x_ref` | 5.10.1 | `λ_k` 乘入滑模面；`k` 为采样步序号 |
| §4.2.1.3（2）控制律 (34)(35) | 5.10.4、5.10.5 | 分支条件与缩放方向统一取 `u_eq + u_n`；可达性用盒判据 |
| §4.2.1.3（2）`u_eq`（原文缺定义式） | 5.10.3 | 由 `s_{k+1}=0` 解出 `u_eq = B⁺(x_ref − g(·,0))` |
| §4.2.1.3（2）`x_ref` "由制动曲线与 SOC 共同确定"（原文无公式） | 5.5 | 四项取小 + 储能吸收匹配电压 + buck 稳态电流 |
| §4.2.1.3（3）EKF 权重更新 | 5.7 | 保留 `η = 0.01`；协方差用与 `η` 自洽的 Joseph 形式 |
| §4.2.1.3（3）UKF 式 (36)(37) | 5.8 | 补全 `P^yy`、`η_j^m`、权重更新式；`L = n_w = 20` |
| 方案 `u0 = 0.9` | 5.10.5、3.2 I3 | 逐通道上限，可行域为盒 |

## 附录 B 术语

| 术语 | 含义 |
| --- | --- |
| 平均模型 | 用占空比平均值代替开关过程，不含开关纹波与器件损耗 |
| 净存入 | 储能内部能量变化，已含储能损耗 |
| 端口吸收 | 储能端子实际接受的电能，未扣储能损耗 |
| 回网 / 回吸 | 经直流母线送回 / 取自牵引网的能量 |
| 硬门禁 | 物理、闭合、辨识健康、SOC 退出四项，失败即不可用 |
| 性能门禁 | 与对照装配逐条比较能量与抖振，出现反例即不授予资格 |
| 参数溯源等级 | `official / real / derived / assumed` 四级标注 |

## 附录 C 引用与复现

| 内容 | 位置 |
| --- | --- |
| 算法公式与接口契约 | `docs/regenerative_braking_algorithm.md` |
| 方案条款与代码映射 | `docs/technical_scheme_code_mapping.md` |
| 输入输出单位与含义 | `docs/project_status_for_teacher_2026-10-17.md` |
| 收尾验收与裁定 | `docs/final_acceptance_2026-10-14.md` |
| 数据共享边界 | `docs/data_sharing_boundary.md` |
| 参数文件 | `data/single_train/*.json` |
| 验证矩阵入口 | `tools/run_validation_suite.py` |
| 全量回归 | `python -m pytest tests -q` |

---

**本方案为唯一技术依据。任何与本方案不一致的实现，必须先修改本方案并说明理由，不得在代码中静默偏离。**
