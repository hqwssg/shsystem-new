# 数据共享边界（data_sharing_boundary）

> **本项目**：`single_train_energy_optimization`（单列车节能与再生制动）
> **关联项目**：`heavy_empty_train_coordination`（重空协同调度）
> **物理关系**：两者在**同一个 Git 仓库**（`D:/dev/project`）内，是两个平级子目录
> **本文档版本**：<span style="color:#c00000">v1.1</span> ｜ **生成日期**：2026-09-24 ｜ **修订日期**：2026-09-25
>
> <span style="color:#c00000">**v1.1 修订**：问题 21 落地后，`storage_parameters.json` 的
> `nominal_voltage_v` 与 `internal_resistance_ohm` 从「被控对象参数」升级为
> **闭环控制律的直接输入**（参考电压 `v_ref` 由储能二参数 I-V 关系解析给出），
> 故 `missing` 清单第 6 条 `storage_electrical` 的优先级提升，见 §6。
> 共享边界本身**不变**：这两个参数仍是本项目专用数据，不进入共享目录。</span>

---

## 1. 边界原则（一句话）

**共享「基础事实数据」，不共享「算法内部状态」。**

展开为四条硬约束：

| # | 约束 | 落地机制 |
| --- | --- | --- |
| 1 | 共享数据**不复制多份** | `configs/data_paths.yaml` 的 `shared_data_root` 指向重空项目目录，**只读引用** |
| 2 | 本项目对共享数据**只读** | `shared_data_read_only: true` + `io/data_paths.py::ensure_read_only` 写入保护 |
| 3 | 算法内部状态**一律留在本项目** | 全部落在 `single_train_data_root` / `experiments_root` 下 |
| 4 | **不修改**重空协同项目的核心逻辑 | 本项目不写入重空项目任何文件；本仓库的提交只增不改其代码 |

判定口径（用于回答"某个字段能不能共享"）：

> 这个字段是不是**线路/列车/供电客观事实**？
> 是 → 共享（只读引用）。
> 不是（是某次仿真/某套算法跑出来的状态或参数）→ **不共享**，留在本项目。

---

## 2. 共享基础事实数据清单（只读引用）

数据根目录（`configs/data_paths.yaml`）：

```
shared_data_root: "../heavy_empty_train_coordination/data/real_shuohuang"
```

该目录由 `heavy_empty_train_coordination/tools/build_real_shuohuang_dataset.py` 生成，
其数据状态的**权威来源**是 `heavy_empty_train_coordination/data/real_shuohuang/DATASET_README.md`
（`configs/data_paths.yaml` 的 `shared_data_status_authority` 字段显式登记了这一点——本项目只引用，不维护）。

### 2.1 本项目**实际读取**的文件（必需文件，缺失即报错）

| 文件 | 状态 | 本项目用途 | 读取代码 |
| --- | --- | --- | --- |
| `stations.csv` | real | 定位制动区段起讫（33 行，终点黄骅港 K583+003） | `data_loader.load_shared_railway_data` |
| `segments.csv` | derived | 按里程查询坡度/曲线/限速（1390 行），构造制动工况输入 | 同上 + `segment_at()` |
| `gradients.csv` | real | 长大下坡区段识别（再生潜力区，728 行） | `find_long_downhill_ranges()` |
| `curves.csv` | real | 曲线附加阻力按 600/R 折算等效坡度（331 行） | 间接（已合成进 `segments.csv`） |
| `trains.csv` | mixed | **仅取列车质量**（`mass_tons`，real）；见 §4 | `SharedTrainRecord` |
| `power_arm_intervals.csv` | derived | 仅作**接入边界**意义使用（76 行） | 登记，阶段 1 未参与控制 |
| `route_metadata.json` | real | 线路总长 583.003 km、最高速度 120 km/h | `total_length_km()` |
| `operating_conditions.json` | real | 黏着系数 0.28、制动黏着安全系数 0.65 | `SharedAdhesion` |
| `battery.json` | real | 储能容量 145 kWh、往返效率 0.9、最大充电功率 2000 kW | `SharedStorageRecord` |

