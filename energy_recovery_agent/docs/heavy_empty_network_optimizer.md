# 重空列协同优化输入模板与双层时空网络原型

本模块用于贴近技术方案第四章中“基于时空网络的重列、空列、重空协同能耗监测系统优化研究”的算法原型。

## 文件

- `data_templates/heavy_empty_od_template.xlsx`：重空列协同优化输入模板。
- `heavy_empty_network_optimizer.py`：双层时空网络 AGA/Pareto 优化原型。
- `tests/smoke/verify_heavy_empty_network_optimizer.py`：示例验证脚本。
- `outputs/heavy_empty_network_optimizer/`：验证输出目录。

## 模板工作表

- `od_demands`：重列 OD 需求、发车窗口、到达期限、货物吨数和优先级。
- `service_types`：重列、空列服务参数，包括速度、走行成本和基础能耗系数。
- `operation_nodes`：装车、卸车、组合、拆解等作业节点和能力。
- `virtual_trainset`：虚拟车底库和惩罚成本。
- `scenarios`：能力富余、能力紧张等目标场景。

## 真实基础设施接入

当前原型已把以下真实数据接入运行弧属性和运行弧权重：

- 坡度：读取 `data/source/geometry/gradients.xlsx` 的 `坡度表`，字段为 `source_image`、`start_km`、`end_km`、`length(m)`、`坡度(千分率)`。
- 平曲线：读取 `data/source/geometry/curves.xlsx` 的 `线路曲线表(2)`，字段包括曲线起始位置、曲线结束位置、半径、曲线长度和方向。
- 供电臂：优先读取 `data/source/power_arm/power_arm_continuous_intervals.xlsx` 的连续供电臂区间，使用 `section_id`、`direction`、`start_km`、`end_km`、`needs_manual_review` 等字段；若该表不存在，则回退读取 `data/source/power_arm/power_arm_boundaries.xlsx`。

## 2025 编组模式接入

当前使用 `data/real_shuohuang/train_formation_modes_2025.csv` 作为可选编组参数表。`service_types` 工作表可以填写以下可选字段：

- `formation_category`：`two_10000_ton`、`unit_10000_ton`、`combined_10000_ton`、`ordinary`。
- `load_state`：`heavy` 或 `empty`。
- `formation_mode`：`1+1`、`2+0`、`单牵` 等。
- `wagon_count`：辆数。
- `mass_tons`：若手动填写，则优先使用该值。
- `mass_energy_reference_tons`：基础 `energy_kwh_per_km` 对应的参考总重量。
- `mass_energy_exponent`：按重量修正基础能耗的指数，默认按 1.0 线性修正。

接入规则：

- 原文件中的“载重”暂按编组总重量 `mass_tons` 使用。
- 如果 `service_types.mass_tons` 为空，且编组字段能唯一匹配 `train_formation_modes_2025.csv`，则使用编组表中的 `mass_tons`。
- 如果填写了 `mass_energy_reference_tons`，则基础单位里程能耗按 `mass_tons / mass_energy_reference_tons` 修正。
- `1+1`、`2+0`、`单牵` 当前只作为编组标签，不解释机车数量、位置和车型；这些含义仍需甲方确认。

运行弧输出字段包括：

- `parent_arc_id`：切分前的父运行弧编号。
- `segment_index`、`segment_count`：父运行弧内的子弧序号和总子弧数。
- `power_arm_split`：是否由供电臂边界自动切分产生。
- `base_energy_kwh`：按列车类型基础能耗系数和距离得到的基础能耗。
- `regen_energy_kwh`：运行弧构造时显式保存的再生制动电量。
- `traction_energy_kwh`：结算牵引侧电量，满足 `energy_kwh = traction_energy_kwh - regen_energy_kwh`。
- `energy_adjustment_kwh`：坡度和曲线启发式修正后相对基础能耗的变化量。
- `avg_gradient_promille`：弧段覆盖坡段的加权平均坡度，反向运行时符号反转。
- `curve_equivalent`：可定位曲线的等效曲线阻力指标。
- `power_arm_ids`：弧段覆盖的供电臂记录编号。
- `power_arm_review_required`：覆盖供电臂中是否存在需要人工复核的记录。

能耗修正目前仍是原型启发式：

```text
energy_multiplier = 1.0 + 0.12 * avg_gradient_promille + 0.001 * curve_equivalent
```

该公式用于先把真实坡度、曲线条件进入弧权重，不等同于最终牵引计算或 Davis 阻力精算模型。

## 时间片与供电臂能量结算

当前已新增“运行弧按时间片展开 + 分供电臂能量结算原型”：

