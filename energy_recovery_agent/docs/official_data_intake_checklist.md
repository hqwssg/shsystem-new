# 正式数据接入清单（阻塞工程结论）

本清单对应当前目标中尚未到位的正式数据。本地算法、重建、smoke、实验样本与实验分组系数已具备；**没有下列正式资料，不能讨论正式节能率或储能容量优化结论**。

## 接入原则

若甲方无法一次提交全部资料，优先按 [`minimal_official_data_package.md`](minimal_official_data_package.md) 先提交阶段 A 的运行图、车辆动力学、供电臂电气能力和储能参数；闭塞、站场资源、库存和校准样本作为阶段 B 补齐。

1. 原始正式文件先放入 `shuohuang_data/` 或新建 `data/official_inbox/`，保留原始文件名与来源说明。
2. 算法直接读取的文件复制/转换为 `data/source/` 英文路径，再重建 `data/real_shuohuang/`。
3. 每个字段必须标注 `data_status`：
   - `official`：来自正式资料
   - `derived_from_official`：由正式资料推导
   - `planning_placeholder`：规划占位
   - `virtual_preset`：虚拟预设
4. 占位值只能用于流程验证/敏感性，不能写入正式结论。

## 1. 正式运行图

| 项目 | 要求 |
| --- | --- |
| 目标模板 | `data_templates/running_diagram_template.xlsx` |
| 接入表 | `trains` + `timetable` |
| 必需字段 | train_id, train_type, direction, origin/destination, mass_t 或编组字段, 站到站到发时刻 |
| 当前状态 | 仅有内部模板，非官方运行图 |
| 到位后动作 | 转换 → `audit-timetable` / `optimize-timetable` |
| 未到位限制 | 不能作为真实运输组织/运行图优化结论 |

建议提供：官方运行图电子表或导出文件 + 字段说明。若格式不同，先写 adapter 转到内部模板。

## 2. 牵引 / 制动 / Davis 参数

| 项目 | 要求 |
| --- | --- |
| 目标文件 | `data/real_shuohuang/trains.csv` |
| 必需字段 | mass_tons, max_traction_kN, max_brake_kN, rotational_mass_factor, davis_a/b/c, length_km, adhesion 相关字段 |
| 当前状态 | 质量部分有 PDF/场景代表值；动力学字段仍为虚拟占位 |
| 到位后动作 | 替换 trains.csv 动力学字段，重跑 simulate / experiment-suite / 校准对齐 |
| 未到位限制 | 能耗只能做原型趋势，不能报正式节能量 |

建议提供：机车/列车动力学参数表、编组与质量口径说明。

## 3. 供电臂电气能力

| 项目 | 要求 |
| --- | --- |
| 目标文件 | `data/real_shuohuang/power_arm_intervals.csv` |
| 必需字段 | max_traction_supply_kw, max_regen_absorption_kw, max_grid_feedback_kw, up_down_feed_rule, grid_feedback_rule |
| 当前状态 | 几何/边界已真实；电气限值是大默认非约束值 |
| 到位后动作 | 替换电气限值字段，重跑 dispatch/energy audit |
| 未到位限制 | 不能判断真实吸收能力瓶颈 |

建议提供：供电臂能力表、回馈/吸收限制、上下行隔离规则说明。

## 4. 储能参数与边界

| 项目 | 要求 |
| --- | --- |
| 目标文件 | `battery.json` + power_arm/storage 区段标记 |
| 必需字段 | capacity_kwh, max_charge/discharge_power_kW, round_trip_efficiency, 成本参数, 接入起终点公里标 |
| 当前状态 | 两段规划区段 K145–K164 / K164–K200.7 占位 |
| 到位后动作 | 替换 battery.json 与 storage 区段，重跑 storage_no_direct 场景 |
| 未到位限制 | 不能做储能容量/收益优化结论 |

建议提供：设备规格书、接入位置、SOC 约束、效率与成本口径。

## 5. 闭塞分区 / 信号通过能力

| 项目 | 要求 |
| --- | --- |
| 目标文件 | `signaling_blocks.csv`（当前主集有意省略） |
| 必需字段 | block_id, direction, start_km, end_km, capacity/headway 规则 |
| 当前状态 | 仅有虚拟模板 `data_templates/shuohuang_virtual/signaling_blocks.csv` |
| 到位后动作 | 接入主集并升级资源约束 |
| 未到位限制 | 资源可行性仍是启发式 |

## 6. 初始车流库存

| 项目 | 要求 |
| --- | --- |
| 目标文件 | `resource_config.json` 或独立 inventory 表 |
| 必需字段 | initial_heavy_flow_count, initial_empty_flow_count（或更细站段库存） |
| 当前状态 | 场景假设库存 |
| 到位后动作 | 替换库存并重跑 flow continuity 校验 |
| 未到位限制 | 车流连续性只适合流程验证 |

## 7. 电表校准口径（补充确认）