区段查询口径：`segments.csv` 按**左闭右开**区间解释，线路终点归末段；真实线路剖面起止里程必须落在共享线路范围内，缺少区段时直接报错，不用零坡度或空曲线静默补值。

`configs/data_paths.yaml::shared_data_required_files` 列出的 7 个文件是**硬前置**：
`require_shared_data()` 在缺失时直接抛 `DataPathError`，**不静默降级、不用假数据顶替**。

### 2.2 已登记但本项目**不使用**的文件（登记以明确边界）

| 文件 | 状态 | 为什么不使用 |
| --- | --- | --- |
| `headway_constraints.csv` | real | 属于**重空调度约束**，与单列车控制无关 |
| `technical_operation_times.csv` | real | 站场作业时分，属**调度层** |
| `train_formation_modes_2025.csv` | real | 仅用于校验列车质量区间 |
| `energy_transfer_zones.csv` | real | 柔性供电协同区间，属**规划层**；阶段 1 不参与控制，仅登记 |
| `smart_meter_*.csv` / `energy_calibration_factors.json` | real | 累计电量口径，**无法支撑高频辨识与控制验证**（见 §6 数据缺口） |

---

## 3. 本项目专用数据（**不共享**，反向也如此）

以下数据属于**单列车控制内部状态**，一律不进入共享目录，重空协同项目也不应读取：

| 类别 | 文件 / 位置 | 状态 |
| --- | --- | --- |
| 高频动态状态 | `data/experiments/<run_id>/timeseries_*.csv` | 仿真产物（已 gitignore） |
| 电力电子参数 | `data/single_train/dc_dc_parameters.json` | placeholder（除 `duty_limit` 为 official） |
| 储能详细参数 | `data/single_train/storage_parameters.json` | derived / assumed / placeholder |
| 电机与列车参数 | `data/single_train/motor_parameters.json`、`train_parameters.json` | placeholder / derived |
| RHONN 参数 | `data/single_train/rhonn_parameters.json`（待建） | 阶段 3 建立 |
| EKF/UKF 协方差与权重 | 运行期 + 实验产物 | 阶段 4/5 建立 |
| NSMC 参数与 PWM 指令 | 运行期 + 实验产物 | 阶段 7 建立 |
| 高频制动控制记录 | `data/experiments/<run_id>/` | 仿真产物 |
| 数据清单 | `data/data_manifest.yaml` | 本项目维护 |

**为什么这些不共享**：它们是"某套算法在某次仿真中的内部量"，不是线路/列车的客观事实。
把它们共享出去，等于让重空调度去依赖一套尚未定型、参数还是 placeholder 的控制内部量——
既污染对方的输入语义，也会让本项目每次改算法都要去协调对方。

---

## 4. 跨项目待确认项（重要）

### 4.1 `trains.csv` 的 Davis 系数基准（**已查明**，仍不复用）

`trains.csv` 自述（`data_manifest.yaml` 中 `trains` 条目的 notes）：

> davis 系数与其代码实现的速度基准（m/s、绝对 kN）不匹配、未按 N/kN 标定，
> 本项目不复用该组系数，改用 `data/single_train/train_parameters.json` 中独立标定的 assumed 值。

**2026-09-25 更新：基准已查明**。证据不是猜测，而是直接读重空协同项目的消费代码
`heavy_empty_train_coordination/train_simulator.py::calculate_forces()`：

```python
rb_kN = (
    (train.davis.a + train.davis.b * current_v_mps) * rolling_multiplier
    + train.davis.c * current_v_mps**2 * aerodynamic_multiplier
)
return rb_kN + rc_kN, rg_kN, average_gradient
```

两个环境乘子由 `operating_conditions.resistance_multipliers_at()` 给出，**默认 1.0**（无量纲天气因子）。

#### 两套口径对照