- 对最优候选方案中的运行弧，先按供电臂连续区间边界切分，再按场景 `energy_settlement_step_s` 展开为能量时间窗（默认 10 秒）。`time_slice_s` 仅用于作业和区间容量时隙，两者不再混用。
- 每条时间片记录输出到 `energy_time_slices.csv`，包括供电臂、列车、运行弧、时间窗、牵引电量、再生电量和净电量。
- 同一供电臂、同一时间窗内聚合到 `power_arm_energy_settlement.csv`。
- 如果运行弧同时覆盖多个供电臂，系统会使用复合供电臂 ID；复合 ID 对应的电气/储能限额必须一致。若限额冲突，输入会被拒绝，避免因供电臂 ID 顺序不同而得到不同的节能量或约束结果。并联供电臂的容量叠加规则需在正式电气模型中明确后再接入。
- 复合 ID 在结算分组前会按成员排序规范化，因此 `A;B` 与 `B;A` 表示同一个物理重叠区，不会重复获得供电容量或直接利用机会；复合 ID 中存在未配置成员时同样会拒绝结算。
- 当前朔黄口径为上下行供电相互隔离，不能直发直用；重空列网络原型中的 `direct_used_kwh` 固定为 0，结算模式输出为 `storage_absorption_no_direct_use_storage_sections_only`。
- 储能利用按运行弧上的储能区段标记处理；当前 `power_arm_intervals.csv` 仍给出 K145-K164、K164-K200.7 两段规划假设，但运行时不再固定这些公里标。替换 CSV 中的 `storage_available`、`storage_section_id` 和区间字段后，运行弧切分与储能 ID 会随数据更新。
- 若提供 `storage_start_km`、`storage_end_km`，运行时优先使用显式储能边界；当前形如 `storage_section_1:K145-K164` 的规划 ID 也可携带边界；任意不含公里标的正式 ID 则采用被标记供电臂的起止区间。
- 候选方案的能量目标为结算后的 `grid_kwh + effective_regen_loss_kwh`。后者包含弃电、储能转换损失和终端 SOC 影响，避免“充电后停放”被错误当作当期节能；供电臂牵引供电或再生吸收超限会计入约束违反量并使候选不可行。
- NSGA-II 排序使用约束支配：可行候选支配不可行候选，不可行候选之间优先选择违反度更小者；用户可选 Pareto 输出仅包含可行候选。
- `ranked_candidates.csv`、`pareto_candidates.csv` 和 `summary.json` 已增加储能充放电量、受限电量、最终 SOC、电气超限量和能量目标等字段。

再生电量目前按运行弧基础能耗与坡度/曲线修正后能耗的差值估算，并在运行弧构造时显式保存：

```text
terrain_adjusted_kwh = base_energy_kwh * energy_multiplier
regen_kwh = max(0, base_energy_kwh - terrain_adjusted_kwh) * 0.65
traction_kwh = max(base_energy_kwh, terrain_adjusted_kwh)
energy_kwh = traction_kwh - regen_kwh
```

下坡弧以基础电量作为牵引侧代理，只将上述按效率回收的部分计为再生节能；未回收部分不计为节能。上坡及曲线附加量仍进入牵引侧。结算时将 `energy_kwh` 视为净电量，以 `traction_kwh = energy_kwh + regen_kwh` 重构牵引侧，因此坡度收益只进入净电量一次。

这只是用于形成供电臂能量结算链路的工程原型。后续拿到机车牵引/制动曲线、速度曲线、列车质量和真实牵引功率后，应替换为更精确的牵引制动计算。

## 当前边界

当前原型已经把 OD 需求、重列服务、空列回送、装卸作业、虚拟车底、能力约束和真实基础设施属性统一到节点-弧段网络输出中，并能生成 ranked candidates 和 Pareto candidates。

运行弧已经按供电臂连续区间边界自动切分，并按运行方向匹配区间：公里标递增按下行，公里标递减按上行。当前连续区间表仍是推断草稿，因此 `power_arm_review_required=True` 会继续保留在输出中，提醒后续人工确认 `power_arm_id` 和区间边界。供电臂方向匹配同时接受真实表的 `上行/下行` 和虚拟模板的 `up/down`（以及模型的 `forward/reverse` 别名），避免虚拟数据下供电臂被误判为不匹配而绕过电气/储能约束。

平曲线表已按正式文件名导入；若输出中 `curve_positioned_count` 大于 0，则曲线会参与运行弧能耗修正。供电臂名称和部分边界仍带人工复核标记，当前优化器使用 `record_id` 和公里标范围进行归属。

当前仍是工程化前的 AGA/Pareto 原型，不等同于最终 AGA/SPEA2 求解器。后续真实 OD、车底周转、组合/拆解站作业能力、区段能力和机车能耗参数到位后，应继续替换模板数据，并进一步实现路径级重空列同步交叉、组合/拆解关系保护、容量修复、径路替换和真实网络流约束。

## 验证命令

```powershell
python tests\smoke\verify_heavy_empty_network_optimizer.py
```

项目 `.venv` 若要直接运行该模板读取流程，需要安装 `openpyxl`。