虽已生成非零实验样本与分组系数，但仍需确认：

1. SS4 `A/B` 双表是否正式按求和聚合（当前证据强烈支持 `58A+58B` / `151A+151B`）。
2. 主线外站点（如敬业、大吾、港口场）是否纳入主线模型。
3. 零能耗/短停样本是否排除出工程拟合。

当前默认：
- 使用 A/B 聚合
- 仅主线 `stations.csv` 可映射、非零距离、非零牵引样本进入发布集
- `enabled_by_default=false`

## 8. 正式接入前的可执行验收门禁

以下门禁全部通过后，才允许把结果称为“正式数据结果”。任一项未通过，只能保留为流程验证或敏感性分析。

### A. 文件与版本

- [ ] 原始文件保存在 `data/official_inbox/`，未覆盖历史来源文件。
- [ ] 每个文件有来源、采集时间、责任人和版本号。
- [ ] 已生成接入前 SHA-256 清单，文件大小和数量与交付单一致。
- [ ] 字段映射表已确认，单位、编码、时区和小数精度明确。

### B. 数据内容与物理约束

- [ ] 运行图列车 ID、方向、站点和到发时刻完整且无重复。
- [ ] 车辆质量、牵引、制动、Davis 参数和编组口径通过范围校验。
- [ ] 供电臂边界连续、无反向区间错误，牵引/回馈能力不再使用无限大占位值。
- [ ] 储能容量、功率、效率、SOC 范围和接入区段与设备规格书一致。
- [ ] 闭塞分区、站场股道、咽喉和区间能力可关联到运行图资源。
- [ ] 初始重车/空车库存与业务台账一致，车流守恒检查通过。

### C. 来源可信度与占位清理

- [ ] 所有关键字段标记为 `official` 或 `derived_from_official`。
- [ ] 不存在未确认的 `planning_placeholder` 或 `virtual_preset` 参与正式结论。
- [ ] 校准样本的 A/B 表聚合、主线范围、零能耗样本排除规则已书面确认。
- [ ] `formal_data_acceptance.py` 报告为 `accepted=true`，错误数为 0。

### D. 算法与结果复核

- [ ] `python run_project.py validate-data --data-dir <正式目录>` 通过。
- [ ] `python run_project.py check-ingestion --kind all` 通过。
- [ ] `python run_project.py simulate --data-dir <正式目录>` 成功完成。
- [ ] `python run_project.py check-results --output-root <输出目录>` 报告为可接受。
- [ ] 能量守恒、SOC 边界、资源冲突和汇总一致性无错误。
- [ ] 运行清单记录代码快照、输入 SHA-256、参数摘要、环境依赖和输出 SHA-256。

### E. 发布审批

- [ ] 与当前合成回归基线比较，所有差异都有解释。
- [ ] 至少重复运行 3 次，固定代码、输入、随机种子和硬件后结果稳定。
- [ ] 节能率、储能容量和收益结论经过业务负责人和数据负责人双签。
- [ ] 正式报告明确列出剩余假设、缺失字段和适用范围。

## 推荐目录落位

```text
data/official_inbox/
  README.md
  timetable/
  vehicle_dynamics/
  power_arm_electrical/
  storage/
  signaling/
  inventory/
data/source/                  # 英文名、算法直接读取
data/real_shuohuang/          # 重建后的默认运行输入
data_templates/official_intake/ # 空白填报模板
```

## 到位后的最短验证链

```powershell
python run_project.py build-data --data-dir data/real_shuohuang --source-dir data/source
python run_project.py validate-data --data-dir data/real_shuohuang
python run_project.py calibrate-energy --overlap-policy exclude --publish-calibration
python run_project.py simulate --data-dir data/real_shuohuang
python run_project.py experiment-suite --data-dir data/real_shuohuang
python run_project.py audit-timetable --timetable <converted_official_timetable.xlsx>
```

## 当前本地已完成（对照）

- data/source 重建并替换默认 real_shuohuang
- 当前共99项 smoke，其中默认94项短耗时检查和5项长耗时专项；另有2个集成长测纳入独立性能门禁；validate/simulate/experiment 产物已刷新
- 文档/CLI/单位口径修正
- 非零实验校准样本 + 可用分组系数（主线精炼后发布）

## 当前仍阻塞

- 正式运行图
- 正式车辆动力学
- 正式供电臂电气能力
- 正式储能参数/边界
- 正式闭塞分区
- 正式初始车流库存

?????
- SS4 ???????? `A+B`????/?????????????????????
- ???? 1/2/3 ?? 33 ????/??/?????????????
- ???/??/???/??????????????? `fit_core` ??
- ????????????? 4320 t??? 2160/2668/3036/4320
- `enabled_by_default=false`

Dry-run?

```powershell
python run_project.py official-intake-dry-run --update-status
# ?
python tools/official_intake_dry_run.py --update-status
```