| 项 | 共享 `trains.csv`（重空协同项目消费口径） | 本项目 |
| --- | --- | --- |
| 力的单位 | **绝对 kN** | 比阻力 N/kN → 绝对 N |
| 速度单位 | **m/s** | km/h |
| 公式 | `rb_kN = (a + b·v_mps)·k_roll + c·v_mps²·k_aero` | `w0 = a + b·v_kmh + c·v_kmh²`；`F0 = w0/1000 · m · g` |
| 质量项 | **无**（公式里不出现质量） | **显式**（`× m · g`） |
| 二次项 | 作用在 `v²` | 作用在 `v_kmh²` |
| Heavy 系数 | `a=8.0, b=0.10, c=0.0028` | `a=0.92, b=0.0048, c=0.000125` |

#### 量级差异（实测，不是估计）

| 速度 | 本项目口径（`F0`，Heavy 2.16e7 kg） | 重空口径（`rb`，乘子=1.0） | 比值 |
| --- | --- | --- | --- |
| 20 km/h | 225.881 kN | 8.642 kN | 26.1× |
| **72 km/h** | **405.484 kN** | **11.120 kN** | **36.5×** |
| 120 km/h | 698.409 kN | 14.444 kN | 48.4× |

差异不是"标定偏差"级别（那通常是 ±10%），而是**几十倍**，且随速度单调扩大——
这正是"重空公式缺少质量项 / 系数并非比阻力口径"的典型特征。
因此**不能**用任何单一比例因子把两者对齐；必须由对方确认口径后才能考虑复用。

#### 本项目处理

| 项 | 共享 `trains.csv` | 本项目 |
| --- | --- | --- |
| 质量 | `Heavy.mass_tons = 21600 t`（real，来自 PDF 编组资料） | **复用** → `train_parameters.json.mass_kg = 2.16e7` |
| 基本阻力系数 | `davis_a/b/c`（基准已查明，见上表） | **不复用**；改用 `basis="per_kN_speed_kmh"` 形式，`a=0.92, b=0.0048, c=0.000125`，标 `assumed` |
| 最大制动力 | `Heavy.max_brake_kN = 6200 kN`（文件自述为工程虚拟预设） | **沿用数值**，但标 `assumed` |
| 最大功率 | `Heavy.max_power_kW = 28800 kW`（工程虚拟预设） | 沿用量级，标 `assumed` |

代码层面对该差异做了**显式防护**：`BasicResistanceModel.__post_init__` 在 `basis != "per_kN_speed_kmh"` 时直接抛
`TrainModelError`，并提示「共享 trains.csv 的 Davis 系数基准与之不同，需先确认后再接入」。
对应测试：`tests/test_train_braking_model.py::test_rejects_incompatible_resistance_basis`。

#### 待重空协同项目书面确认的三个问题

1. `davis_a/b/c` 的**定义口径**是什么？是"绝对 kN 系数"（即整车在给定速度下的基本阻力直接等于 `a + b·v + c·v²`），
   还是"单位质量/单位编组的比阻力"？——若是后者，公式里缺一个质量（或 1000 t）因子。
2. 速度单位确认为 **m/s**（而非 km/h）吗？代码里用的是 `current_v_mps`，但需要确认这是有意为之而非沿用旧口径。
3. Heavy 在 72 km/h 下的基本阻力**预期量级**是多少？本项目口径给出约 **405 kN**，
   重空口径给出约 **11 kN**。哪一个符合朔黄 2 万吨编组的实际经验值？

**在此之前不复用**；本项目继续使用 `data/single_train/train_parameters.json` 中独立标定的 assumed 值，
并保持 `basis` 校验作为硬防护。

### 4.2 `battery.json` 的 `max_discharge_power_kW = 0.0`

`battery.json` 原文标注为 `missing_conservative_zero`（缺失，保守取零）。
本项目**不把它当真实值**，而是：

- `storage_parameters.json.max_discharge_power_w` 采用**规划假设值** `2.0e6 W`，标 `assumed`；
- 字段级来源写明「规划值 `planning_max_discharge_power_assumption_kW = 2000.0`，本文件采用规划值并标注 assumed」；
- 阶段 1 的 `StorageBusRequest.allow_discharge = False`，**放电通道预留但未启用**，因此该假设值不影响当前结果。

### 4.3 `power_arm_intervals.csv` 的电气上限

