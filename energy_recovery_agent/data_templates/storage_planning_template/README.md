# 储能选址定容规划输入模板

本目录是一套可直接复制填报、并能通过结构校验的规划占位模板。示例数值只用于说明字段格式，全部标记为 `planning_placeholder`。

使用步骤：

1. 复制整个目录，不要修改五个合同文件名和表头；
2. 用候选站点、电气接入、设备规格、成本、场景和规划策略资料替换示例值；
3. 未经确认的记录继续保留 `planning_placeholder`，正式来源才可标记为 `official` 或 `derived_from_official`；
4. 运行 `python run_project.py validate-storage-planning --input-dir <填报目录>`；
5. 只有校验通过的目录才能进入后续规划求解阶段。

CSV 多值字段 `allowed_technology_codes` 使用竖线 `|` 分隔。距离、功率、能量和金额单位固定为 km、kW、kWh、元。场景必须使用概率权重，权重之和为 1。

