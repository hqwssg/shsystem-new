# 当前数据缺口与后续动作

本文与当前算法可信边界配套，记录“现在能做 / 还不能下正式结论 / 需要哪些正式数据”。

## 已完成并可复现（2026-09-09 复核）

- 算法直接消耗源文件已收敛到 `data/source/`（英文文件名）。
- 默认算法输入 `data/real_shuohuang/` 已由 `data/source` 完整重建并替换。
- 主线范围：K0–K583.003，33 站，终点 `黄骅港`。
- 主场景：`storage_no_direct`（禁止直发直用，仅储能复用规划区段）。
- `tests/smoke/` 当前共有101个 `verify_*.py`，默认短耗时 smoke 运行96个，另有5个长耗时专项；2个集成长测与这5项共同纳入性能门禁。上一轮候选已在Python 3.12.13下完成7/7项长测和9/9次独立执行，新候选以其独立验收报告为准。生产保障专项覆盖本地/生产状态分离、告警边界和恢复安全约束。异常与极端输入总套件覆盖4934个可枚举案例/专项并通过，其中随机合成差分4800/4800、实时异常40/40、静态数据异常29/29、平台参数49/49、核心极端场景10/10，另有6个深层合同专项。`validate-data` 和缩小规模 `simulate` 端到端流程通过。
- 智能电表校准已形成主线可对齐非零实验样本和历史实验系数；新增独立验证质量门禁后，现有数据未达到正式系数发布条件。
- 正式数据接入清单与空白模板已准备：`docs/official_data_intake_checklist.md`、`data_templates/official_intake/`、`data/official_inbox/`。
- 正式数据到件自动触发已准备：最终标记与逐文件哈希核验、冻结快照、幂等账本、完整工程仿真、结果质量审计和正式对比总控可由 `official-data-auto-trigger` 自动串联；当前因尚无正式交付包而处于 `waiting` 属正常状态。

## 仍缺正式数据（阻塞工程结论）

| 数据 | 当前状态 | 未到位时限制 |
| --- | --- | --- |
| 正式运行图 | 只有 `data_templates/running_diagram_template.xlsx` 预设模板 | 不能作为真实运输组织/运行图优化结论 |
| 牵引/制动/Davis 参数 | `trains.csv` 中动力学字段仍为工程占位 | 能耗只能做原型趋势，不能报正式节能量 |
| 供电臂电气能力 | `power_arm_intervals.csv` 使用大默认非约束值 | 不能判断真实吸收能力瓶颈 |
| 储能设备参数与边界 | `battery.json` + 两段规划区段 K145–K164 / K164–K200.7 | 不能做储能容量/收益优化结论 |
| 闭塞分区/信号通过能力 | 主集有意省略 `signaling_blocks.csv` | 资源可行性仍是启发式 |
| 初始车流库存 | `resource_config.json` 中场景库存 | 车流连续性只适合流程验证 |

## 校准样本现状（当前发布文件口径）

### 关键发现
- 旧 smoke 0 样本主因是行数截断，不是完全无重叠。
- 单表匹配大量呈“实时能耗 ≈ 站段一半”；必须使用 `58A+58B` / `151A+151B` 聚合。
- 全量 A/B 候选 1172 条中，只有主线可映射且非零距离/非零牵引样本适合发布。

### 历史实验集（`data/real_shuohuang`，默认关闭）
- 选择策略：`mainline_mapped_nonzero_traction_from_ab_aggregation`
- 发布样本总数：**532**
- 过滤：
  - 排除 station 未映射：386
  - 排除零距离：248
  - 排除零能耗/非可用状态后保留 532
- 可对齐非零牵引：532（全部 aligned）
- 当前实验拟合核心样本：**178**（见 `docs/official_data_intake_status.json`）
- 全局实验系数：`traction_scale≈0.99517`
- 可用分组系数：
  - `down|aggregated_ab≈0.943459`
  - `up|aggregated_ab≈1.019481`
  - `aggregated_ab≈0.995169`
- 当前实验拟合核心的中位绝对百分误差约 **36.49%**；该系数默认不启用。
- `enabled_by_default=false`，`data_status=experimental_kwh_calibration`

### 2026-09-04 独立留出审计

- 全量匹配 1721 条、高可信候选 1172 条，经代表性和主线过滤后为 48 条。
- 其中仅 16 条进入 `fit_core`；确定性拆分后拟合 13 条、验证 3 条，均低于默认门槛 30/10。
- 留出集中位 APE 从未校准的 62.37% 变为校准后的 68.37%，未形成样本外改善。
- 新质量门禁结论为 `publication_ready=false`，没有生成或发布新系数。历史 532/178 资料只能作为实验诊断材料，不能再称为“可用正式校准”。
- 结果见 `paper/experiments/model_meter_calibration_current/`；后续优先提供不同日期/来源批次的对齐样本，通过 `--validation-alignment-csv` 做外部验证。

### 详细输出
- `outputs/energy_calibration_pipeline_ab/`
- `outputs/energy_calibration_mainline_refined/`
- `docs/official_data_intake_checklist.md`

### 仍不能下正式节能/容量结论的原因
1. 车辆动力学/运行图/供电臂/储能/闭塞/库存正式参数仍缺。
2. 系数仍是历史实验口径，默认不启用，且未通过新增的独立验证质量门禁。
3. 拟合核心中位误差仍约 36%，物理模型未完成工程定标。
4. 鲁棒样本主要由 `58A+58B` 支撑，车次覆盖有限。

## 建议下一步

在正式车辆、储能和供电参数到位前，可使用 `tools_energy_sensitivity_scan.py --only-interval` 做储能快速角点诊断，并使用 `python run_project.py benchmark-joint-parameter-robustness` 做车辆动力学、储能、电气上限和运行扰动的联合稳健评价。正式数据到位后必须用经确认的测量误差或设备容差区间替换规划区间并重跑。

1. 按 `docs/official_data_intake_checklist.md` 收集并投递正式数据到 `data/official_inbox/`。
2. 数据到位后先运行 `python run_project.py accept-official-data`；验收通过后再运行完整 `simulate`，最后运行 `python run_project.py check-results --output-root <输出目录>`。
3. 正式运行图到位后转换模板，重跑 `audit-timetable` / `optimize-timetable`。
4. 用正式车辆参数替换 `trains.csv` 动力学占位字段。
5. 用正式供电臂能力与储能资料替换电气/储能占位字段。
6. 提供闭塞分区与初始车流库存后，升级资源与连续性约束。
7. 正式参数到位、误差收敛到工程可接受范围前，不讨论正式节能率或容量优化结论。