`max_traction_supply_kw` / `max_regen_absorption_kw` / `max_grid_feedback_kw` 在共享数据中标注为
`default_large_non_binding_until_official_limits`（未获得供电臂电气能力资料前的大值默认）。
本项目**只在"接入边界"意义上使用**，不把它当作已确认的电气能力上限。

---

## 5. 数据格式与读取契约

| 项 | 约定 |
| --- | --- |
| 路径声明 | 全部集中在 `configs/data_paths.yaml`；**代码中不硬编码任何绝对路径** |
| 相对路径基准 | 相对**本项目根目录**（`configs/` 的上一级），由 `data_paths.project_root()` 解析 |
| 环境变量覆盖 | 优先级高于配置文件：`SINGLE_TRAIN_SHARED_DATA_ROOT`、`SINGLE_TRAIN_DATA_ROOT`、`SINGLE_TRAIN_EXPERIMENTS_ROOT` |
| 单位 | 全项目 SI：m / s / kg / N / W / J / V / A；坡度用 ‰；曲线半径用 m；速度内部用 m/s |
| CSV 编码 | 共享 CSV 用 `utf-8-sig` 读取（兼容 BOM），写出一律 `utf-8` |
| JSON | 本项目参数文件为 UTF-8 JSON object，含 `data_status` 与 `field_data_status` |
| 缺字段 | 抛 `DataLoadError`（`ParameterFile.require`），**不猜、不补、不伪造** |
| 单位换算 | 只在 IO 边界做（如 `capacity_kwh → capacity_j`），模型内部不再换算 |

---

## 6. 数据状态管理（`data/data_manifest.yaml`）

状态取值集合（严格，不猜）：

| 状态 | 含义 |
| --- | --- |
| `official` | 正式文件 / 合同口径提供 |
| `real` | 真实测量或真实资料整理 |
| `derived` | 由 real / official 数据按明确规则推导 |
| `assumed` | 工程假设（有依据但非实测） |
| `synthetic` | 虚拟生成数据 |
| `placeholder` | 纯占位，仅用于打通接口 |
| `unknown` | **来源不明确 —— 不得猜，保留 unknown** |

当前清单：`shared` 13 项、`single_train` 4 项、`missing` 7 项。
7 个 `unknown` 条目（全部是**真实数据缺口**，不是"忘了填"）：

1. `traction_curve` —— 机车牵引特性曲线（缺失，现用恒转矩-恒功率包络近似，标 assumed）
2. `braking_curve` —— 电制动/再生制动特性曲线（缺失，现用对称占位包络）
3. `motor_efficiency_map` —— 电机效率云图（缺失，现用可解释解析近似）
4. `high_frequency_voltage_current` —— **直流母线电压/电流、储能端电流高频实测记录（完全缺失）**
5. `converter_hardware` —— 变流器硬件资料（器件、电感、电容、开关频率）
6. `storage_electrical` —— 储能系统电气资料（额定电压、内阻、最大放电功率、SOC 区间）
   <span style="color:#c00000">**【2026-09-25 优先级提升】** 其中 `nominal_voltage_v` 与 `internal_resistance_ohm`
   此前只作为被控对象参数出现，现在**同时是闭环控制律的直接输入**：问题 21 裁定参考电压
   `v_ref = clip((V_oc + √(V_oc² + 4·P_abs·R_int))/2, V_out,min, V_out,max)`，
   由储能二参数 I-V 关系 `i_sink = (v_out − V_oc)/R_int` 与稳态功率平衡解析解出。
   实测（`tools/probe_reference_voltage_placeholder_sensitivity.py`，7 变体 × 2 场景）：
   **结构稳健**（`d2` 中位数 ≤ 0.112、`v_out` 峰值 ≤ 1240.5 V，闭环始终留在物理包络内），
   但**幅值敏感**（`max_charge_power_w × 2.0` → 回收能量 `+72.06%`）。
   故这两个 placeholder 升级为实测值后，**回收能量的具体数字会漂移**，
   在硬件资料到位前不可作工程结论。该依赖已登记在 `storage_parameters.json` 的
   `reference_voltage_dependency` 与 `data_manifest.yaml` 的 `storage_parameters` / `storage_electrical` 条目中。</span>
