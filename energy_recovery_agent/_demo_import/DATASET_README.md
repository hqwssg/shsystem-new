# 朔黄线真实数据集

本目录由 `tools/build_real_shuohuang_dataset.py` 生成，作为当前算法主线默认输入。

## 已导入的真实数据

- `stations.csv`：仅含线路图1/2/3覆盖的朔黄主线真实站点，终点为黄骅港 K583+003。
- `gradients.csv`：来自 `data/source/geometry/gradients.xlsx`。
- `curves.csv`：来自 `data/source/geometry/curves.xlsx`。
- `segments.csv`：由真实坡度、平曲线和限速信息合成，替代旧虚拟线路几何。
- `power_arm_intervals.csv`：来自 `data/source/power_arm/power_arm_continuous_intervals.xlsx`。
- `stations.csv`、`headway_constraints.csv`、`technical_operation_times.csv`：来自此前 PDF 真实资料整理结果。
- `train_formation_modes_2025.csv`：来自 2025 朔黄铁路编组模式资料。
- `smart_meter_calibration_samples.csv`：由 `smart_meter_calibration_builder.py` 生成；如重建本目录后需要重新运行该脚本。
- `energy_calibration_factors.json`：由 `energy_calibration_factor_builder.py` 生成；如重建本目录后需要重新运行该脚本。

## 规划虚拟预设（非官方，但可跑通流程）

- `battery.json`：两段规划储能区段的虚拟设备参数（20 MWh / 10 MW / η=0.90 / 电价 0.65 元/kWh / 折旧 0.25 元/kWh）。
- `trains.csv`：质量来自编组资料；牵引/制动/Davis/功率为工程虚拟预设。
- `energy_transfer_zones.csv`：K145-K164、K164-K200.7 两段规划储能区段虚拟预设。
- `data_templates/running_diagram_template.xlsx`：基于真实主线站点的虚拟运行图（时刻/停点为预设）。

## 明确未使用

- 未复制 `signaling_blocks.csv`：暂无真实闭塞分区数据。

## 仍为假设或待确认

- `battery.json`、`trains.csv`、运行图模板、储能区段边界均为规划/工程虚拟预设，不是正式设备或官方运行图。
- `power_arm_intervals.csv` 中供电臂最大牵引供电能力、最大再生吸收能力、回馈限制暂采用较大默认值，不作为当前原型瓶颈；后续有真实资料后替换。
- 朔黄上下行供电相互隔离，当前算法默认不计算直发直用；再生能量仅可在标记为储能可用的区段进入储能后利用。
- 当前储能可用区段按 K145-K164、K164-K200.7 两段规划假设标记，后续需按正式储能设备资料替换。
- 当前只建模朔黄线 K0-K583.003；神朔 SK、准池K 等接入线边界暂作为模型边界外记录，不参与运行模拟区间生成。
- 未标明线路名的 K、黄K/朔黄K 是否属于同一朔黄线连续里程体系仍需确认。
- `smart_meter_calibration_samples.csv` 的电量单位已按供应商答复按 kWh 理解；当前样本覆盖有限，仅用于原型对比，不作为最终工程校准。
- `energy_calibration_factors.json` 只用于对比和敏感性测试，不应作为最终工程 kWh 校准结论。
- 正式运行图仍需确认后才能做正式业务验证。