7. `rhonn_ekf_ukf_nsmc_parameters` —— 阶段 3–7 才建立，**刻意不提前固化**

**第 4 条是本项目最关键的缺口**：现有智能电表数据（`shuohuang_data/260704-列车智能电表数据` 等）为
**累计电量口径**，无法支撑 RHONN/NSMC 的高频辨识与控制验证。因此本项目**全部高频仿真结果**
一律标注 `simulation result / not engineering conclusion`（`run_project.py::RESULT_DISCLAIMER`，
写入每次运行的 `summary.json`、`summary.csv`、`README.md`）。

校验方式：

```bash
python tools/check_data_manifest.py          # 常规校验（unknown 允许，但必须写明原因）
python tools/check_data_manifest.py --strict # 把 unknown 判为失败
```

校验内容：必需字段齐全、`status` 取值合法、`unknown` 必须写明原因、
`shared` 条目在 `shared_data_root` 下**真实存在**、`single_train` 条目存在、
`missing` 条目允许不存在但须写明 `source` / `notes`。**只读，不写任何文件。**

---

## 7. 写入保护机制

| 层 | 机制 | 代码 |
| --- | --- | --- |
| 配置 | `shared_data_read_only: true` | `configs/data_paths.yaml` |
| 运行时 | `ensure_read_only(paths, target)` 检查输出路径是否落在共享根目录内，是则抛 `DataPathError` | `io/data_paths.py` |
| 落盘前 | `run_project.py` 在 `mkdir` **之前**调用 `ensure_read_only` | `run_project.py::main` |
| 测试 | `test_read_only_guard_blocks_writes_into_shared_root` | `tests/test_data_layer.py` |
| 版本管理 | `data/experiments/` 加入 `.gitignore`，仿真产物不入库 | `.gitignore` |

---

## 8. 所有权与版本管理

| 数据 | 所有者 | 版本标记 | 本项目权限 |
| --- | --- | --- | --- |
| `heavy_empty_train_coordination/data/real_shuohuang/*` | 重空协同项目 | `real_shuohuang@YYYY-MM-DD`（记在 manifest 的 `version` 字段） | **只读** |
| `data/single_train/*.json` | 本项目 | `v1.0` | 读写 |
| `data/data_manifest.yaml` | 本项目 | `schema_version: 1.0` | 读写 |
| `data/experiments/*` | 本项目 | 目录名即时间戳 `YYYYmmdd_HHMMSS` | 读写（不入库） |
| `configs/data_paths.yaml` | 本项目 | `schema_version: 1.0` | 读写 |

**Git 边界**：两个项目在同一仓库。本项目**不修改**重空协同项目的任何文件；
本项目在分支 `feature/regenerative-braking-rhonn-nsmc` 上提交，不 force push、不重写历史。

---

## 9. 与重空协同项目的接口（阶段 11，已实现）

方向只允许走"基础事实数据 + 汇总结果"，不允许走控制内部状态：

| 方向 | 允许的内容 | 落点 | 状态 |
| --- | --- | --- | --- |
| 重空 → 本项目 | 线路几何、站表、坡度、曲线、限速、列车质量、黏着、供电臂边界、储能容量口径 | `shared_data_root` | 已就绪（只读引用） |
| 本项目 → 重空 | 单列车**按时间桶汇总**的可回收能量（不导出高频状态、不导出 RHONN 权重与协方差） | `data/experiments/<run>/cross_project/energy_buckets.{csv,json}` | **已实现**（阶段 11） |
| 双向 | **数据状态标记本身**（real / assumed / placeholder / unknown）必须原样传递 | `data_manifest.yaml`；导出的 `parameter_data_status` 字段 | 已实现 |

**明确不做**：不把重空协同的 NSGA-II 调度算法引入本项目；不把本项目的 NSMC 控制器引入调度层。
两者是**同一线路上的两个不同问题**，共享数据但算法独立。

### 9.1 实现与三道闸

| 项 | 位置 |
| --- | --- |
| 导出模块 | `regenerative_braking/io/cross_project_export.py` |
| 命令行入口 | `tools/export_cross_project.py` |
| 测试 | `tests/test_cross_project_export.py`（42 条） |
| 白名单 | `SHARED_FACT_COLUMNS`（23 列，`FIELD_WHITELIST_VERSION = "1.0"`） |
| 键名哨兵 | `FORBIDDEN_INTERNAL_TOKENS`（20 条片段） |
| 路径越界检查 | `assert_export_target_allowed()` / `coordination_project_roots()` |

导出纪律由**三道闸**强制，不靠自觉：

1. **字段白名单（allow-list）**——导出行的键必须**全部**落在 `SHARED_FACT_COLUMNS` 内。
   多一个键就报错，**不静默丢弃**：静默丢弃会让"忘了导"与"故意不导"无法区分，
   而这两件事的审计含义完全不同。
2. **元数据键名哨兵**——payload 的键名（递归）命中 `FORBIDDEN_INTERNAL_TOKENS` 即报错。
   哨兵**只扫键名、不扫值**，这是刻意的：要防的是"把内部状态当成一个字段导出去"，
   而不是"提到过算法名字"；若改成扫值，`source_*` 这类溯源字段会把整条导出链误伤。
   为让这条规则真正闭环，payload 内**不设自由文本字段**（没有 notes）。
3. **路径越界检查**——目标落在共享数据根、或落在重空协同项目目录内一律报错。
   这一步**不依赖** `shared_data_read_only` 开关：§1 第 4 条是硬约束，
   不能被一个配置项关掉。检查顺序刻意是「先校验 payload → 再校验路径 → 最后才 mkdir」，
   任何一步不过都不留半个目录。

### 9.2 导出列清单（白名单，v1.0）

| 类别 | 列 |
| --- | --- |
| 时间桶骨架 | `bucket_index`、`t_start_s`、`t_end_s`、`covered_duration_s`、`sample_count`、`is_partial` |
| 运动与线路客观事实 | `distance_m`、`speed_mean/min/max_m_per_s`、`gradient_per_mille`、`curve_radius_m`、`speed_limit_kmh` |
| 储能客观状态 | `soc_start`、`soc_end`、`soc_min`、`soc_max` |
| 能量桶 | `mechanical_braking_energy_kWh`、`available_regenerative_energy_kWh`、`captured_energy_kWh`、`curtailed_energy_kWh`、`grid_export_energy_kWh`、`grid_import_energy_kWh` |

**明确不在列内**：`duty_cycle_T1/T2`、母线/电感电压电流、`grid_source_loss_w`、
`regen_limit_reason`、模式切换次数与原因、RHONN 权重、EKF/UKF 协方差、滑模面、跟踪误差。

### 9.3 口径与限制（必须随文件一起传递）

| 项 | 约定 |
| --- | --- |
| 归桶规则 | 样本按 `floor(t / bucket_seconds)` 归桶；末桶不满时保留并标 `is_partial=True` |
| 能量聚合 | **矩形法（左端点）**，与 `metrics.EnergyLedger` 同口径 |
| 抽样前提 | 导出基于**抽样记录**（每 `record_stride` 步一条），不是逐步累加 |
| 抽样间隔 | 写进元数据 `sample_interval_s`，供消费方判断粒度 |
| 缺资料 | 客观事实列整桶缺失时输出 `None`（CSV 空单元格 / JSON `null`），**不伪装成 0** |
| 闭合校验 | 桶合计与全步台账存在抽样差异，**不得用于闭合校验**；闭合校验用 `EnergyLedger` |
| 非有限值 | 积分列出现 `NaN` 直接报错（静默按 0 会污染能量桶） |
| 编码 | 写出一律 `utf-8`（无 BOM），与本文件 §5 的读取约定配套 |

实测校验（`scenario_1_flat_braking`，dt=2e-4，record_stride=50，桶宽 1 s）：
桶合计机械制动能量 810.5382 kWh vs 全步台账 810.4683 kWh，相对差 **8.6e-5**——
方向与量级都符合"左端点矩形法对单调下降功率的轻微高估"，可放心用于**跨项目汇总**，
但不能替代台账做闭合校验。
